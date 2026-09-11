"""Single controlled acceptance driver for C012.

The driver is deliberately kept outside the application package.  It starts
only resources that it owns, talks to the production application through its
normal HTTP/WebSocket routes, and records non-sensitive run metadata beside
the raw command logs.  The later C012 commands extend this same entry point;
they must not become alternate production handlers or database seed paths.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import httpx
from pydantic import ValidationError
import websockets.asyncio.client


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
EVIDENCE_DIR = ROOT / ".work" / "c012"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class AcceptanceFailure(RuntimeError):
    """A deterministic acceptance observation did not meet its contract."""


C012_SPEC_PATH = ROOT / "openspec" / "changes" / "c012" / "spec.md"
M6_SCRIPT_PATH = BACKEND / "deployment" / "m6-script.txt"
M6_APPEND_SENTENCE = "球馆内，工作人员陈宁走到芳嘉蔓身边递给她一张入场券。"
M6_CLIP_TARGETS = (
    "芳嘉蔓进门催促、乔彦茜抬眼回应后继续吃饭",
    "芳嘉蔓指向出场球员、乔彦茜由平静变为僵住",
)


@dataclass(frozen=True, slots=True)
class ChildResult:
    command: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    termination_requested: bool = False

    def text_stdout(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    def text_stderr(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


@dataclass(frozen=True, slots=True)
class HttpObservation:
    status_code: int
    body: object


@dataclass(slots=True)
class RunEvidence:
    command: str
    args: list[str]
    status: str = "running"
    error: str | None = None
    events: list[dict[str, object]] = field(default_factory=list)

    def add(self, name: str, **values: object) -> None:
        self.events.append({"name": name, **values})

    def finish(self, *, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error

    def write(self) -> Path:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE_DIR / f"{self.command}-acceptance.json"
        payload = {
            "command": self.command,
            "args": self.args,
            "cwd": str(Path.cwd()),
            "repository_root": str(ROOT),
            "commit": git_commit(),
            "pid": os.getpid(),
            "status": self.status,
            "error": self.error,
            "events": self.events,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def explicit_runtime() -> tuple[str, Path, dict[str, str]]:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise AcceptanceFailure(
            "DATABASE_URL must be explicitly exported for C012; refusing .env fallback"
        )
    if not raw_url.startswith("postgresql+asyncpg://"):
        raise AcceptanceFailure(
            "DATABASE_URL must use the postgresql+asyncpg scheme"
        )
    raw_data_dir = os.environ.get("DATA_DIR")
    if not raw_data_dir:
        raise AcceptanceFailure(
            "DATA_DIR must be explicitly exported for C012; refusing default data/"
        )
    data_dir = Path(raw_data_dir).resolve()
    if not data_dir.is_dir():
        raise AcceptanceFailure(f"DATA_DIR does not exist: {data_dir}")
    parsed = urlsplit(raw_url)
    if not parsed.hostname or not parsed.path.strip("/"):
        raise AcceptanceFailure("DATABASE_URL must include host and database")
    safe_identity = {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "database_from_url": parsed.path.lstrip("/"),
        "user": parsed.username or "",
    }
    return raw_url, data_dir, safe_identity


async def read_database_identity(raw_url: str) -> dict[str, object]:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", ""))
    try:
        row = await connection.fetchrow(
            "SELECT current_database(), current_user, "
            "inet_server_addr()::text, inet_server_port()"
        )
    finally:
        await connection.close()
    if row is None:
        raise AcceptanceFailure("database identity query returned no row")
    return {
        "current_database": row[0],
        "current_user": row[1],
        "server_address": row[2],
        "server_port": row[3],
    }


async def read_database_tasks(raw_url: str) -> list[dict[str, object]]:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", ""))
    try:
        rows = await connection.fetch(
            "SELECT id, type, target_id, request_id, status, progress, "
            "error_msg, cancel_requested_at, created_at, started_at, "
            "finished_at, payload FROM tasks ORDER BY id"
        )
    finally:
        await connection.close()
    result: list[dict[str, object]] = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "type": row["type"],
                "target_id": row["target_id"],
                "request_id": row["request_id"],
                "status": row["status"],
                "progress": row["progress"],
                "error_msg": row["error_msg"],
                "cancel_requested_at": (
                    row["cancel_requested_at"].isoformat()
                    if row["cancel_requested_at"] is not None
                    else None
                ),
                "created_at": row["created_at"].isoformat(),
                "started_at": (
                    row["started_at"].isoformat()
                    if row["started_at"] is not None
                    else None
                ),
                "finished_at": (
                    row["finished_at"].isoformat()
                    if row["finished_at"] is not None
                    else None
                ),
                "payload": row["payload"],
            }
        )
    return result


def runtime_settings() -> Any:
    """Load the same settings file used by a backend process started in backend/."""

    from app.core.config import Settings

    try:
        return Settings(_env_file=BACKEND / ".env")
    except ValidationError as exc:
        raise AcceptanceFailure(
            f"backend settings are invalid: {exc}"
        ) from exc


def read_frozen_m6_script() -> tuple[str, dict[str, object]]:
    try:
        spec_text = C012_SPEC_PATH.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AcceptanceFailure(
            f"cannot read UTF-8 C012 spec for script provenance: {exc}"
        ) from exc
    match = re.search(
        r"### 6\.1 冻结首轮剧本\r?\n.*?```text\r?\n"
        r"(?P<body>.*?)\r?\n```",
        spec_text,
        flags=re.DOTALL,
    )
    if match is None:
        raise AcceptanceFailure("C012 spec §6.1 script code block was not found")
    script = match.group("body")
    if "```" in script:
        raise AcceptanceFailure("C012 spec §6.1 script contains a nested fence")
    return script, {
        "path": str(C012_SPEC_PATH),
        "section": "§6.1 冻结首轮剧本",
        "code_fence": "text",
        "characters": len(script),
        "utf8_bytes": len(script.encode("utf-8")),
        "ends_with_lf": script.endswith("\n"),
        "ends_with_crlf": script.endswith("\r\n"),
    }


def read_utf8_file(path: Path, label: str) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AcceptanceFailure(f"{label} is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise AcceptanceFailure(f"cannot read {label} {path}: {exc}") from exc


def safe_service_url(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise AcceptanceFailure(f"{label} is not a text URL")
    parsed = urlsplit(value.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AcceptanceFailure(f"{label} is not an HTTP URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


async def real_http_request(
    base_url: str,
    method: str,
    path: str,
    *,
    params: Mapping[str, object] | None = None,
    timeout: float = 10.0,
) -> HttpObservation:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            trust_env=False,
        ) as client:
            response = await client.request(method, url, params=params)
    except (httpx.RequestError, TimeoutError) as exc:
        raise AcceptanceFailure(f"{method} {url} failed: {exc}") from exc
    try:
        body: object = response.json()
    except ValueError:
        body = response.text
    return HttpObservation(response.status_code, body)


def require_http_success(
    observation: HttpObservation, *, method: str, url: str
) -> object:
    if not 200 <= observation.status_code < 300:
        raise AcceptanceFailure(
            f"{method} {url} returned HTTP {observation.status_code}: "
            f"{observation.body!r}"
        )
    return observation.body


def require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AcceptanceFailure(f"{label} was not a JSON object")
    return value


def listener_ports(urls: Sequence[str]) -> list[int]:
    ports: set[int] = set()
    for url in urls:
        parsed = urlsplit(url)
        if parsed.port is not None:
            ports.add(parsed.port)
        elif parsed.scheme == "https":
            ports.add(443)
        else:
            ports.add(80)
    return sorted(ports)


def observe_windows_listeners(ports: Sequence[int]) -> dict[str, object]:
    """Read listener/PID ownership without starting or stopping any process."""

    if not ports:
        return {"ports": [], "listeners": []}
    port_list = ",".join(str(port) for port in ports)
    script = (
        "$ports=@(" + port_list + "); "
        "$rows=Get-NetTCPConnection -State Listen -ErrorAction Stop | "
        "Where-Object {$ports -contains $_.LocalPort} | "
        "Select-Object LocalAddress,LocalPort,OwningProcess; "
        "@($rows) | ConvertTo-Json -Compress"
    )
    result = run_child(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        timeout=10.0,
    )
    if result.timed_out or result.returncode != 0:
        raise AcceptanceFailure(
            "listener ownership query failed: "
            f"rc={result.returncode} timeout={result.timed_out} "
            f"stderr={result.text_stderr()!r}"
        )
    try:
        value = json.loads(result.text_stdout() or "[]")
    except json.JSONDecodeError as exc:
        raise AcceptanceFailure(
            f"listener ownership query returned invalid JSON: {result.text_stdout()!r}"
        ) from exc
    if isinstance(value, Mapping):
        listeners: object = [value]
    elif isinstance(value, list):
        listeners = value
    else:
        raise AcceptanceFailure("listener ownership query returned an invalid list")
    return {
        "ports": list(ports),
        "listeners": listeners,
        "query": child_observation(result),
    }


def run_child(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> ChildResult:
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=None if env is None else dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    return ChildResult(
        command=tuple(str(part) for part in command),
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )


def stop_process(process: subprocess.Popen[bytes], timeout: float = 10.0) -> ChildResult:
    termination_requested = process.poll() is None
    if termination_requested:
        process.terminate()
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    return ChildResult(
        command=tuple(str(part) for part in process.args),
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        termination_requested=termination_requested,
    )


class ControlledHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class HealthStubHandler(BaseHTTPRequestHandler):
    """Health-only dependency stub used solely by the selfcheck."""

    server_version = "C012Selfcheck/1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path == "/system_stats":
            self._send_json(200, {"system": "ok"})
        elif self.path == "/is_sleeping":
            self._send_json(200, {"is_sleeping": False})
        elif self.path == "/queue":
            self._send_json(200, {"queue_running": [], "queue_pending": []})
        elif self.path == "/v1/models":
            self._send_json(
                200,
                {"data": [{"id": os.environ.get("VLLM_MODEL", "controlled-model")}]},
            )
        elif self.path.startswith("/history/"):
            prompt_id = self.path.rsplit("/", 1)[-1]
            self._send_json(
                200,
                {
                    prompt_id: {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "168": {
                                "gifs": [
                                    {
                                        "filename": "controlled.mp4",
                                        "subfolder": "",
                                        "type": "output",
                                        "format": "video/h264-mp4",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        else:
            self._send_json(404, {"detail": "selfcheck route not provided"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            body = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            body = {}
        if self.path in {"/wake_up", "/sleep", "/free", "/interrupt"}:
            self._send_json(200, {})
        elif self.path == "/prompt":
            prompt_id = body.get("prompt_id") if isinstance(body, dict) else None
            self._send_json(200, {"prompt_id": prompt_id})
        elif self.path == "/v1/chat/completions":
            response_format = body.get("response_format", {}) if isinstance(body, dict) else {}
            schema = response_format.get("json_schema", {}) if isinstance(response_format, dict) else {}
            schema_name = schema.get("name") if isinstance(schema, dict) else None
            if schema_name == "script2assets":
                content = {"assets": []}
            elif schema_name == "script2shots":
                content = {"shots": []}
            else:
                content = {"prompt": "controlled acceptance prompt"}
            self._send_json(
                200,
                {
                    "choices": [
                        {"message": {"content": json.dumps(content, ensure_ascii=False)}}
                    ]
                },
            )
        else:
            self._send_json(404, {"detail": "selfcheck route not provided"})

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class ControlledHTTPStub:
    def __init__(self) -> None:
        self.server = ControlledHTTPServer(("127.0.0.1", 0), HealthStubHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="c012-selfcheck-http-stub",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "ControlledHTTPStub":
        self.thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AcceptanceFailure("owned HTTP stub thread did not stop")


def controlled_mp4_bytes() -> bytes:
    """Create one legal, deterministic offline video for the controlled path."""

    import av

    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp4")
    stream = container.add_stream("libx264", rate=24)
    stream.width = 320
    stream.height = 180
    stream.pix_fmt = "yuv420p"
    for _ in range(24):
        frame = av.VideoFrame(320, 180, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


class ControlledComfyStub:
    """A local HTTP/WebSocket Comfy boundary for the real worker path."""

    _WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, *, response_mode: str = "empty") -> None:
        self.server: asyncio.AbstractServer | None = None
        self.video = controlled_mp4_bytes()
        self.upload_count = 0
        self.response_mode = response_mode
        self.chat_observations: list[dict[str, object]] = []

    @property
    def base_url(self) -> str:
        if self.server is None or not self.server.sockets:
            raise AcceptanceFailure("controlled Comfy stub is not started")
        host, port = self.server.sockets[0].getsockname()[:2]
        return f"http://{host}:{port}"

    async def __aenter__(self) -> "ControlledComfyStub":
        self.server = await asyncio.start_server(
            self._handle_connection,
            host="127.0.0.1",
            port=0,
        )
        return self

    async def __aexit__(
        self,
        _type: object,
        _value: object,
        _traceback: object,
    ) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        headers: dict[str, str] = {}
        is_websocket = False
        try:
            header_bytes = await reader.readuntil(b"\r\n\r\n")
            header_lines = header_bytes[:-4].split(b"\r\n")
            request_line = header_lines[0].decode("ascii")
            method, raw_path, _version = request_line.split(" ", 2)
            for line in header_lines[1:]:
                key, value = line.decode("latin-1").split(":", 1)
                headers[key.strip().lower()] = value.strip()
            if headers.get("upgrade", "").casefold() == "websocket":
                is_websocket = True
                await self._handle_websocket(raw_path, headers, reader, writer)
                return
            body_length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(body_length) if body_length else b""
            await self._handle_http(method, raw_path, body, writer)
        except (asyncio.IncompleteReadError, ValueError, ConnectionError):
            writer.close()
        finally:
            if not is_websocket:
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass

    async def _handle_http(
        self,
        method: str,
        raw_path: str,
        body: bytes,
        writer: asyncio.StreamWriter,
    ) -> None:
        path = urlsplit(raw_path).path
        payload: object
        status = 200
        content_type = "application/json"
        response_body: bytes
        if method == "GET" and path == "/health":
            payload = {"status": "ok"}
            response_body = json.dumps(payload).encode("utf-8")
        elif method == "GET" and path == "/system_stats":
            response_body = b'{"system":"ok"}'
        elif method == "GET" and path == "/is_sleeping":
            response_body = b'{"is_sleeping":false}'
        elif method == "GET" and path == "/queue":
            response_body = b'{"queue_running":[],"queue_pending":[]}'
        elif method == "GET" and path == "/v1/models":
            model = os.environ.get("VLLM_MODEL", "controlled-model")
            response_body = json.dumps({"data": [{"id": model}]}).encode("utf-8")
        elif method == "GET" and path.startswith("/history/"):
            prompt_id = path.rsplit("/", 1)[-1]
            response_body = json.dumps(
                {
                    prompt_id: {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "168": {
                                "gifs": [
                                    {
                                        "filename": "controlled.mp4",
                                        "subfolder": "",
                                        "type": "output",
                                        "format": "video/h264-mp4",
                                    }
                                ]
                            }
                        },
                    }
                }
            ).encode("utf-8")
        elif method == "GET" and path == "/view":
            content_type = "video/mp4"
            response_body = self.video
        elif method == "POST" and path == "/prompt":
            try:
                request_body = json.loads(body or b"{}")
            except json.JSONDecodeError:
                request_body = {}
            prompt_id = request_body.get("prompt_id") if isinstance(request_body, dict) else None
            response_body = json.dumps({"prompt_id": prompt_id}).encode("utf-8")
        elif method == "POST" and path == "/upload/image":
            self.upload_count += 1
            response_body = json.dumps(
                {
                    "name": f"subject{self.upload_count}.png",
                    "subfolder": "c012-controlled",
                    "type": "input",
                }
            ).encode("utf-8")
        elif method == "POST" and path == "/v1/chat/completions":
            try:
                request_body = json.loads(body or b"{}")
            except json.JSONDecodeError:
                request_body = {}
            response_format = request_body.get("response_format", {}) if isinstance(request_body, dict) else {}
            json_schema = response_format.get("json_schema", {}) if isinstance(response_format, dict) else {}
            schema_name = json_schema.get("name") if isinstance(json_schema, dict) else None
            if schema_name == "script2assets":
                model_content = self._model_content(request_body, schema_name)
            elif schema_name == "script2shots":
                model_content = self._model_content(request_body, schema_name)
            else:
                model_content = {"prompt": "controlled acceptance prompt"}
            response_payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                model_content,
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
            response_body = json.dumps(
                response_payload,
                ensure_ascii=False,
            ).encode("utf-8")
            self.chat_observations.append(
                {
                    "schema_name": schema_name,
                    "request_raw_utf8": body.decode("utf-8"),
                    "request": request_body,
                    "response_raw_utf8": response_body.decode("utf-8"),
                    "response": response_payload,
                    "parsed_model_content": model_content,
                }
            )
        elif method == "POST" and path in {"/wake_up", "/sleep", "/free", "/interrupt"}:
            response_body = b"{}"
        else:
            status = 404
            response_body = b'{"detail":"controlled route not provided"}'
        await self._write_http_response(writer, status, content_type, response_body)

    def _model_content(
        self,
        request_body: dict[str, object],
        schema_name: str,
    ) -> dict[str, object]:
        if self.response_mode != "t27-browser":
            return {"assets": []} if schema_name == "script2assets" else {"shots": []}

        if schema_name == "script2assets":
            messages = request_body.get("messages")
            if not isinstance(messages, list) or len(messages) != 1:
                raise ValueError("T27 browser assets request must contain one message")
            message = messages[0]
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("T27 browser assets request message is invalid")
            content = message["content"]
            snapshot_marker = "# 项目已有资产"
            if snapshot_marker in content:
                content = content.split(snapshot_marker, 1)[1]
                line_end = content.find("\n")
                if line_end < 0:
                    raise ValueError("T27 browser assets prompt snapshot header is incomplete")
                content = content[line_end + 1 :]
            content = content.lstrip()
            try:
                existing_assets, _end = json.JSONDecoder().raw_decode(content)
            except json.JSONDecodeError as exc:
                raise ValueError("T27 browser assets prompt must start with JSON assets") from exc
            if not isinstance(existing_assets, list) or not existing_assets:
                raise ValueError("T27 browser assets prompt must contain existing assets")
            assets: list[dict[str, object]] = []
            for item in existing_assets:
                if not isinstance(item, dict) or set(item) != {"id", "type", "name", "description"}:
                    raise ValueError("T27 browser existing asset snapshot is invalid")
                assets.append(
                    {
                        "existing_id": item["id"],
                        "type": item["type"],
                        "name": item["name"],
                        "description": item["description"],
                    }
                )
            return {"assets": assets}

        response_format = request_body.get("response_format")
        if not isinstance(response_format, dict):
            raise ValueError("T27 browser shots response format is invalid")
        json_schema = response_format.get("json_schema")
        if not isinstance(json_schema, dict):
            raise ValueError("T27 browser shots schema is invalid")
        schema = json_schema.get("schema")
        if not isinstance(schema, dict):
            raise ValueError("T27 browser shots schema body is invalid")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("T27 browser shots schema properties are invalid")
        shots_schema = properties.get("shots")
        if not isinstance(shots_schema, dict):
            raise ValueError("T27 browser shots array schema is invalid")
        items = shots_schema.get("items")
        if not isinstance(items, dict):
            raise ValueError("T27 browser shot item schema is invalid")
        item_properties = items.get("properties")
        if not isinstance(item_properties, dict):
            raise ValueError("T27 browser shot item properties are invalid")
        asset_ids_schema = item_properties.get("asset_ids")
        if not isinstance(asset_ids_schema, dict):
            raise ValueError("T27 browser shot asset schema is invalid")
        asset_items = asset_ids_schema.get("items")
        if not isinstance(asset_items, dict):
            raise ValueError("T27 browser shot asset item schema is invalid")
        allowed_asset_ids = asset_items.get("enum")
        shot_type_schema = item_properties.get("shot_type")
        camera_schema = item_properties.get("camera")
        if (
            not isinstance(allowed_asset_ids, list)
            or not allowed_asset_ids
            or not isinstance(shot_type_schema, dict)
            or not isinstance(camera_schema, dict)
            or not isinstance(shot_type_schema.get("enum"), list)
            or not shot_type_schema["enum"]
            or not isinstance(camera_schema.get("enum"), list)
            or not camera_schema["enum"]
        ):
            raise ValueError("T27 browser shots schema enums are invalid")
        first_asset = allowed_asset_ids[0]
        second_asset = allowed_asset_ids[min(1, len(allowed_asset_ids) - 1)]
        shot_type = shot_type_schema["enum"][0]
        camera = camera_schema["enum"][0]
        return {
            "shots": [
                {
                    "order": 1,
                    "duration_est": 1.0,
                    "shot_type": shot_type,
                    "camera": camera,
                    "description": "controlled generated shot one",
                    "dialogue": "",
                    "asset_ids": [first_asset],
                },
                {
                    "order": 2,
                    "duration_est": 1.0,
                    "shot_type": shot_type,
                    "camera": camera,
                    "description": "controlled generated shot two",
                    "dialogue": "",
                    "asset_ids": [second_asset],
                },
            ]
        }

    async def _write_http_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        content_type: str,
        body: bytes,
    ) -> None:
        reason = "OK" if status == 200 else "Not Found"
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body
        writer.write(response)
        await writer.drain()
        writer.close()

    async def _handle_websocket(
        self,
        raw_path: str,
        headers: Mapping[str, str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        key = headers.get("sec-websocket-key")
        if not key:
            writer.close()
            return
        accept = base64.b64encode(
            hashlib.sha1((key + self._WEBSOCKET_GUID).encode("ascii")).digest()
        ).decode("ascii")
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii")
        )
        await writer.drain()
        query = urlsplit(raw_path).query
        prompt_id = query.split("clientId=", 1)[-1].split("&", 1)[0]
        message = json.dumps(
            {"type": "execution_success", "data": {"prompt_id": prompt_id}}
        ).encode("utf-8")
        if len(message) >= 126:
            raise AcceptanceFailure("controlled websocket message unexpectedly exceeded 125 bytes")
        writer.write(bytes((0x81, len(message))) + message)
        await writer.drain()
        try:
            await asyncio.wait_for(reader.read(4096), timeout=2)
        except (asyncio.TimeoutError, ConnectionError):
            pass
        writer.close()


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def wait_for_http(
    url: str, *, timeout: float = 20.0, expect_json: bool = True
) -> HttpObservation:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url)
            except (httpx.RequestError, TimeoutError) as exc:
                last_error = str(exc)
            else:
                if not expect_json:
                    return HttpObservation(response.status_code, response.text)
                try:
                    body = response.json()
                except ValueError as exc:
                    raise AcceptanceFailure(
                        f"HTTP {url} returned non-JSON response: {exc}"
                    ) from exc
                return HttpObservation(response.status_code, body)
            await asyncio.sleep(0.1)
    raise AcceptanceFailure(f"HTTP endpoint did not respond: {url}; {last_error}")


def child_observation(result: ChildResult) -> dict[str, object]:
    return {
        "command": list(result.command),
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "stdout": result.text_stdout(),
        "stderr": result.text_stderr(),
        "termination_requested": result.termination_requested,
    }


def assert_child_success(result: ChildResult, label: str) -> None:
    if result.timed_out or result.returncode != 0:
        raise AcceptanceFailure(
            f"{label} did not exit 0: rc={result.returncode}, timeout={result.timed_out}"
        )


MIGRATION_PREVIOUS_HEAD = "6b8e3f0a1d24"
MIGRATION_NEW_HEAD = "c012_asset_name_unique"
MIGRATION_DEPENDENCY_QUERIES = {
    "episodes":
    "SELECT id, project_id, seq, title, script_text, script_revision, "
    "assets_generated_script_revision, shots_generated_script_revision "
    "FROM episodes ORDER BY id",
    "asset_images":
    "SELECT id, asset_id, file_path, sha256, seed, source, is_current, "
    "built_prompt, input_hash, input_snapshot, user_note "
    "FROM asset_images ORDER BY id",
    "shots":
    "SELECT id, episode_id, order_index, duration_est, shot_type, camera, "
    "description, dialogue, status, revision FROM shots ORDER BY id",
    "clips":
    "SELECT id, episode_id, generation_mode, user_note, requested_duration, "
    "prompt_cache, prompt_input_hash, generation_state, freshness, revision "
    "FROM clips ORDER BY id",
    "clip_ref_slots":
    "SELECT id, clip_id, slot_no, asset_id, asset_name_snapshot, "
    "asset_type_snapshot, override_image_path, override_sha256, enabled "
    "FROM clip_ref_slots ORDER BY id",
    "clip_shots": "SELECT clip_id, shot_id, position FROM clip_shots ORDER BY clip_id, shot_id",
    "clip_videos":
    "SELECT id, clip_id, file_path, sha256, seed, requested_duration, "
    "actual_duration, is_current, built_prompt, input_hash, input_snapshot "
    "FROM clip_videos ORDER BY id",
    "shot_assets": "SELECT shot_id, asset_id FROM shot_assets ORDER BY shot_id, asset_id",
}


def migration_database_url(raw_url: str, database: str) -> str:
    parsed = urlsplit(raw_url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment)
    )


async def migration_create_database(admin_url: str, database: str) -> None:
    connection = await asyncpg.connect(admin_url)
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def migration_drop_database(admin_url: str, database: str) -> None:
    connection = await asyncpg.connect(admin_url)
    try:
        await connection.execute(f'DROP DATABASE "{database}"')
    finally:
        await connection.close()


def migration_alembic(
    database_url: str,
    command: str,
    revision: str,
    data_dir: Path,
) -> ChildResult:
    child_env = os.environ.copy()
    child_env.update(
        {
            "DATABASE_URL": database_url,
            "DATA_DIR": str(data_dir),
            "PYTHONUTF8": "1",
        }
    )
    return run_child(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=BACKEND,
        env=child_env,
        timeout=30.0,
    )


async def migration_seed(
    database_url: str,
    rows: Sequence[tuple[int, str, str]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, list[dict[str, object]]],
]:
    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        style_id = await connection.fetchval(
            "INSERT INTO styles (name, prompt_fragment) VALUES ($1, $2) RETURNING id",
            f"c012-migration-style-{uuid4().hex}",
            "style",
        )
        project_ids: dict[int, int] = {}
        for project_number, _asset_type, _name in rows:
            if project_number not in project_ids:
                project_ids[project_number] = await connection.fetchval(
                    "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
                    f"c012-migration-project-{project_number}-{uuid4().hex}",
                    style_id,
                )
        for project_number, asset_type, name in rows:
            await connection.execute(
                "INSERT INTO assets "
                "(project_id, type, name, description, source, revision) "
                "VALUES ($1, $2, $3, $4, 'manual', 1)",
                project_ids[project_number],
                asset_type,
                name,
                f"description-{name}",
            )
        assets = [
            dict(row)
            for row in await connection.fetch(
                "SELECT id, project_id, type, name, description, source, revision "
                "FROM assets ORDER BY id"
            )
        ]
        first_asset = await connection.fetchrow(
            "SELECT id, project_id, type, name FROM assets ORDER BY id LIMIT 1"
        )
        if first_asset is None:
            raise AcceptanceFailure("migration fixture did not create an asset")
        episode_id = await connection.fetchval(
            "INSERT INTO episodes "
            "(project_id, seq, title, script_text, script_revision) "
            "VALUES ($1, 1, 'Migration episode', 'Migration script', 1) RETURNING id",
            first_asset["project_id"],
        )
        shot_id = await connection.fetchval(
            "INSERT INTO shots "
            "(episode_id, order_index, duration_est, shot_type, camera, "
            "description, dialogue, status, revision) "
            "VALUES ($1, 1, 5.0, 'wide', 'fixed', 'Migration shot', '', 'normal', 1) "
            "RETURNING id",
            episode_id,
        )
        clip_id = await connection.fetchval(
            "INSERT INTO clips "
            "(episode_id, requested_duration, generation_state, freshness, revision) "
            "VALUES ($1, 5, 'ready', 'fresh', 1) RETURNING id",
            episode_id,
        )
        await connection.execute(
            "INSERT INTO asset_images "
            "(asset_id, file_path, sha256, seed, source, is_current) "
            "VALUES ($1, 'assets/migration.png', 'migration-image', 1, 'uploaded', true)",
            first_asset["id"],
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_id,
            first_asset["id"],
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            clip_id,
            shot_id,
        )
        await connection.execute(
            "INSERT INTO clip_ref_slots "
            "(clip_id, slot_no, asset_id, asset_name_snapshot, asset_type_snapshot, enabled) "
            "VALUES ($1, 1, $2, $3, $4, true)",
            clip_id,
            first_asset["id"],
            first_asset["name"],
            first_asset["type"],
        )
        await connection.execute(
            "INSERT INTO clip_videos "
            "(clip_id, file_path, sha256, seed, requested_duration, actual_duration, is_current) "
            "VALUES ($1, 'clips/migration.mp4', 'migration-video', 1, 5, 5.0, true)",
            clip_id,
        )
        templates = [
            dict(row)
            for row in await connection.fetch(
                "SELECT key, content FROM prompt_templates ORDER BY key"
            )
        ]
        dependencies = {
            table: [dict(row) for row in await connection.fetch(query)]
            for table, query in MIGRATION_DEPENDENCY_QUERIES.items()
        }
        return assets, templates, dependencies
    finally:
        await connection.close()


async def migration_read_state(database_url: str) -> dict[str, object]:
    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        return {
            "version": await connection.fetchval(
                "SELECT version_num FROM alembic_version"
            ),
            "constraint": bool(
                await connection.fetchval(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conrelid = 'assets'::regclass "
                    "AND conname = 'uq_assets_project_name'"
                    ")"
                )
            ),
            "assets": [
                dict(row)
                for row in await connection.fetch(
                    "SELECT id, project_id, type, name, description, source, revision "
                    "FROM assets ORDER BY id"
                )
            ],
            "templates": [
                dict(row)
                for row in await connection.fetch(
                    "SELECT key, content FROM prompt_templates ORDER BY key"
                )
            ],
            "dependencies": {
                table: [dict(row) for row in await connection.fetch(query)]
                for table, query in MIGRATION_DEPENDENCY_QUERIES.items()
            },
        }
    finally:
        await connection.close()


def require_migration_state(
    actual: dict[str, object],
    *,
    version: str,
    constraint: bool,
    assets: list[dict[str, object]],
    templates: list[dict[str, object]],
    dependencies: dict[str, list[dict[str, object]]],
    label: str,
) -> None:
    expected = {
        "version": version,
        "constraint": constraint,
        "assets": assets,
        "templates": templates,
        "dependencies": dependencies,
    }
    if actual != expected:
        raise AcceptanceFailure(
            f"{label} state mismatch: actual={actual!r}; expected={expected!r}"
        )


async def migration_duplicate_rejected(
    database_url: str,
    project_id: int,
) -> None:
    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        try:
            await connection.execute(
                "INSERT INTO assets "
                "(project_id, type, name, description, source, revision) "
                "VALUES ($1, 'prop', 'Hero', 'duplicate', 'manual', 1)",
                project_id,
            )
        except asyncpg.exceptions.UniqueViolationError:
            return
        raise AcceptanceFailure(
            "project-scoped asset name constraint accepted a duplicate"
        )
    finally:
        await connection.close()


async def command_migration(
    _arguments: argparse.Namespace,
    evidence: RunEvidence,
) -> None:
    raw_url, data_dir, url_identity = explicit_runtime()
    admin_url = migration_database_url(raw_url, "postgres").replace(
        "+asyncpg", "", 1
    )
    evidence.add(
        "migration_runtime",
        database_url=url_identity,
        admin_database="postgres",
        data_dir=str(data_dir),
    )

    async def run_step(
        database: str,
        database_url: str,
        command: str,
        revision: str,
        label: str,
    ) -> ChildResult:
        result = migration_alembic(database_url, command, revision, data_dir)
        evidence.add(
            "alembic_step",
            database=database,
            label=label,
            revision=revision,
            **child_observation(result),
        )
        return result

    empty_database = f"c012_migration_empty_{uuid4().hex}"
    empty_url = migration_database_url(raw_url, empty_database)
    await migration_create_database(admin_url, empty_database)
    try:
        result = await run_step(
            empty_database,
            empty_url,
            "upgrade",
            MIGRATION_NEW_HEAD,
            "empty-upgrade",
        )
        assert_child_success(result, "empty migration upgrade")
        empty_state = await migration_read_state(empty_url)
        require_migration_state(
            empty_state,
            version=MIGRATION_NEW_HEAD,
            constraint=True,
            assets=[],
            templates=empty_state["templates"],  # type: ignore[arg-type]
            dependencies=empty_state["dependencies"],  # type: ignore[arg-type]
            label="empty database",
        )
        evidence.add("migration_case", case="empty", state=empty_state)
    finally:
        await migration_drop_database(admin_url, empty_database)
        evidence.add("migration_cleanup", database=empty_database, dropped=True)

    legal_database = f"c012_migration_legal_{uuid4().hex}"
    legal_url = migration_database_url(raw_url, legal_database)
    await migration_create_database(admin_url, legal_database)
    try:
        result = await run_step(
            legal_database,
            legal_url,
            "upgrade",
            MIGRATION_PREVIOUS_HEAD,
            "legal-previous-head-upgrade",
        )
        assert_child_success(result, "legal previous-head upgrade")
        before_assets, before_templates, before_dependencies = await migration_seed(
            legal_url,
            [(1, "character", "Hero"), (1, "scene", "Room"), (2, "character", "Hero")],
        )
        project_one_id = int(before_assets[0]["project_id"])
        result = await run_step(
            legal_database,
            legal_url,
            "upgrade",
            MIGRATION_NEW_HEAD,
            "legal-upgrade",
        )
        assert_child_success(result, "legal migration upgrade")
        require_migration_state(
            await migration_read_state(legal_url),
            version=MIGRATION_NEW_HEAD,
            constraint=True,
            assets=before_assets,
            templates=before_templates,
            dependencies=before_dependencies,
            label="legal upgrade",
        )
        await migration_duplicate_rejected(legal_url, project_one_id)
        evidence.add("migration_constraint", case="legal", duplicate_rejected=True)

        result = await run_step(
            legal_database,
            legal_url,
            "downgrade",
            MIGRATION_PREVIOUS_HEAD,
            "legal-downgrade",
        )
        assert_child_success(result, "legal migration downgrade")
        require_migration_state(
            await migration_read_state(legal_url),
            version=MIGRATION_PREVIOUS_HEAD,
            constraint=False,
            assets=before_assets,
            templates=before_templates,
            dependencies=before_dependencies,
            label="legal downgrade",
        )
        result = await run_step(
            legal_database,
            legal_url,
            "upgrade",
            MIGRATION_NEW_HEAD,
            "legal-re-upgrade",
        )
        assert_child_success(result, "legal migration re-upgrade")
        require_migration_state(
            await migration_read_state(legal_url),
            version=MIGRATION_NEW_HEAD,
            constraint=True,
            assets=before_assets,
            templates=before_templates,
            dependencies=before_dependencies,
            label="legal re-upgrade",
        )
        evidence.add("migration_case", case="legal", assets=before_assets)
    finally:
        await migration_drop_database(admin_url, legal_database)
        evidence.add("migration_cleanup", database=legal_database, dropped=True)

    invalid_cases: dict[str, list[tuple[int, str, str]]] = {
        "exact-collision": [(1, "character", "Hero"), (1, "scene", "Hero")],
        "normalized-collision": [(1, "character", "Hero"), (1, "scene", "  Hero  ")],
        "blank-name": [(1, "character", "   ")],
        "non-normalized": [(1, "character", " Hero ")],
    }
    for case, rows in invalid_cases.items():
        database = f"c012_migration_{case}_{uuid4().hex}"
        database_url = migration_database_url(raw_url, database)
        await migration_create_database(admin_url, database)
        try:
            result = await run_step(
                database,
                database_url,
                "upgrade",
                MIGRATION_PREVIOUS_HEAD,
                f"{case}-previous-head-upgrade",
            )
            assert_child_success(result, f"{case} previous-head upgrade")
            before_assets, before_templates, before_dependencies = await migration_seed(
                database_url, rows
            )
            result = await run_step(
                database,
                database_url,
                "upgrade",
                MIGRATION_NEW_HEAD,
                f"{case}-precheck",
            )
            output = result.text_stdout() + result.text_stderr()
            if result.timed_out or result.returncode == 0:
                raise AcceptanceFailure(
                    f"{case} precheck did not fail: rc={result.returncode}, "
                    f"timeout={result.timed_out}"
                )
            for marker in (
                "assets name precheck failed",
                "project_id",
                "asset_id",
                "original_name",
                "normalized_name",
            ):
                if marker not in output:
                    raise AcceptanceFailure(
                        f"{case} precheck output omitted {marker!r}: {output}"
                    )
            require_migration_state(
                await migration_read_state(database_url),
                version=MIGRATION_PREVIOUS_HEAD,
                constraint=False,
                assets=before_assets,
                templates=before_templates,
                dependencies=before_dependencies,
                label=f"{case} failed migration",
            )
            evidence.add(
                "migration_case",
                case=case,
                failure_returncode=result.returncode,
                state=await migration_read_state(database_url),
            )
        finally:
            await migration_drop_database(admin_url, database)
            evidence.add("migration_cleanup", database=database, dropped=True)


async def command_names(
    _arguments: argparse.Namespace,
    evidence: RunEvidence,
) -> None:
    raw_url, data_dir, url_identity = explicit_runtime()
    database_identity = await read_database_identity(raw_url)
    evidence.add(
        "runtime_identity",
        database_url=url_identity,
        database=database_identity,
        data_dir=str(data_dir),
    )
    if database_identity["current_database"] != url_identity["database_from_url"]:
        raise AcceptanceFailure(
            "database identity does not match explicit DATABASE_URL database"
        )

    child_env = os.environ.copy()
    child_env.update(
        {
            "DATABASE_URL": raw_url,
            "DATA_DIR": str(data_dir),
            "PYTHONUTF8": "1",
        }
    )
    result = run_child(
        [
            sys.executable,
            "-m",
            "pytest",
            "-s",
            "-q",
            "tests/task_system/test_c012_asset_name_races.py",
        ],
        cwd=BACKEND,
        env=child_env,
        timeout=120.0,
    )
    evidence.add("names_probe", **child_observation(result))
    assert_child_success(result, "C012 names probe")
    evidence.add("post_probe_connection", database=await read_database_identity(raw_url))


async def ws_seed_task(raw_url: str) -> int:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    try:
        target_id = await connection.fetchval(
            "SELECT COALESCE(MAX(target_id), 0) + 1 FROM tasks"
        )
        row = await connection.fetchrow(
            "INSERT INTO tasks "
            "(type, target_id, payload, status, progress) "
            "VALUES ('gen_assets', $1, $2::jsonb, 'running', $3) "
            "RETURNING id",
            int(target_id),
            json.dumps(
                {
                    "input_snapshot": {},
                    "input_hash": None,
                    "source_revisions": {},
                }
            ),
            0.5,
        )
    finally:
        await connection.close()
    if row is None:
        raise AcceptanceFailure("WebSocket task fixture insert returned no id")
    return int(row["id"])


async def ws_read_task(raw_url: str, task_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    try:
        row = await connection.fetchrow(
            "SELECT status, progress, cancel_requested_at, error_msg "
            "FROM tasks WHERE id = $1",
            task_id,
        )
    finally:
        await connection.close()
    if row is None:
        raise AcceptanceFailure(f"WebSocket task {task_id} disappeared before probe")
    return {
        "status": row["status"],
        "progress": float(row["progress"]),
        "cancel_requested": row["cancel_requested_at"] is not None,
        "error_msg": row["error_msg"],
    }


async def ws_delete_task(raw_url: str, task_id: int) -> str:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    try:
        return str(
            await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
        )
    finally:
        await connection.close()


async def command_ws(
    _arguments: argparse.Namespace,
    evidence: RunEvidence,
) -> None:
    raw_url, data_dir, url_identity = explicit_runtime()
    database_identity = await read_database_identity(raw_url)
    evidence.add(
        "runtime_identity",
        database_url=url_identity,
        database=database_identity,
        data_dir=str(data_dir),
    )
    if database_identity["current_database"] != url_identity["database_from_url"]:
        raise AcceptanceFailure(
            "database identity does not match explicit DATABASE_URL database"
        )

    with tempfile.TemporaryDirectory(
        prefix="c012-ws-", dir=str(data_dir)
    ) as runtime_name:
        runtime_dir = Path(runtime_name)
        with ControlledHTTPStub() as dependency_stub:
            app_port = free_tcp_port()
            child_env = os.environ.copy()
            child_env.update(
                {
                    "DATABASE_URL": raw_url,
                    "PYTHONUTF8": "1",
                    "DATA_DIR": str(runtime_dir),
                    "VLLM_BASE_URL": dependency_stub.base_url,
                    "COMFY_BASE_URL": dependency_stub.base_url,
                }
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(app_port),
                    "--log-level",
                    "warning",
                ],
                cwd=BACKEND,
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                ),
            )
            task_id: int | None = None
            stopped_result: ChildResult | None = None
            try:
                health = await wait_for_http(
                    f"http://127.0.0.1:{app_port}/api/system/health"
                )
                if health.status_code != 200:
                    raise AcceptanceFailure(
                        f"production health returned {health.status_code}"
                    )
                task_id = await ws_seed_task(raw_url)
                ws_uri = f"ws://127.0.0.1:{app_port}/ws/tasks"
                cancel_url = f"http://127.0.0.1:{app_port}/api/tasks/{task_id}/cancel"
                expected_event = {
                    "task_id": task_id,
                    "type": "gen_assets",
                    "status": "running",
                    "progress": 0.5,
                    "message": "已请求取消",
                }
                async with (
                    websockets.asyncio.client.connect(
                        ws_uri, open_timeout=5, close_timeout=5
                    ) as websocket_a,
                    websockets.asyncio.client.connect(
                        ws_uri, open_timeout=5, close_timeout=5
                    ) as websocket_b,
                ):
                    async with httpx.AsyncClient(
                        timeout=5.0, trust_env=False
                    ) as client:
                        cancel_response = await client.post(cancel_url)
                    if cancel_response.status_code != 200:
                        raise AcceptanceFailure(
                            f"production cancel returned {cancel_response.status_code}: "
                            f"{cancel_response.text}"
                        )
                    cancel_body = cancel_response.json()
                    if not isinstance(cancel_body, dict):
                        raise AcceptanceFailure("production cancel body was not an object")
                    if (
                        cancel_body.get("status") != "running"
                        or cancel_body.get("cancel_requested_at") is None
                    ):
                        raise AcceptanceFailure(
                            f"cancel response did not preserve running state: {cancel_body}"
                        )
                    received_events: list[object] = []
                    for websocket in (websocket_a, websocket_b):
                        raw_event = await asyncio.wait_for(websocket.recv(), timeout=5)
                        try:
                            received_events.append(json.loads(raw_event))
                        except ValueError as exc:
                            raise AcceptanceFailure(
                                f"production WebSocket returned non-JSON event: {raw_event!r}"
                            ) from exc
                    if received_events != [expected_event, expected_event]:
                        raise AcceptanceFailure(
                            f"production WebSocket event mismatch: {received_events!r}"
                        )
                task_state = await ws_read_task(raw_url, task_id)
                if task_state != {
                    "status": "running",
                    "progress": 0.5,
                    "cancel_requested": True,
                    "error_msg": None,
                }:
                    raise AcceptanceFailure(
                        f"task state changed after WebSocket probe: {task_state!r}"
                    )
                evidence.add(
                    "network_ws",
                    uri=ws_uri,
                    connections_before=0,
                    connections_active=2,
                    connections_after=0,
                    cancel_response=cancel_body,
                    events=received_events,
                    task_state=task_state,
                    process_alive=process.poll() is None,
                )
                if process.poll() is not None:
                    raise AcceptanceFailure(
                        f"production process exited during WebSocket probe: {process.returncode}"
                    )
            finally:
                stopped_result = stop_process(process)
                evidence.add(
                    "production_process_shutdown",
                    **child_observation(stopped_result),
                    process_exited=process.poll() is not None,
                )
                if task_id is not None:
                    deleted = await ws_delete_task(raw_url, task_id)
                    evidence.add(
                        "task_fixture_cleanup",
                        task_id=task_id,
                        delete_result=deleted,
                    )
            if stopped_result is None:
                raise AcceptanceFailure("owned production process shutdown was not observed")
            if stopped_result.timed_out:
                raise AcceptanceFailure(
                    "owned production process required forced termination"
                )
            if process.poll() is None:
                raise AcceptanceFailure("owned production process did not stop")
    if runtime_dir.exists():
        raise AcceptanceFailure("WebSocket runtime directory was not released")
    evidence.add(
        "owned_resource_cleanup",
        runtime_directory_exists=runtime_dir.exists(),
        dependency_stub_stopped=True,
        production_process_stopped=True,
    )


async def command_selfcheck(
    arguments: argparse.Namespace, evidence: RunEvidence
) -> None:
    raw_url, data_dir, url_identity = explicit_runtime()
    database_identity = await read_database_identity(raw_url)
    evidence.add(
        "runtime_identity",
        database_url=url_identity,
        database=database_identity,
        data_dir=str(data_dir),
    )
    if database_identity["current_database"] != url_identity["database_from_url"]:
        raise AcceptanceFailure(
            "database identity does not match explicit DATABASE_URL database"
        )

    marker = data_dir / "c012-selfcheck-successor.marker"
    marker.unlink(missing_ok=True)
    stderr_probe = run_child(
        [
            sys.executable,
            "-c",
            "import sys; print('stdout-ok'); print('stderr-ok', file=sys.stderr)",
        ]
    )
    evidence.add("stderr_plus_zero", **child_observation(stderr_probe))
    assert_child_success(stderr_probe, "stderr+exit0 probe")
    if stderr_probe.text_stderr().replace("\r\n", "\n") != "stderr-ok\n":
        raise AcceptanceFailure("stderr+exit0 probe did not preserve stderr")

    failure_probe = run_child(
        [
            sys.executable,
            "-c",
            "import sys; print('controlled-startup-failure', file=sys.stderr); raise SystemExit(23)",
        ]
    )
    evidence.add(
        "startup_failure_without_successor",
        **child_observation(failure_probe),
        successor_started=marker.exists(),
    )
    if failure_probe.timed_out or failure_probe.returncode == 0:
        raise AcceptanceFailure(
            "controlled startup-failure probe was not a non-zero exit"
        )
    if marker.exists():
        raise AcceptanceFailure("startup-failure probe left a successor marker")

    if arguments.fail_case == "child":
        raise AcceptanceFailure("requested --fail-case child")
    if arguments.fail_case == "startup":
        raise AcceptanceFailure("requested --fail-case startup")

    with tempfile.TemporaryDirectory(
        prefix="c012-selfcheck-", dir=str(data_dir)
    ) as runtime_name:
        runtime_dir = Path(runtime_name)
        with ControlledHTTPStub() as dependency_stub:
            app_port = free_tcp_port()
            child_env = os.environ.copy()
            child_env.update(
                {
                    "PYTHONUTF8": "1",
                    "DATA_DIR": str(runtime_dir),
                    "VLLM_BASE_URL": dependency_stub.base_url,
                    "COMFY_BASE_URL": dependency_stub.base_url,
                }
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(app_port),
                    "--log-level",
                    "warning",
                ],
                cwd=BACKEND,
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                ),
            )
            stopped = False
            try:
                docs = await wait_for_http(
                    f"http://127.0.0.1:{app_port}/docs", expect_json=False
                )
                health = await wait_for_http(
                    f"http://127.0.0.1:{app_port}/api/system/health"
                )
                tasks = await wait_for_http(
                    f"http://127.0.0.1:{app_port}/api/tasks"
                )
                if docs.status_code != 200:
                    raise AcceptanceFailure(
                        f"production /docs returned {docs.status_code}"
                    )
                if health.status_code != 200:
                    raise AcceptanceFailure(
                        f"production /api/system/health returned {health.status_code}"
                    )
                if tasks.status_code != 200 or not isinstance(tasks.body, list):
                    raise AcceptanceFailure(
                        "production /api/tasks did not return a JSON list"
                    )
                if not isinstance(health.body, dict):
                    raise AcceptanceFailure("health response was not a JSON object")
                bindings = health.body.get("workflow_bindings")
                if not isinstance(bindings, dict) or bindings.get("status") != "valid":
                    raise AcceptanceFailure(
                        "production health did not expose valid workflow bindings"
                    )
                evidence.add(
                    "production_http",
                    port=app_port,
                    docs_status=docs.status_code,
                    health_status=health.status_code,
                    tasks_status=tasks.status_code,
                    health=health.body,
                )
                ws_uri = f"ws://127.0.0.1:{app_port}/ws/tasks"
                async with websockets.asyncio.client.connect(
                    ws_uri, open_timeout=5, close_timeout=5
                ) as websocket:
                    await websocket.close(code=1000)
                evidence.add(
                    "production_websocket",
                    uri=ws_uri,
                    connected=True,
                    closed_code=1000,
                )
            finally:
                stopped_result = stop_process(process)
                stopped = True
                evidence.add(
                    "production_process_shutdown",
                    **child_observation(stopped_result),
                    process_exited=process.poll() is not None,
                )
            if not stopped or process.poll() is None:
                raise AcceptanceFailure("owned production process did not stop")
            if stopped_result.timed_out:
                raise AcceptanceFailure(
                    "owned production process required forced termination"
                )
            expected_shutdown_codes = {0, -15, 15, 1, 3221225786}
            if (
                not stopped_result.termination_requested
                or stopped_result.returncode not in expected_shutdown_codes
            ):
                raise AcceptanceFailure(
                    f"owned production process exited unexpectedly: {stopped_result.returncode}"
                )

    evidence.add(
        "owned_resource_cleanup",
        successor_marker_exists=marker.exists(),
        runtime_directory_exists=runtime_dir.exists(),
        production_process_stopped=True,
        dependency_stub_stopped=True,
    )
    if marker.exists() or runtime_dir.exists():
        raise AcceptanceFailure("selfcheck owned temporary resources were not released")


def binding_report() -> tuple[dict[str, object], dict[str, str]]:
    from app.integrations.workflow_binding import (
        WorkflowBindingError,
        load_binding_snapshot,
        load_minimax_binding_snapshot,
    )

    try:
        zimage = load_binding_snapshot()
        minimaxh3 = load_minimax_binding_snapshot()
    except WorkflowBindingError as exc:
        raise AcceptanceFailure(f"workflow binding validation failed: {exc}") from exc

    node_ids = {
        "zimage_prompt": zimage.prompt_path.split(".", 1)[0],
        "zimage_seed": zimage.seed_path.split(".", 1)[0],
        "zimage_output": zimage.output_node,
        "minimaxh3_prompt": minimaxh3.prompt_path.split(".", 1)[0],
        "minimaxh3_seed": minimaxh3.seed_path.split(".", 1)[0],
        "minimaxh3_duration": minimaxh3.duration_path.split(".", 1)[0],
        "minimaxh3_output": minimaxh3.output_node,
        "minimaxh3_lora": "310",
    }

    def node_class(snapshot: object, node_id: str, label: str) -> str:
        definition = getattr(snapshot, "definition", None)
        if not isinstance(definition, Mapping):
            raise AcceptanceFailure(f"{label} workflow definition is not an object")
        node = definition.get(node_id)
        if not isinstance(node, Mapping) or not isinstance(
            node.get("class_type"), str
        ):
            raise AcceptanceFailure(f"{label} workflow node {node_id} is invalid")
        return node["class_type"]

    classes = {
        label: node_class(
            zimage if label.startswith("zimage") else minimaxh3,
            node_id,
            label,
        )
        for label, node_id in node_ids.items()
    }

    def workflow_metadata(snapshot: object, label: str) -> dict[str, object]:
        return {
            "name": getattr(snapshot, "name"),
            "workflow_path": str(getattr(snapshot, "workflow_path")),
            "workflow_hash": getattr(snapshot, "workflow_hash"),
            "prompt_path": getattr(snapshot, "prompt_path"),
            "seed_path": getattr(snapshot, "seed_path"),
            "duration_path": getattr(snapshot, "duration_path", None),
            "output_node": getattr(snapshot, "output_node"),
            "reference_count": len(getattr(snapshot, "ref_image_paths", ())),
            "node_classes": {
                key: value
                for key, value in classes.items()
                if key.startswith(label)
            },
        }

    definition = minimaxh3.definition
    lora_node = definition.get("310") if isinstance(definition, Mapping) else None
    if not isinstance(lora_node, Mapping):
        raise AcceptanceFailure("MiniMax workflow node 310 is missing")
    lora_inputs = lora_node.get("inputs")
    lora_name = (
        lora_inputs.get("lora_name")
        if isinstance(lora_inputs, Mapping)
        else None
    )
    if not isinstance(lora_name, str) or not lora_name:
        raise AcceptanceFailure("MiniMax workflow node 310 LoRA name is invalid")

    return (
        {
            "zimage": workflow_metadata(zimage, "zimage"),
            "minimaxh3": workflow_metadata(minimaxh3, "minimaxh3"),
            "required_node_ids": node_ids,
            "required_node_classes": classes,
            "minimaxh3_lora": {
                "node_id": "310",
                "class_type": classes["minimaxh3_lora"],
                "configured_name": lora_name,
            },
        },
        {"minimaxh3_lora_class": classes["minimaxh3_lora"], "minimaxh3_lora_name": lora_name},
    )


def validate_object_info(
    object_info: object, *, binding_nodes: Mapping[str, object], lora: Mapping[str, str]
) -> dict[str, object]:
    info = require_mapping(object_info, "Comfy /object_info")
    missing_classes = sorted(
        {
            value
            for value in binding_nodes.values()
            if isinstance(value, str) and value not in info
        }
    )
    if missing_classes:
        raise AcceptanceFailure(
            f"Comfy /object_info is missing workflow node classes: {missing_classes}"
        )
    lora_class = lora["minimaxh3_lora_class"]
    class_info = require_mapping(info[lora_class], f"Comfy object_info[{lora_class}]")
    input_info = require_mapping(
        class_info.get("input"), f"Comfy object_info[{lora_class}].input"
    )
    required = require_mapping(
        input_info.get("required"),
        f"Comfy object_info[{lora_class}].input.required",
    )
    lora_spec = required.get("lora_name")
    if not isinstance(lora_spec, list) or not lora_spec:
        raise AcceptanceFailure(
            f"Comfy object_info[{lora_class}] has no lora_name options"
        )
    allowed = lora_spec[0]
    if not isinstance(allowed, list) or lora["minimaxh3_lora_name"] not in allowed:
        raise AcceptanceFailure(
            "configured MiniMax LoRA is not registered by Comfy /object_info: "
            f"{lora['minimaxh3_lora_name']}"
        )
    return {
        "class_count": len(info),
        "workflow_classes_present": sorted(set(binding_nodes.values())),
        "lora_class": lora_class,
        "lora_name": lora["minimaxh3_lora_name"],
        "lora_registered": True,
    }


def require_model_id(value: object, expected: str) -> list[str]:
    body = require_mapping(value, "vLLM /v1/models")
    entries = body.get("data")
    if not isinstance(entries, list):
        raise AcceptanceFailure("vLLM /v1/models data was not a list")
    model_ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("id"), str):
            raise AcceptanceFailure("vLLM /v1/models contained an invalid model entry")
        model_ids.append(entry["id"])
    if expected not in model_ids:
        raise AcceptanceFailure(
            f"configured vLLM model is not registered: expected={expected!r} "
            f"actual={model_ids!r}"
        )
    return model_ids


def require_queue_empty(value: object, label: str) -> dict[str, int]:
    body = require_mapping(value, label)
    running = body.get("queue_running")
    pending = body.get("queue_pending")
    if not isinstance(running, list) or not isinstance(pending, list):
        raise AcceptanceFailure(f"{label} did not contain queue_running/queue_pending lists")
    counts = {"queue_running": len(running), "queue_pending": len(pending)}
    if any(counts.values()):
        raise AcceptanceFailure(f"{label} contains tasks owned by another run: {counts}")
    return counts


def require_sleeping(value: object, label: str) -> bool:
    body = require_mapping(value, label)
    sleeping = body.get("is_sleeping")
    if not isinstance(sleeping, bool):
        raise AcceptanceFailure(f"{label} did not return a boolean is_sleeping")
    return sleeping


async def command_verify_inputs(
    _arguments: argparse.Namespace, evidence: RunEvidence
) -> None:
    expected, source = read_frozen_m6_script()
    actual = read_utf8_file(M6_SCRIPT_PATH, "M6 script")
    settings = runtime_settings()
    evidence.add(
        "frozen_m6_script",
        path=str(M6_SCRIPT_PATH),
        source=source,
        actual_characters=len(actual),
        actual_utf8_bytes=len(actual.encode("utf-8")),
        actual_ends_with_lf=actual.endswith("\n"),
        actual_ends_with_crlf=actual.endswith("\r\n"),
        exact_match=actual == expected,
        script_char_limit=settings.SCRIPT_CHAR_LIMIT,
    )
    evidence.add(
        "m6_real_input_plan",
        three_run_append_sentence=M6_APPEND_SENTENCE,
        clip_targets=list(M6_CLIP_TARGETS),
    )
    if actual != expected:
        raise AcceptanceFailure(
            "backend/deployment/m6-script.txt does not exactly match C012 spec §6.1"
        )
    if len(actual) > settings.SCRIPT_CHAR_LIMIT:
        raise AcceptanceFailure(
            "M6 script exceeds the configured SCRIPT_CHAR_LIMIT: "
            f"characters={len(actual)} limit={settings.SCRIPT_CHAR_LIMIT}"
        )


async def command_preflight(
    _arguments: argparse.Namespace, evidence: RunEvidence
) -> None:
    raw_url, data_dir, identity = explicit_runtime()
    settings = runtime_settings()
    database_identity = await read_database_identity(raw_url)
    evidence.add(
        "runtime_identity",
        database_url=identity,
        database=database_identity,
        data_dir=str(data_dir),
    )
    if database_identity["current_database"] != identity["database_from_url"]:
        raise AcceptanceFailure(
            "database identity does not match explicit DATABASE_URL database"
        )

    vllm_url = safe_service_url(str(settings.VLLM_BASE_URL), "VLLM_BASE_URL")
    comfy_url = safe_service_url(str(settings.COMFY_BASE_URL), "COMFY_BASE_URL")
    evidence.add(
        "runtime_configuration",
        vllm_base_url=vllm_url,
        vllm_model=settings.VLLM_MODEL,
        vllm_temperature=settings.VLLM_TEMPERATURE,
        comfy_base_url=comfy_url,
        script_char_limit=settings.SCRIPT_CHAR_LIMIT,
        data_dir=str(data_dir),
    )

    binding_metadata, lora = binding_report()
    evidence.add("workflow_bindings", **binding_metadata)

    ports = listener_ports([vllm_url, comfy_url])
    evidence.add("listener_ownership_before", **observe_windows_listeners(ports))

    vllm_health = await real_http_request(vllm_url, "GET", "/health")
    require_http_success(vllm_health, method="GET", url=f"{vllm_url}/health")
    vllm_models = await real_http_request(vllm_url, "GET", "/v1/models")
    models = require_http_success(
        vllm_models, method="GET", url=f"{vllm_url}/v1/models"
    )
    model_ids = require_model_id(models, settings.VLLM_MODEL)
    evidence.add(
        "vllm_health_and_model",
        health_status=vllm_health.status_code,
        health_body=vllm_health.body,
        models_status=vllm_models.status_code,
        model_ids=model_ids,
        configured_model=settings.VLLM_MODEL,
    )

    comfy_health = await real_http_request(comfy_url, "GET", "/system_stats")
    require_http_success(
        comfy_health, method="GET", url=f"{comfy_url}/system_stats"
    )
    object_info_response = await real_http_request(comfy_url, "GET", "/object_info")
    object_info = require_http_success(
        object_info_response, method="GET", url=f"{comfy_url}/object_info"
    )
    binding_nodes = binding_metadata["required_node_classes"]
    object_info_summary = validate_object_info(
        object_info,
        binding_nodes=binding_nodes,
        lora=lora,
    )
    queue_response = await real_http_request(comfy_url, "GET", "/queue")
    queue = require_http_success(
        queue_response, method="GET", url=f"{comfy_url}/queue"
    )
    queue_counts_before = require_queue_empty(queue, "Comfy /queue before preflight")
    evidence.add(
        "comfy_health_binding_queue",
        health_status=comfy_health.status_code,
        health_body=comfy_health.body,
        object_info_status=object_info_response.status_code,
        object_info_body=object_info,
        object_info=object_info_summary,
        queue_status=queue_response.status_code,
        queue_body=queue,
        queue_counts=queue_counts_before,
    )

    initial_sleep_response = await real_http_request(vllm_url, "GET", "/is_sleeping")
    initial_sleeping = require_sleeping(
        require_http_success(
            initial_sleep_response,
            method="GET",
            url=f"{vllm_url}/is_sleeping",
        ),
        "vLLM /is_sleeping initial",
    )
    sleep_response = await real_http_request(
        vllm_url, "POST", "/sleep", params={"level": 1}, timeout=120.0
    )
    require_http_success(sleep_response, method="POST", url=f"{vllm_url}/sleep?level=1")
    after_sleep_response = await real_http_request(vllm_url, "GET", "/is_sleeping")
    after_sleeping = require_sleeping(
        require_http_success(
            after_sleep_response,
            method="GET",
            url=f"{vllm_url}/is_sleeping",
        ),
        "vLLM /is_sleeping after level-1 sleep",
    )
    wake_response = await real_http_request(
        vllm_url, "POST", "/wake_up", timeout=120.0
    )
    require_http_success(wake_response, method="POST", url=f"{vllm_url}/wake_up")
    after_wake_response = await real_http_request(vllm_url, "GET", "/is_sleeping")
    after_waking = require_sleeping(
        require_http_success(
            after_wake_response,
            method="GET",
            url=f"{vllm_url}/is_sleeping",
        ),
        "vLLM /is_sleeping after wake_up",
    )
    final_sleep_response = await real_http_request(
        vllm_url, "POST", "/sleep", params={"level": 1}, timeout=120.0
    )
    require_http_success(
        final_sleep_response, method="POST", url=f"{vllm_url}/sleep?level=1"
    )
    final_sleep_response = await real_http_request(vllm_url, "GET", "/is_sleeping")
    final_sleeping = require_sleeping(
        require_http_success(
            final_sleep_response,
            method="GET",
            url=f"{vllm_url}/is_sleeping",
        ),
        "vLLM /is_sleeping final",
    )
    evidence.add(
        "vllm_sleep_wake",
        initial_sleeping=initial_sleeping,
        after_level1_sleep=after_sleeping,
        after_wake=after_waking,
        final_sleeping=final_sleeping,
        operations=[
            "GET /is_sleeping",
            "POST /sleep?level=1",
            "GET /is_sleeping",
            "POST /wake_up",
            "GET /is_sleeping",
            "POST /sleep?level=1",
            "GET /is_sleeping",
        ],
    )
    if not after_sleeping or after_waking or not final_sleeping:
        raise AcceptanceFailure(
            "vLLM sleep/wake state contract failed: "
            f"initial={initial_sleeping} after_sleep={after_sleeping} "
            f"after_wake={after_waking} final={final_sleeping}"
        )

    final_queue_response = await real_http_request(comfy_url, "GET", "/queue")
    final_queue = require_http_success(
        final_queue_response, method="GET", url=f"{comfy_url}/queue"
    )
    final_queue_counts = require_queue_empty(final_queue, "Comfy /queue after preflight")
    evidence.add(
        "preflight_final_state",
        queue_counts=final_queue_counts,
        queue_body=final_queue,
        vllm_sleeping=final_sleeping,
        listener_ownership_after=observe_windows_listeners(ports),
        owned_processes_started=[],
        owned_processes_stopped=[],
    )


async def command_observe(
    _arguments: argparse.Namespace, evidence: RunEvidence
) -> None:
    raw_url, data_dir, identity = explicit_runtime()
    settings = runtime_settings()
    database_identity = await read_database_identity(raw_url)
    if database_identity["current_database"] != identity["database_from_url"]:
        raise AcceptanceFailure(
            "database identity does not match explicit DATABASE_URL database"
        )
    tasks = await read_database_tasks(raw_url)
    vllm_url = safe_service_url(str(settings.VLLM_BASE_URL), "VLLM_BASE_URL")
    comfy_url = safe_service_url(str(settings.COMFY_BASE_URL), "COMFY_BASE_URL")
    vllm_health = await real_http_request(vllm_url, "GET", "/health")
    vllm_models = await real_http_request(vllm_url, "GET", "/v1/models")
    vllm_sleeping = await real_http_request(vllm_url, "GET", "/is_sleeping")
    comfy_health = await real_http_request(comfy_url, "GET", "/system_stats")
    comfy_queue = await real_http_request(comfy_url, "GET", "/queue")
    for method, base_url, path, result in (
        ("GET", vllm_url, "/health", vllm_health),
        ("GET", vllm_url, "/v1/models", vllm_models),
        ("GET", vllm_url, "/is_sleeping", vllm_sleeping),
        ("GET", comfy_url, "/system_stats", comfy_health),
        ("GET", comfy_url, "/queue", comfy_queue),
    ):
        require_http_success(result, method=method, url=f"{base_url}{path}")
    queue_counts = require_queue_empty(comfy_queue.body, "Comfy /queue observer")
    sleeping = require_sleeping(vllm_sleeping.body, "vLLM /is_sleeping observer")
    evidence.add(
        "observer_contract",
        http_methods=["GET"],
        database_statements=[
            "SELECT current_database(), current_user, inet_server_addr(), inet_server_port()",
            "SELECT id,type,target_id,request_id,status,progress,error_msg,"
            "cancel_requested_at,created_at,started_at,finished_at,payload FROM tasks ORDER BY id",
        ],
        database_mutations=[],
        generation_replay=False,
        task_count=len(tasks),
    )
    evidence.add(
        "runtime_observation",
        database_url=identity,
        database=database_identity,
        data_dir=str(data_dir),
        vllm={
            "base_url": vllm_url,
            "model": settings.VLLM_MODEL,
            "health_status": vllm_health.status_code,
            "health_body": vllm_health.body,
            "models_status": vllm_models.status_code,
            "models_body": vllm_models.body,
            "is_sleeping": sleeping,
        },
        comfy={
            "base_url": comfy_url,
            "health_status": comfy_health.status_code,
            "health_body": comfy_health.body,
            "queue_status": comfy_queue.status_code,
            "queue_counts": queue_counts,
        },
        tasks=tasks,
        listener_ownership=observe_windows_listeners(
            listener_ports([vllm_url, comfy_url])
        ),
    )


async def command_locks(
    arguments: argparse.Namespace, evidence: RunEvidence
) -> None:
    _raw_url, data_dir, identity = explicit_runtime()
    selected = (
        [arguments.case]
        if arguments.case != "all"
        else ["L1", "L2", "L3", "L4", "L5"]
    )
    child_env = os.environ.copy()
    child_env.update({"PYTHONUTF8": "1", "DATA_DIR": str(data_dir)})
    for case in selected:
        result = run_child(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "pytest",
                "-q",
                "tests/task_system/test_c012_lock_order.py",
                "-k",
                case,
            ],
            cwd=BACKEND,
            env=child_env,
            timeout=30.0,
        )
        output = result.text_stdout() + result.text_stderr()
        diagnostic_reproduced = False
        scheduled_case = False
        evidence.add(
            "lock_case",
            case=case,
            database=identity,
            data_dir=str(data_dir),
            **child_observation(result),
            diagnostic_reproduced=diagnostic_reproduced,
            scheduled_case=scheduled_case,
        )
        if result.timed_out:
            raise AcceptanceFailure(f"lock case {case} timed out")
        if result.returncode == 0:
            continue
        if diagnostic_reproduced or scheduled_case:
            continue
        raise AcceptanceFailure(
            f"lock case {case} produced an unexpected result: rc={result.returncode}"
        )


async def cascade_seed_fixture(raw_url: str, data_dir: Path) -> dict[str, object]:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    token = uuid4().hex
    try:
        async with connection.transaction():
            style_id = await connection.fetchval(
                "INSERT INTO styles (name, prompt_fragment) VALUES ($1, $2) RETURNING id",
                f"C012 acceptance style {token}", "controlled style",
            )
            project_id = await connection.fetchval(
                "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
                f"C012 acceptance project {token}", style_id,
            )
            edit_episode_id = await connection.fetchval(
                "INSERT INTO episodes (project_id, seq, title, script_text, script_revision) "
                "VALUES ($1, 1, 'Cascade edit', 'cascade script', 1) RETURNING id",
                project_id,
            )
            generation_episode_id = await connection.fetchval(
                "INSERT INTO episodes (project_id, seq, title, script_text, script_revision) "
                "VALUES ($1, 2, 'Cascade generation', 'generation script', 1) RETURNING id",
                project_id,
            )
            asset_ids: list[int] = []
            for asset_type, name in (("character", "Cascade character"), ("scene", "Cascade scene"), ("character", "Cascade spare")):
                asset_id = await connection.fetchval(
                    "INSERT INTO assets (project_id, type, name, description, source) "
                    "VALUES ($1, $2, $3, 'controlled fixture asset', 'manual') RETURNING id",
                    project_id, asset_type, f"{name} {token}",
                )
                asset_ids.append(int(asset_id))
            edit_shot_ids: list[int] = []
            for order_index, description in ((1, "old edit shot"), (2, "second edit shot")):
                shot_id = await connection.fetchval(
                    "INSERT INTO shots (episode_id, order_index, duration_est, shot_type, camera, description, dialogue, status, revision) "
                    "VALUES ($1, $2, 1.0, '中景', '固定', $3, '', 'normal', 1) RETURNING id",
                    edit_episode_id, order_index, description,
                )
                edit_shot_ids.append(int(shot_id))
            await connection.execute(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2), ($1, $3), ($4, $5)",
                edit_shot_ids[0], asset_ids[0], asset_ids[1], edit_shot_ids[1], asset_ids[0],
            )
            generation_shot_id = await connection.fetchval(
                "INSERT INTO shots (episode_id, order_index, duration_est, shot_type, camera, description, dialogue, status, revision) "
                "VALUES ($1, 1, 1.0, '全景', '固定', 'old generation shot', '', 'normal', 1) RETURNING id",
                generation_episode_id,
            )
            await connection.execute(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                generation_shot_id, asset_ids[1],
            )
            clip_id = await connection.fetchval(
                "INSERT INTO clips (episode_id, requested_duration, generation_state, freshness, revision) "
                "VALUES ($1, 5, 'empty', 'fresh', 1) RETURNING id",
                edit_episode_id,
            )
            await connection.executemany(
                "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, $3)",
                [(clip_id, edit_shot_ids[0], 1), (clip_id, edit_shot_ids[1], 2)],
            )
            success_shot_ids: list[int] = []
            for order_index, description in ((3, "controlled success shot one"), (4, "controlled success shot two")):
                success_shot_id = await connection.fetchval(
                    "INSERT INTO shots (episode_id, order_index, duration_est, shot_type, camera, description, dialogue, status, revision) "
                    "VALUES ($1, $2, 2.0, '中景', '固定', $3, '', 'normal', 1) RETURNING id",
                    edit_episode_id, order_index, description,
                )
                success_shot_ids.append(int(success_shot_id))
                await connection.execute(
                    "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2), ($1, $3)",
                    success_shot_id, asset_ids[2], asset_ids[1],
                )
            success_clip_id = await connection.fetchval(
                "INSERT INTO clips (episode_id, requested_duration, generation_state, freshness, revision) "
                "VALUES ($1, 4, 'empty', 'fresh', 1) RETURNING id",
                edit_episode_id,
            )
            await connection.executemany(
                "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, $3)",
                [(success_clip_id, success_shot_ids[0], 1), (success_clip_id, success_shot_ids[1], 2)],
            )
            await connection.execute(
                "INSERT INTO clip_ref_slots (clip_id, slot_no, asset_id, asset_name_snapshot, asset_type_snapshot, enabled) "
                "VALUES ($1, 1, $2, $3, 'character', true)",
                success_clip_id, asset_ids[2], f"Cascade spare {token}",
            )
            from app.services.asset_files import asset_image_relative_path

            image_id = await connection.fetchval(
                "INSERT INTO asset_images (asset_id, file_path, sha256, source, is_current) "
                "VALUES ($1, 'pending', $2, 'generated', true) RETURNING id",
                asset_ids[2], "0" * 64,
            )
            image_relative_path = asset_image_relative_path(
                int(project_id), asset_ids[2], int(image_id), "png"
            )
            image_path = data_dir / image_relative_path
            image_path.parent.mkdir(parents=True, exist_ok=True)
            from PIL import Image

            image_buffer = io.BytesIO()
            Image.new("RGB", (320, 180), (32, 96, 160)).save(
                image_buffer, format="PNG"
            )
            image_bytes = image_buffer.getvalue()
            image_path.write_bytes(image_bytes)
            await connection.execute(
                "UPDATE asset_images SET file_path = $1, sha256 = $2 WHERE id = $3",
                image_relative_path.as_posix(), hashlib.sha256(image_bytes).hexdigest(), image_id,
            )
        return {
            "project_id": int(project_id), "style_id": int(style_id),
            "edit_episode_id": int(edit_episode_id), "generation_episode_id": int(generation_episode_id),
            "asset_ids": asset_ids, "edit_shot_ids": edit_shot_ids,
            "generation_shot_id": int(generation_shot_id), "clip_id": int(clip_id),
            "success_clip_id": int(success_clip_id), "success_shot_ids": success_shot_ids,
        }
    finally:
        await connection.close()


async def cascade_cleanup_fixture(raw_url: str, fixture: Mapping[str, object]) -> None:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    try:
        project_id = int(fixture["project_id"])
        await connection.execute(
            "DELETE FROM tasks WHERE target_id IN ($1, $2, $3)",
            fixture["edit_episode_id"], fixture["generation_episode_id"], fixture["success_clip_id"],
        )
        for table, predicate in (
            ("clip_shots", "clip_id IN (SELECT id FROM clips WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = $1))"),
            ("clip_ref_slots", "clip_id IN (SELECT id FROM clips WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = $1))"),
            ("clip_videos", "clip_id IN (SELECT id FROM clips WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = $1))"),
            ("shot_assets", "shot_id IN (SELECT id FROM shots WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = $1))"),
        ):
            await connection.execute(f"DELETE FROM {table} WHERE {predicate}", project_id)
        await connection.execute("DELETE FROM clips WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = $1)", project_id)
        await connection.execute("DELETE FROM shots WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = $1)", project_id)
        await connection.execute("DELETE FROM asset_images WHERE asset_id IN (SELECT id FROM assets WHERE project_id = $1)", project_id)
        await connection.execute("DELETE FROM assets WHERE project_id = $1", project_id)
        await connection.execute("DELETE FROM episodes WHERE project_id = $1", project_id)
        await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        await connection.execute("DELETE FROM styles WHERE id = $1", fixture["style_id"])
    finally:
        await connection.close()


async def cascade_http_json(client: httpx.AsyncClient, method: str, url: str, payload: object | None = None) -> HttpObservation:
    response = await client.request(method, url, json=payload)
    try:
        body: object = response.json()
    except ValueError:
        body = response.text
    return HttpObservation(response.status_code, body)


async def cascade_wait_task(client: httpx.AsyncClient, base_url: str, task_id: int) -> dict[str, object]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        observation = await cascade_http_json(client, "GET", f"{base_url}/api/tasks/{task_id}")
        if observation.status_code != 200 or not isinstance(observation.body, Mapping):
            raise AcceptanceFailure(f"task {task_id} detail read failed: {observation.status_code} {observation.body!r}")
        if observation.body.get("status") in {"done", "failed", "canceled"}:
            return dict(observation.body)
        await asyncio.sleep(0.1)
    raise AcceptanceFailure(f"task {task_id} did not reach a terminal state")


def start_backend_process(
    raw_url: str,
    data_dir: Path,
    dependency_stub: object,
    extra_env: Mapping[str, str] | None = None,
    comfy_dependency_stub: object | None = None,
) -> tuple[subprocess.Popen[bytes], int]:
    port = free_tcp_port()
    child_env = os.environ.copy()
    comfy_stub = dependency_stub if comfy_dependency_stub is None else comfy_dependency_stub
    child_env.update({"DATABASE_URL": raw_url, "DATA_DIR": str(data_dir), "VLLM_BASE_URL": dependency_stub.base_url, "COMFY_BASE_URL": comfy_stub.base_url, "PYTHONUTF8": "1"})
    if extra_env is not None:
        child_env.update(extra_env)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--lifespan",
            "on",
        ],
        cwd=BACKEND, env=child_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return process, port


async def command_cascade(_arguments: argparse.Namespace, evidence: RunEvidence) -> None:
    raw_url, data_dir, identity = explicit_runtime()
    database_identity = await read_database_identity(raw_url)
    evidence.add("runtime_identity", database_url=identity, database=database_identity, data_dir=str(data_dir))
    if database_identity["current_database"] != identity["database_from_url"]:
        raise AcceptanceFailure("database identity does not match explicit DATABASE_URL database")
    with tempfile.TemporaryDirectory(prefix="c012-cascade-", dir=str(data_dir)) as runtime_name:
        runtime_dir = Path(runtime_name)
        fixture = await cascade_seed_fixture(raw_url, runtime_dir)
        process: subprocess.Popen[bytes] | None = None
        stopped: ChildResult | None = None
        try:
            async with ControlledComfyStub() as dependency_stub:
                process, port = start_backend_process(
                    raw_url,
                    runtime_dir,
                    dependency_stub,
                    comfy_dependency_stub=dependency_stub,
                )
                base_url = f"http://127.0.0.1:{port}"
                health = await wait_for_http(f"{base_url}/api/system/health")
                if health.status_code != 200:
                    raise AcceptanceFailure(f"cascade backend health returned {health.status_code}")
                evidence.add("production_process", pid=process.pid, port=port, health=health.body, dependency_stub=dependency_stub.base_url)
                async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                    for template_key, content in (
                        ("script2assets", "{{existing_assets}} {{style}} {{script}}"),
                        ("script2shots", "{{assets}} {{style}} {{script}}"),
                    ):
                        template_path = f"/api/prompt-templates/{template_key}"
                        template_observation = await cascade_http_json(
                            client,
                            "PATCH",
                            f"{base_url}{template_path}",
                            {"content": content},
                        )
                        if template_observation.status_code != 200:
                            raise AcceptanceFailure(
                                f"cascade template {template_key} returned "
                                f"{template_observation.status_code}: {template_observation.body!r}"
                            )
                        evidence.add(
                            "cascade_operation",
                            operation="edit_style_template",
                            method="PATCH",
                            path=template_path,
                            status=template_observation.status_code,
                            response=template_observation.body,
                        )

                    assets_observation = await cascade_http_json(
                        client,
                        "POST",
                        f"{base_url}/api/episodes/{fixture['generation_episode_id']}/generate-assets",
                    )
                    if assets_observation.status_code != 202:
                        raise AcceptanceFailure(
                            f"cascade regenerate_assets returned "
                            f"{assets_observation.status_code}: {assets_observation.body!r}"
                        )
                    assets_body = require_mapping(assets_observation.body, "cascade regenerate_assets")
                    assets_task = await cascade_wait_task(
                        client, base_url, int(assets_body["task_id"])
                    )
                    if assets_task["status"] != "done":
                        raise AcceptanceFailure(f"cascade regenerate_assets task failed: {assets_task!r}")
                    evidence.add(
                        "cascade_operation",
                        operation="regenerate_assets",
                        method="POST",
                        path=f"/api/episodes/{fixture['generation_episode_id']}/generate-assets",
                        status=assets_observation.status_code,
                        response=assets_observation.body,
                        task=assets_task,
                    )
                    impact_observation = await cascade_http_json(
                        client,
                        "POST",
                        f"{base_url}/api/episodes/{fixture['generation_episode_id']}/generate-shots/impact",
                    )
                    impact = require_mapping(impact_observation.body, "cascade regenerate_shots impact")
                    shots_observation = await cascade_http_json(
                        client,
                        "POST",
                        f"{base_url}/api/episodes/{fixture['generation_episode_id']}/generate-shots",
                        {"confirm_token": impact.get("confirm_token")},
                    )
                    if shots_observation.status_code != 202:
                        raise AcceptanceFailure(
                            f"cascade regenerate_shots returned "
                            f"{shots_observation.status_code}: {shots_observation.body!r}"
                        )
                    shots_body = require_mapping(shots_observation.body, "cascade regenerate_shots")
                    shots_task = await cascade_wait_task(
                        client, base_url, int(shots_body["task_id"])
                    )
                    if shots_task["status"] != "done":
                        raise AcceptanceFailure(f"cascade regenerate_shots task failed: {shots_task!r}")
                    evidence.add(
                        "cascade_operation",
                        operation="regenerate_shots",
                        method="POST",
                        path=f"/api/episodes/{fixture['generation_episode_id']}/generate-shots",
                        impact=impact_observation.body,
                        status=shots_observation.status_code,
                        response=shots_observation.body,
                        task=shots_task,
                    )
                    simple_operations = [
                        ("edit_script", "PATCH", f"/api/episodes/{fixture['edit_episode_id']}", {"script_text": "cascade script edited"}),
                        ("edit_asset", "PATCH", f"/api/assets/{fixture['asset_ids'][0]}", {"name": f"Cascade renamed {uuid4().hex}"}),
                        ("edit_shot_binding", "PATCH", f"/api/shots/{fixture['edit_shot_ids'][1]}", {"asset_ids": [fixture['asset_ids'][1]]}),
                        ("edit_style_template", "PATCH", f"/api/styles/{fixture['style_id']}", {"prompt_fragment": "cascade updated style"}),
                        ("edit_style_template", "PATCH", "/api/prompt-templates/minimaxh3", {"content": "{{shots}} {{references}} {{style}} {{requested_duration}} {{user_note}}"}),
                        ("delete_clip", "DELETE", f"/api/clips/{fixture['clip_id']}", None),
                        ("delete_asset", "DELETE", f"/api/assets/{fixture['asset_ids'][0]}", None),
                    ]
                    for name, method, path, payload in simple_operations:
                        observation = await cascade_http_json(client, method, f"{base_url}{path}", payload)
                        if observation.status_code not in {200, 204}:
                            raise AcceptanceFailure(f"cascade {name} returned {observation.status_code}: {observation.body!r}")
                        evidence.add("cascade_operation", operation=name, method=method, path=path, status=observation.status_code, response=observation.body)
                    success_path = f"/api/clips/{fixture['success_clip_id']}/generate-video"
                    success_request_id = "c012-cascade-clip-success"
                    success_observation = await cascade_http_json(
                        client,
                        "POST",
                        f"{base_url}{success_path}",
                        {"request_id": success_request_id},
                    )
                    if success_observation.status_code != 202:
                        raise AcceptanceFailure(
                            f"cascade clip_success enqueue returned "
                            f"{success_observation.status_code}: {success_observation.body!r}"
                        )
                    success_body = require_mapping(success_observation.body, "cascade clip_success enqueue")
                    success_task_id = int(success_body["task_id"])
                    success_task = await cascade_wait_task(client, base_url, success_task_id)
                    videos_observation = await cascade_http_json(
                        client,
                        "GET",
                        f"{base_url}/api/clips/{fixture['success_clip_id']}/videos",
                    )
                    videos = videos_observation.body
                    if success_task["status"] != "done" or videos_observation.status_code != 200:
                        raise AcceptanceFailure(
                            f"cascade clip_success did not complete: task={success_task!r} videos={videos!r}"
                        )
                    if not isinstance(videos, list) or len(videos) != 1:
                        raise AcceptanceFailure(f"cascade clip_success video count mismatch: {videos!r}")
                    video = require_mapping(videos[0], "cascade clip_success video")
                    video_id = video.get("id")
                    if not isinstance(video_id, int):
                        raise AcceptanceFailure(f"cascade clip_success video id missing: {video!r}")
                    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
                    try:
                        stored_video = await connection.fetchrow(
                            "SELECT file_path, sha256, built_prompt, input_hash FROM clip_videos WHERE id = $1",
                            video_id,
                        )
                    finally:
                        await connection.close()
                    if stored_video is None:
                        raise AcceptanceFailure(f"cascade clip_success DB video row missing: {video_id}")
                    file_path = stored_video["file_path"]
                    if not isinstance(file_path, str) or not file_path:
                        raise AcceptanceFailure(f"cascade clip_success file path missing: {video!r}")
                    formal_path = (runtime_dir / Path(file_path)).resolve()
                    if runtime_dir.resolve() not in formal_path.parents or not formal_path.is_file():
                        raise AcceptanceFailure(f"cascade clip_success formal media missing: {formal_path}")
                    media_bytes = formal_path.read_bytes()
                    if not media_bytes or video.get("is_current") is not True:
                        raise AcceptanceFailure(f"cascade clip_success media/current mismatch: {video!r}")
                    evidence.add(
                        "cascade_operation",
                        operation="clip_success",
                        method="POST",
                        path=success_path,
                        status=success_observation.status_code,
                        response=success_observation.body,
                        task=success_task,
                        videos=videos,
                        media={
                            "path": str(formal_path),
                            "bytes": len(media_bytes),
                            "sha256": stored_video["sha256"],
                            "built_prompt": stored_video["built_prompt"],
                            "input_hash": stored_video["input_hash"],
                        },
                    )
        finally:
            if process is not None:
                stopped = stop_process(process)
                evidence.add("production_process_shutdown", **child_observation(stopped), process_exited=process.poll() is not None)
            await cascade_cleanup_fixture(raw_url, fixture)
        if stopped is None or stopped.timed_out or process is None or process.poll() is None:
            raise AcceptanceFailure("cascade owned production process did not cleanly stop")
    evidence.add("owned_resource_cleanup", production_process_stopped=True, runtime_directory_exists=runtime_dir.exists())


async def recovery_seed_tasks(raw_url: str) -> tuple[int, int]:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    running_target_id = 2_000_000_000 + (uuid4().int % 100_000_000)
    queued_target_id = 2_000_000_000 + (uuid4().int % 100_000_000)
    while queued_target_id == running_target_id:
        queued_target_id = 2_000_000_000 + (uuid4().int % 100_000_000)
    try:
        async with connection.transaction():
            running = int(await connection.fetchval("INSERT INTO tasks (type, target_id, status, progress, payload) VALUES ('gen_assets', $1, 'running', 0.5, '{}'::jsonb) RETURNING id", running_target_id))
            queued = int(await connection.fetchval("INSERT INTO tasks (type, target_id, status, progress, payload) VALUES ('gen_assets', $1, 'queued', 0, '{}'::jsonb) RETURNING id", queued_target_id))
        return running, queued
    finally:
        await connection.close()


async def command_recovery(_arguments: argparse.Namespace, evidence: RunEvidence) -> None:
    raw_url, data_dir, identity = explicit_runtime()
    database_identity = await read_database_identity(raw_url)
    evidence.add("runtime_identity", database_url=identity, database=database_identity, data_dir=str(data_dir))
    with tempfile.TemporaryDirectory(prefix="c012-recovery-", dir=str(data_dir)) as runtime_name:
        runtime_dir = Path(runtime_name)
        running_id, queued_id = await recovery_seed_tasks(raw_url)
        first: subprocess.Popen[bytes] | None = None
        second: subprocess.Popen[bytes] | None = None
        first_stop: ChildResult | None = None
        queued_lock_connection: asyncpg.Connection | None = None
        try:
            queued_lock_connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
            await queued_lock_connection.execute("BEGIN")
            await queued_lock_connection.fetchrow(
                "SELECT id FROM tasks WHERE id = $1 FOR UPDATE", queued_id
            )
            with ControlledHTTPStub() as dependency_stub:
                first, first_port = start_backend_process(raw_url, runtime_dir, dependency_stub)
                health = await wait_for_http(f"http://127.0.0.1:{first_port}/api/system/health")
                tasks_after = await read_database_tasks(raw_url)
                running_row = next(row for row in tasks_after if row["id"] == running_id)
                queued_row = next(row for row in tasks_after if row["id"] == queued_id)
                if running_row["status"] != "failed" or running_row["error_msg"] != "server restarted":
                    raise AcceptanceFailure(f"running recovery mismatch: {running_row!r}")
                evidence.add("running_recovery", first_pid=first.pid, first_port=first_port, health=health.body, running_task=running_row, queued_task=queued_row)
                second, second_port = start_backend_process(raw_url, runtime_dir, dependency_stub)
                try:
                    stdout, stderr = second.communicate(timeout=30)
                    second_result = ChildResult(command=tuple(str(part) for part in second.args), returncode=second.returncode, stdout=stdout, stderr=stderr)
                except subprocess.TimeoutExpired:
                    second_result = stop_process(second, timeout=1)
                evidence.add("advisory_lock_exclusion", second_pid=second.pid, second_port=second_port, **child_observation(second_result))
                lock_output = second_result.text_stdout() + second_result.text_stderr()
                if (
                    second_result.returncode == 0
                    or second_result.timed_out
                    or second_result.termination_requested
                    or "AdvisoryLockNotAcquired" not in lock_output
                    or "advisory lock is already held" not in lock_output
                ):
                    raise AcceptanceFailure(
                        "second backend did not naturally reject the shared advisory lock "
                        "with the expected startup error"
                    )
        finally:
            if second is not None and second.poll() is None:
                stop_process(second)
            if first is not None:
                first_stop = stop_process(first)
                evidence.add("first_process_shutdown", **child_observation(first_stop))
            if queued_lock_connection is not None:
                await queued_lock_connection.execute("ROLLBACK")
                await queued_lock_connection.close()
                queued_lock_connection = None
            connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
            try:
                await connection.execute("DELETE FROM tasks WHERE id = ANY($1::int[])", [running_id, queued_id])
            finally:
                await connection.close()
        if first_stop is None or first_stop.timed_out or first.poll() is None:
            raise AcceptanceFailure("recovery first backend did not cleanly stop")
    evidence.add("owned_resource_cleanup", production_process_stopped=True, runtime_directory_exists=runtime_dir.exists())


async def command_trash(_arguments: argparse.Namespace, evidence: RunEvidence) -> None:
    raw_url, data_dir, identity = explicit_runtime()
    database_identity = await read_database_identity(raw_url)
    evidence.add("runtime_identity", database_url=identity, database=database_identity, data_dir=str(data_dir))
    with tempfile.TemporaryDirectory(prefix="c012-trash-", dir=str(data_dir)) as runtime_name:
        runtime_dir = Path(runtime_name)
        trash_root = runtime_dir / "trash"
        trash_root.mkdir(parents=True)
        old_path = trash_root / "old.bin"
        recent_path = trash_root / "recent.bin"
        valid_path = runtime_dir / "valid.bin"
        old_path.write_bytes(b"old")
        recent_path.write_bytes(b"recent")
        valid_path.write_bytes(b"valid")
        old_time = time.time() - 7200
        os.utime(old_path, (old_time, old_time))
        process: subprocess.Popen[bytes] | None = None
        stopped: ChildResult | None = None
        try:
            with ControlledHTTPStub() as dependency_stub:
                process, port = start_backend_process(raw_url, runtime_dir, dependency_stub, {"TRASH_RETENTION_HOURS": "1"})
                health = await wait_for_http(f"http://127.0.0.1:{port}/api/system/health")
                if health.status_code != 200 or old_path.exists() or not recent_path.exists() or not valid_path.exists():
                    raise AcceptanceFailure("startup trash cleanup boundary was incorrect")
                evidence.add("startup_cleanup", pid=process.pid, port=port, health=health.body, old_exists=old_path.exists(), recent_exists=recent_path.exists(), outside_exists=valid_path.exists())
        finally:
            if process is not None:
                stopped = stop_process(process)
                evidence.add("startup_process_shutdown", **child_observation(stopped))
        if stopped is None or stopped.timed_out or process is None or process.poll() is None:
            raise AcceptanceFailure("trash startup process did not cleanly stop")

        scheduled_old = trash_root / "scheduled-old.bin"
        scheduled_new = trash_root / "scheduled-new.bin"
        scheduled_old.write_bytes(b"scheduled-old")
        scheduled_new.write_bytes(b"scheduled-new")
        os.utime(scheduled_old, (old_time, old_time))
        scheduled_code = """
import asyncio
import os
from pathlib import Path
import app.services.trash as trash

calls = 0

async def fake_sleep(_seconds):
    global calls
    calls += 1
    if calls > 1:
        raise asyncio.CancelledError

trash.asyncio.sleep = fake_sleep
asyncio.run(trash.run_trash_cleanup_loop(Path(os.environ["DATA_DIR"]), 1))
"""
        scheduled_env = os.environ.copy()
        scheduled_env.update({"DATABASE_URL": raw_url, "DATA_DIR": str(runtime_dir), "PYTHONUTF8": "1"})
        scheduled_result = run_child([sys.executable, "-c", scheduled_code], cwd=BACKEND, env=scheduled_env, timeout=10)
        evidence.add("scheduled_cleanup", **child_observation(scheduled_result), old_exists=scheduled_old.exists(), new_exists=scheduled_new.exists())
        if (
            scheduled_result.returncode != 1
            or scheduled_result.timed_out
            or "CancelledError" not in scheduled_result.text_stderr()
            or scheduled_old.exists()
            or not scheduled_new.exists()
        ):
            raise AcceptanceFailure("scheduled trash cleanup probe failed")

        recent_path.unlink()
        scheduled_new.unlink()
        trash_root.rmdir()
        trash_root.write_bytes(b"not a directory")
        failure_code = "from pathlib import Path; import os; from app.services.trash import cleanup_expired_trash; cleanup_expired_trash(Path(os.environ['DATA_DIR']), 1)"
        failure_env = os.environ.copy()
        failure_env.update({"DATABASE_URL": raw_url, "DATA_DIR": str(runtime_dir), "PYTHONUTF8": "1"})
        failure_result = run_child([sys.executable, "-c", failure_code], cwd=BACKEND, env=failure_env, timeout=10)
        evidence.add("io_failure_visible", **child_observation(failure_result))
        if (
            failure_result.returncode == 0
            or failure_result.timed_out
            or failure_result.termination_requested
            or "NotADirectoryError" not in failure_result.text_stderr()
        ):
            raise AcceptanceFailure(
                "trash IO failure probe did not expose the expected NotADirectoryError"
            )


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        prog="python -X utf8 .work/c012/acceptance.py"
    )
    subparsers = argument_parser.add_subparsers(dest="command", required=True)
    selfcheck = subparsers.add_parser("selfcheck")
    selfcheck.add_argument(
        "--fail-case",
        choices=("none", "child", "startup"),
        default="none",
        help="intentionally stop after the selected non-zero probe",
    )
    locks = subparsers.add_parser("locks")
    locks.add_argument(
        "--case", choices=("L1", "L2", "L3", "L4", "L5", "all"), required=True
    )
    for name in (
        "migration",
        "names",
        "ws",
        "cascade",
        "recovery",
        "trash",
        "verify-inputs",
    ):
        subparsers.add_parser(name)
    real_preflight = subparsers.add_parser("preflight")
    real_preflight.add_argument("--real", action="store_true")
    observe = subparsers.add_parser("observe")
    observe.add_argument("--real", action="store_true")
    return argument_parser


async def run(arguments: argparse.Namespace, evidence: RunEvidence) -> None:
    if arguments.command == "selfcheck":
        await command_selfcheck(arguments, evidence)
        return
    if arguments.command == "locks":
        await command_locks(arguments, evidence)
        return
    if arguments.command == "migration":
        await command_migration(arguments, evidence)
        return
    if arguments.command == "names":
        await command_names(arguments, evidence)
        return
    if arguments.command == "ws":
        await command_ws(arguments, evidence)
        return
    if arguments.command == "cascade":
        await command_cascade(arguments, evidence)
        return
    if arguments.command == "recovery":
        await command_recovery(arguments, evidence)
        return
    if arguments.command == "trash":
        await command_trash(arguments, evidence)
        return
    if arguments.command == "verify-inputs":
        await command_verify_inputs(arguments, evidence)
        return
    if arguments.command == "preflight":
        if not arguments.real:
            raise AcceptanceFailure("preflight requires --real")
        await command_preflight(arguments, evidence)
        return
    if arguments.command == "observe":
        if not arguments.real:
            raise AcceptanceFailure("observe requires --real")
        await command_observe(arguments, evidence)
        return
    raise AcceptanceFailure(
        f"C012 acceptance command {arguments.command!r} is reserved for its scheduled task"
    )


async def async_main(arguments: argparse.Namespace) -> int:
    evidence = RunEvidence(
        command=arguments.command,
        args=sys.argv[1:],
    )
    try:
        await run(arguments, evidence)
    except AcceptanceFailure as exc:
        evidence.finish(status="failed", error=str(exc))
        evidence_path = evidence.write()
        print(
            json.dumps(
                {"status": "failed", "error": str(exc), "evidence": str(evidence_path)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    evidence.finish(status="passed")
    evidence_path = evidence.write()
    print(
        json.dumps(
            {"status": "passed", "command": arguments.command, "evidence": str(evidence_path)},
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    return asyncio.run(async_main(parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
