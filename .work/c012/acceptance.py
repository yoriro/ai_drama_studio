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
import functools
import hashlib
import io
import json
import logging
import os
import re
import select
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
from urllib.parse import parse_qs, urlsplit, urlunsplit
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
    drain_state = getattr(process, "_c012_drain_state", None)
    if drain_state is None:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
    else:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait()
        stdout_buffer, stderr_buffer, stdout_thread, stderr_thread = drain_state
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        stdout = bytes(stdout_buffer)
        stderr = bytes(stderr_buffer)
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
                            "9": {
                                "images": [
                                    {
                                        "filename": "controlled.png",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            },
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


class RecoveryHTTPServer(ControlledHTTPServer):
    def __init__(
        self,
        *args: object,
        controller: "RecoveryHTTPStub",
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.controller = controller


class RecoveryHTTPHandler(HealthStubHandler):
    def _controller(self) -> "RecoveryHTTPStub":
        server = self.server
        if not isinstance(server, RecoveryHTTPServer):
            raise AcceptanceFailure("recovery HTTP handler has an unexpected server")
        return server.controller

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        self._controller().record_http("GET", self.path)
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        controller = self._controller()
        if self.path != "/v1/chat/completions":
            controller.record_http("POST", self.path)
            super().do_POST()
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            body: object = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            body = None
        request_index = controller.record_chat(raw_body, body)
        controller.chat_handlers_started += 1
        try:
            if controller.block_chat.is_set():
                wait_result = controller.wait_for_release_or_disconnect(
                    self.connection
                )
                if wait_result == "client_closed":
                    controller.record_chat_disconnect(
                        request_index, "client_closed_before_response"
                    )
                    return
                if wait_result == "timed_out":
                    controller.record_chat_timeout(request_index)
                    self._send_json(
                        504,
                        {"detail": "recovery chat release was not observed"},
                    )
                    return

            content = {
                "assets": [
                    {
                        "existing_id": None,
                        "type": "character",
                        "name": f"C012 recovery generated asset {request_index}",
                        "description": (
                            f"recovery controlled generated asset {request_index}"
                        ),
                    }
                ]
            }
            response_payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(content, ensure_ascii=False)
                        }
                    }
                ]
            }
            controller.record_chat_response(request_index, response_payload)
            try:
                self._send_json(200, response_payload)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                controller.record_chat_disconnect(
                    request_index, "client_closed_during_response"
                )
        finally:
            controller.chat_handlers_started -= 1


class RecoveryHTTPStub:
    """Controlled vLLM/Comfy boundary for real recovery lifecycle runs."""

    def __init__(self) -> None:
        self.block_chat = threading.Event()
        self.chat_release = threading.Event()
        self.chat_client_closed = threading.Event()
        self.chat_requests: list[dict[str, object]] = []
        self.chat_responses: list[dict[str, object]] = []
        self.chat_disconnects: list[dict[str, object]] = []
        self.chat_timeouts: list[int] = []
        self.http_requests: list[dict[str, str]] = []
        self.chat_handlers_started = 0
        self._lock = threading.Lock()
        self.server = RecoveryHTTPServer(
            ("127.0.0.1", 0),
            RecoveryHTTPHandler,
            controller=self,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="c012-recovery-http-stub",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "RecoveryHTTPStub":
        self.thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.chat_release.set()
        self.block_chat.clear()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AcceptanceFailure("owned recovery HTTP stub thread did not stop")

    def set_blocked(self) -> None:
        self.chat_release.clear()
        self.block_chat.set()

    def release(self) -> None:
        self.chat_release.set()
        self.block_chat.clear()

    def record_http(self, method: str, path: str) -> None:
        with self._lock:
            self.http_requests.append({"method": method, "path": path})

    def record_chat(self, raw_body: bytes, body: object) -> int:
        with self._lock:
            request_index = len(self.chat_requests) + 1
            self.chat_requests.append(
                {
                    "request_index": request_index,
                    "method": "POST",
                    "path": "/v1/chat/completions",
                    "raw_body_utf8": raw_body.decode("utf-8", errors="replace"),
                    "body": body,
                }
            )
            self.http_requests.append(
                {"method": "POST", "path": "/v1/chat/completions"}
            )
            return request_index

    def record_chat_response(
        self, request_index: int, response_payload: Mapping[str, object]
    ) -> None:
        with self._lock:
            self.chat_responses.append(
                {
                    "request_index": request_index,
                    "response": dict(response_payload),
                }
            )

    def record_chat_disconnect(self, request_index: int, reason: str) -> None:
        with self._lock:
            self.chat_disconnects.append(
                {"request_index": request_index, "reason": reason}
            )
        self.chat_client_closed.set()

    def record_chat_timeout(self, request_index: int) -> None:
        with self._lock:
            self.chat_timeouts.append(request_index)

    def wait_for_release_or_disconnect(self, connection: socket.socket) -> str:
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            if self.chat_release.is_set():
                return "released"
            try:
                readable, _, _ = select.select([connection], [], [], 0.05)
            except (OSError, ValueError):
                return "client_closed"
            if not readable:
                continue
            try:
                data = connection.recv(1, socket.MSG_PEEK)
            except BlockingIOError:
                continue
            except (ConnectionAbortedError, ConnectionResetError, OSError):
                return "client_closed"
            if data == b"":
                return "client_closed"
        return "timed_out"

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            by_path: dict[str, int] = {}
            for request in self.http_requests:
                path = request["path"]
                by_path[path] = by_path.get(path, 0) + 1
            return {
                "http_requests": list(self.http_requests),
                "http_counts_by_path": by_path,
                "chat_requests": list(self.chat_requests),
                "chat_responses": list(self.chat_responses),
                "chat_disconnects": list(self.chat_disconnects),
                "chat_timeouts": list(self.chat_timeouts),
                "chat_handlers_started": self.chat_handlers_started,
            }


class SlowASGISendGate:
    """Hold the first production task-event send at the ASGI boundary."""

    def __init__(self, application: Any) -> None:
        self.application = application
        self.release = asyncio.Event()
        self.first_send_started = asyncio.Event()
        self.send_cancelled = asyncio.Event()
        self.first_message: dict[str, object] | None = None
        self.active_connections = 0
        self.completed_connections = 0

    async def __call__(
        self,
        scope: Mapping[str, object],
        receive: Any,
        send: Any,
    ) -> None:
        if scope.get("type") != "websocket" or scope.get("path") != "/ws/tasks":
            await self.application(scope, receive, send)
            return

        self.active_connections += 1

        async def gated_send(message: Mapping[str, object]) -> None:
            if (
                message.get("type") == "websocket.send"
                and not self.first_send_started.is_set()
            ):
                self.first_message = {
                    "type": message.get("type"),
                    "text_length": (
                        len(message["text"])
                        if isinstance(message.get("text"), str)
                        else None
                    ),
                }
                self.first_send_started.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.send_cancelled.set()
                    raise
            await send(message)

        try:
            await self.application(scope, receive, gated_send)
        finally:
            self.active_connections -= 1
            self.completed_connections += 1


class CapturedLogHandler(logging.Handler):
    """Capture only selected production log records for acceptance evidence."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class RecordingSlowASGISendGate(SlowASGISendGate):
    """Add request ordering evidence for the real TasksPage browser run."""

    def __init__(self, application: Any) -> None:
        super().__init__(application)
        self.http_requests: list[dict[str, object]] = []
        self.websocket_connections: list[dict[str, object]] = []
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    async def __call__(
        self,
        scope: Mapping[str, object],
        receive: Any,
        send: Any,
    ) -> None:
        scope_type = scope.get("type")
        if scope_type == "http":
            request: dict[str, object] = {
                "sequence": self._next_sequence(),
                "method": scope.get("method"),
                "path": scope.get("path"),
                "query_string": (
                    scope.get("query_string", b"").decode("ascii")
                    if isinstance(scope.get("query_string", b""), bytes)
                    else str(scope.get("query_string", ""))
                ),
            }
            self.http_requests.append(request)

            async def recording_send(message: Mapping[str, object]) -> None:
                if message.get("type") == "http.response.start":
                    request["status"] = message.get("status")
                await send(message)

            await self.application(scope, receive, recording_send)
            return

        if scope_type == "websocket":
            connection: dict[str, object] = {
                "sequence": self._next_sequence(),
                "path": scope.get("path"),
            }
            self.websocket_connections.append(connection)
            try:
                await super().__call__(scope, receive, send)
            finally:
                connection["completed"] = True
            return

        await self.application(scope, receive, send)


class SlowBrowserHTTPServer(ControlledHTTPServer):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.block_enabled = threading.Event()
        self.chat_started = threading.Event()
        self.chat_release = threading.Event()


class SlowBrowserStubHandler(HealthStubHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        if (
            self.path == "/v1/chat/completions"
            and isinstance(self.server, SlowBrowserHTTPServer)
            and self.server.block_enabled.is_set()
        ):
            self.server.chat_started.set()
            if not self.server.chat_release.wait(timeout=180):
                self._send_json(
                    504,
                    {"detail": "slow-page browser release was not observed"},
                )
                return
        super().do_POST()


class SlowBrowserHTTPStub:
    """External vLLM/Comfy stub with an explicit model-release barrier."""

    def __init__(self) -> None:
        self.server = SlowBrowserHTTPServer(
            ("127.0.0.1", 0), SlowBrowserStubHandler
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="c012-slow-page-browser-http-stub",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "SlowBrowserHTTPStub":
        self.thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AcceptanceFailure("owned browser HTTP stub thread did not stop")


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


def controlled_png_bytes() -> bytes:
    """Create one legal, deterministic offline image for the controlled path."""

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (320, 180), (160, 64, 32)).save(output, format="PNG")
    return output.getvalue()


class ControlledComfyStub:
    """A local HTTP/WebSocket Comfy boundary for the real worker path."""

    _WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, *, response_mode: str = "empty") -> None:
        self.server: asyncio.AbstractServer | None = None
        self.video = controlled_mp4_bytes()
        self.image = controlled_png_bytes()
        self.upload_count = 0
        self.response_mode = response_mode
        self.chat_observations: list[dict[str, object]] = []
        self.http_observations: list[dict[str, object]] = []
        self.model_errors: list[dict[str, object]] = []

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
                writer.close()

    async def _handle_http(
        self,
        method: str,
        raw_path: str,
        body: bytes,
        writer: asyncio.StreamWriter,
    ) -> None:
        path = urlsplit(raw_path).path
        request_observation: dict[str, object] = {
            "method": method,
            "path": path,
            "body_bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
        }
        if body:
            try:
                request_observation["json"] = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        self.http_observations.append(request_observation)
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
                            "9": {
                                "images": [
                                    {
                                        "filename": "controlled.png",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            },
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
            query = parse_qs(urlsplit(raw_path).query)
            filename = query.get("filename", [""])[0]
            if filename.endswith(".mp4"):
                content_type = "video/mp4"
                response_body = self.video
            else:
                content_type = "image/png"
                response_body = self.image
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
                try:
                    model_content = self._model_content(request_body, schema_name)
                except ValueError as exc:
                    self.model_errors.append(
                        {
                            "schema_name": schema_name,
                            "error": str(exc),
                            "request": request_body,
                        }
                    )
                    raise
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
        request_observation.update(
            {
                "raw_path": raw_path,
                "response_status": status,
                "response_content_type": content_type,
                "response_body_bytes": len(response_body),
                "response_body_sha256": hashlib.sha256(response_body).hexdigest(),
                "response_body_prefix_hex": response_body[:16].hex(),
                "response_prepared": True,
            }
        )
        await self._write_http_response(writer, status, content_type, response_body)
        request_observation["response_sent"] = True

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
            if content.startswith("existing="):
                content = content[len("existing=") :]
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


SLOW_PAGE_TASK_COUNT = 90
SLOW_PAGE_BROWSER_PRE_TASK_COUNT = 40
SLOW_PAGE_BROWSER_POST_TASK_COUNT = 86
SLOW_PAGE_BROWSER_TASK_COUNT = (
    SLOW_PAGE_BROWSER_PRE_TASK_COUNT
    + 1
    + SLOW_PAGE_BROWSER_POST_TASK_COUNT
)
T41_BROWSER_MANUAL_TIMEOUT_SECONDS = 900.0


async def slow_page_http_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    payload: object | None = None,
) -> tuple[int, object]:
    if payload is None:
        response = await client.request(method, url)
    else:
        response = await client.request(method, url, json=payload)
    try:
        body: object = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


async def slow_page_create_fixture(
    client: httpx.AsyncClient,
    base_url: str,
    request_log: list[dict[str, object]],
    *,
    task_count: int = SLOW_PAGE_TASK_COUNT,
) -> dict[str, object]:
    token = uuid4().hex
    style_path = "/api/styles"
    style_status, style_body = await slow_page_http_json(
        client,
        "POST",
        f"{base_url}{style_path}",
        {"name": f"C012 slow page {token}", "prompt_fragment": "受控慢连接"},
    )
    request_log.append(
        {"method": "POST", "path": style_path, "status": style_status}
    )
    if style_status != 201:
        raise AcceptanceFailure(
            f"slow-page style creation returned {style_status}: {style_body!r}"
        )
    style = require_mapping(style_body, "slow-page style response")
    style_id = style.get("id")
    if not isinstance(style_id, int):
        raise AcceptanceFailure(f"slow-page style id missing: {style_body!r}")

    project_path = "/api/projects"
    project_status, project_body = await slow_page_http_json(
        client,
        "POST",
        f"{base_url}{project_path}",
        {"name": f"C012 slow page project {token}", "style_id": style_id},
    )
    request_log.append(
        {"method": "POST", "path": project_path, "status": project_status}
    )
    if project_status != 201:
        raise AcceptanceFailure(
            f"slow-page project creation returned {project_status}: {project_body!r}"
        )
    project = require_mapping(project_body, "slow-page project response")
    project_id = project.get("id")
    if not isinstance(project_id, int):
        raise AcceptanceFailure(f"slow-page project id missing: {project_body!r}")

    template_path = "/api/prompt-templates/script2assets"
    template_status, template_body = await slow_page_http_json(
        client,
        "PATCH",
        f"{base_url}{template_path}",
        {"content": "{{existing_assets}} {{style}} {{script}}"},
    )
    request_log.append(
        {"method": "PATCH", "path": template_path, "status": template_status}
    )
    if template_status != 200:
        raise AcceptanceFailure(
            f"slow-page template patch returned {template_status}: {template_body!r}"
        )

    episode_ids: list[int] = []
    for sequence in range(1, task_count + 1):
        episode_path = f"/api/projects/{project_id}/episodes"
        episode_status, episode_body = await slow_page_http_json(
            client,
            "POST",
            f"{base_url}{episode_path}",
            {
                "seq": sequence,
                "title": f"慢连接任务 {sequence}",
                "script_text": f"slow-page controlled script {sequence}",
            },
        )
        request_log.append(
            {
                "method": "POST",
                "path": episode_path,
                "status": episode_status,
                "sequence": sequence,
            }
        )
        if episode_status != 201:
            raise AcceptanceFailure(
                f"slow-page episode {sequence} creation returned "
                f"{episode_status}: {episode_body!r}"
            )
        episode = require_mapping(episode_body, f"slow-page episode {sequence}")
        episode_id = episode.get("id")
        if not isinstance(episode_id, int):
            raise AcceptanceFailure(
                f"slow-page episode {sequence} id missing: {episode_body!r}"
            )
        episode_ids.append(episode_id)

    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_ids": episode_ids,
        "task_count": task_count,
    }


async def slow_page_read_state(
    raw_url: str,
    task_ids: Sequence[int],
    episode_ids: Sequence[int],
) -> dict[str, object]:
    tasks = await read_database_tasks(raw_url)
    task_id_set = set(task_ids)
    selected_tasks = [task for task in tasks if task["id"] in task_id_set]
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", ""))
    try:
        episode_rows = await connection.fetch(
            "SELECT id, script_revision, assets_generated_script_revision "
            "FROM episodes WHERE id = ANY($1::int[]) ORDER BY id",
            list(episode_ids),
        )
    finally:
        await connection.close()
    return {
        "tasks": selected_tasks,
        "episodes": [
            {
                "id": row["id"],
                "script_revision": row["script_revision"],
                "assets_generated_script_revision": row[
                    "assets_generated_script_revision"
                ],
            }
            for row in episode_rows
        ],
    }


async def slow_page_wait_for_terminal(
    raw_url: str,
    task_ids: Sequence[int],
    episode_ids: Sequence[int],
    *,
    timeout: float = 90.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        state = await slow_page_read_state(raw_url, task_ids, episode_ids)
        last_state = state
        tasks = state["tasks"]
        if (
            isinstance(tasks, list)
            and len(tasks) == len(task_ids)
            and all(
                isinstance(task, Mapping)
                and task.get("status") in {"done", "failed", "canceled"}
                for task in tasks
            )
        ):
            return state
        await asyncio.sleep(0.1)
    raise AcceptanceFailure(
        f"slow-page tasks did not reach terminal states: {last_state!r}"
    )


async def slow_page_cleanup(
    raw_url: str,
    style_id: int | None,
    project_id: int | None,
    episode_ids: Sequence[int],
    task_ids: Sequence[int],
) -> str:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", ""))
    try:
        async with connection.transaction():
            if task_ids:
                await connection.execute(
                    "DELETE FROM tasks WHERE id = ANY($1::int[])",
                    list(task_ids),
                )
            if episode_ids:
                await connection.execute(
                    "DELETE FROM episodes WHERE id = ANY($1::int[])",
                    list(episode_ids),
                )
            if project_id is not None:
                await connection.execute(
                    "DELETE FROM projects WHERE id = $1", project_id
                )
            if style_id is not None:
                await connection.execute(
                    "DELETE FROM styles WHERE id = $1", style_id
                )
    finally:
        await connection.close()
    return "deleted"


async def stop_slow_page_server(
    server: Any,
    server_task: asyncio.Task[Any],
) -> dict[str, object]:
    server.should_exit = True
    try:
        await asyncio.wait_for(server_task, timeout=30)
    except asyncio.TimeoutError:
        if not server_task.done():
            server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        return {"server_task_done": server_task.done(), "timed_out": True}
    if server_task.cancelled():
        return {"server_task_done": True, "cancelled": True, "timed_out": False}
    error = server_task.exception()
    if error is not None:
        return {
            "server_task_done": True,
            "timed_out": False,
            "exception": repr(error),
        }
    return {"server_task_done": True, "timed_out": False, "exception": None}


async def command_ws_slow_page(
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

    request_log: list[dict[str, object]] = []
    fixture: dict[str, object] = {}
    task_ids: list[int] = []
    episode_ids: list[int] = []
    style_id: int | None = None
    project_id: int | None = None
    first_task_id: int | None = None
    final_state: dict[str, object] | None = None
    gate: SlowASGISendGate | None = None
    server: Any | None = None
    server_task: asyncio.Task[Any] | None = None
    server_port: int | None = None
    shutdown_result: dict[str, object] | None = None
    cleanup_result: str | None = None
    task_logger: logging.Logger | None = None
    log_handler = CapturedLogHandler()

    with tempfile.TemporaryDirectory(
        prefix="c012-ws-slow-page-", dir=str(data_dir)
    ) as runtime_name:
        runtime_dir = Path(runtime_name)
        try:
            with ControlledHTTPStub() as dependency_stub:
                os.environ.update(
                    {
                        "DATABASE_URL": raw_url,
                        "PYTHONUTF8": "1",
                        "DATA_DIR": str(runtime_dir),
                        "VLLM_BASE_URL": dependency_stub.base_url,
                        "COMFY_BASE_URL": dependency_stub.base_url,
                    }
                )
                if "app.main" in sys.modules:
                    raise AcceptanceFailure(
                        "production app was imported before the isolated slow-page runtime"
                    )
                import uvicorn

                from app.main import app as production_app

                gate = SlowASGISendGate(production_app)
                server_port = free_tcp_port()
                server = uvicorn.Server(
                    uvicorn.Config(
                        gate,
                        host="127.0.0.1",
                        port=server_port,
                        log_level="warning",
                        lifespan="on",
                        access_log=False,
                    )
                )
                task_logger = logging.getLogger("app.api.tasks")
                task_logger.addHandler(log_handler)
                server_task = asyncio.create_task(
                    server.serve(), name="c012-slow-page-production-server"
                )
                base_url = f"http://127.0.0.1:{server_port}"
                health = await wait_for_http(
                    f"{base_url}/api/system/health", timeout=30
                )
                if health.status_code != 200:
                    raise AcceptanceFailure(
                        f"slow-page production health returned {health.status_code}: "
                        f"{health.body!r}"
                    )
                evidence.add(
                    "production_runtime",
                    pid=os.getpid(),
                    port=server_port,
                    health=health.body,
                    app_module="app.main:app",
                    lifespan=True,
                    queue="production TaskQueue",
                    handler="gen_assets_handler",
                    event_bus="production EventBus",
                    dependency_stub=dependency_stub.base_url,
                    asgi_gate="websocket.send only",
                )

                async with httpx.AsyncClient(
                    timeout=10, trust_env=False
                ) as client:
                    fixture = await slow_page_create_fixture(
                        client, base_url, request_log
                    )
                    style_id = int(fixture["style_id"])
                    project_id = int(fixture["project_id"])
                    episode_ids = [int(value) for value in fixture["episode_ids"]]
                    if len(episode_ids) != SLOW_PAGE_TASK_COUNT:
                        raise AcceptanceFailure(
                            "slow-page fixture did not create the requested episode count"
                        )

                    ws_uri = f"ws://127.0.0.1:{server_port}/ws/tasks"
                    first_path = (
                        f"/api/episodes/{episode_ids[0]}/generate-assets"
                    )
                    async with websockets.asyncio.client.connect(
                        ws_uri, open_timeout=10, close_timeout=10
                    ) as websocket:
                        first_status, first_body = await slow_page_http_json(
                            client, "POST", f"{base_url}{first_path}"
                        )
                        first_request: dict[str, object] = {
                            "method": "POST",
                            "path": first_path,
                            "status": first_status,
                        }
                        if isinstance(first_body, Mapping):
                            first_request["response"] = dict(first_body)
                        request_log.append(first_request)
                        if first_status != 202:
                            raise AcceptanceFailure(
                                f"slow-page first generation returned "
                                f"{first_status}: {first_body!r}"
                            )
                        first_mapping = require_mapping(
                            first_body, "slow-page first generation response"
                        )
                        raw_first_task_id = first_mapping.get("task_id")
                        if not isinstance(raw_first_task_id, int):
                            raise AcceptanceFailure(
                                f"slow-page first task id missing: {first_body!r}"
                            )
                        first_task_id = raw_first_task_id
                        task_ids.append(first_task_id)

                        try:
                            await asyncio.wait_for(
                                gate.first_send_started.wait(), timeout=10
                            )
                        except asyncio.TimeoutError as exc:
                            raise AcceptanceFailure(
                                "production task-event send did not reach the ASGI gate"
                            ) from exc

                        for episode_id in episode_ids[1:]:
                            generation_path = (
                                f"/api/episodes/{episode_id}/generate-assets"
                            )
                            status_code, body = await slow_page_http_json(
                                client,
                                "POST",
                                f"{base_url}{generation_path}",
                            )
                            request_entry: dict[str, object] = {
                                "method": "POST",
                                "path": generation_path,
                                "status": status_code,
                                "target_episode_id": episode_id,
                            }
                            if isinstance(body, Mapping):
                                request_entry["response"] = dict(body)
                            request_log.append(request_entry)
                            if status_code != 202:
                                raise AcceptanceFailure(
                                    f"slow-page generation for episode {episode_id} "
                                    f"returned {status_code}: {body!r}"
                                )
                            mapping = require_mapping(
                                body,
                                f"slow-page generation {episode_id} response",
                            )
                            raw_task_id = mapping.get("task_id")
                            if not isinstance(raw_task_id, int):
                                raise AcceptanceFailure(
                                    f"slow-page task id missing for episode "
                                    f"{episode_id}: {body!r}"
                                )
                            task_ids.append(raw_task_id)

                        try:
                            await asyncio.wait_for(websocket.recv(), timeout=30)
                        except websockets.exceptions.ConnectionClosed as exc:
                            close_observation = {
                                "code": exc.code,
                                "reason": exc.reason,
                            }
                        else:
                            raise AcceptanceFailure(
                                "slow-page WebSocket yielded a message instead of closing"
                            )

                        if close_observation["code"] != 1013:
                            raise AcceptanceFailure(
                                f"slow-page WebSocket close code mismatch: "
                                f"{close_observation!r}"
                            )
                        try:
                            await asyncio.wait_for(
                                gate.send_cancelled.wait(), timeout=5
                            )
                        except asyncio.TimeoutError as exc:
                            raise AcceptanceFailure(
                                "ASGI-gated send was not cancelled after overflow close"
                            ) from exc

                        final_state = await slow_page_wait_for_terminal(
                            raw_url, task_ids, episode_ids
                        )
                        task_rows = final_state["tasks"]
                        if not isinstance(task_rows, list) or any(
                            not isinstance(row, Mapping)
                            or row.get("status") != "done"
                            or row.get("error_msg") is not None
                            for row in task_rows
                        ):
                            raise AcceptanceFailure(
                                f"slow-page production handlers did not all finish done: "
                                f"{task_rows!r}"
                            )
                        episode_rows = final_state["episodes"]
                        if not isinstance(episode_rows, list) or any(
                            not isinstance(row, Mapping)
                            or row.get("script_revision") != 1
                            or row.get("assets_generated_script_revision") != 1
                            for row in episode_rows
                        ):
                            raise AcceptanceFailure(
                                f"slow-page episode markers did not close through handlers: "
                                f"{episode_rows!r}"
                            )

                        overflow_logs = [
                            message
                            for message in log_handler.messages
                            if "subscription_overflow" in message
                        ]
                        if not overflow_logs:
                            raise AcceptanceFailure(
                                "production task WebSocket logs did not record subscription_overflow"
                            )
                        evidence.add(
                            "slow_page_observation",
                            browser_address=f"{base_url}/api/tasks/{first_task_id}",
                            tasks_page_address="http://127.0.0.1:5173/tasks",
                            tasks_page_note=(
                                "existing Vite proxy is fixed to 127.0.0.1:8000; "
                                "T41 must consume the isolated backend with a matching frontend route"
                            ),
                            websocket_uri=ws_uri,
                            first_task_id=first_task_id,
                            task_ids=task_ids,
                            event_queue_capacity=256,
                            submitted_task_count=len(task_ids),
                            submitted_event_lower_bound=len(task_ids) * 3,
                            first_gated_message=gate.first_message,
                            send_cancelled=gate.send_cancelled.is_set(),
                            websocket_close=close_observation,
                            production_close_logs=overflow_logs,
                            request_count=len(request_log),
                        )

                await asyncio.sleep(0)
                if gate.active_connections != 0:
                    raise AcceptanceFailure(
                        f"slow-page WebSocket connections remained active: "
                        f"{gate.active_connections}"
                    )
        finally:
            if gate is not None:
                gate.release.set()
            if server is not None and server_task is not None:
                shutdown_result = await stop_slow_page_server(
                    server, server_task
                )
                evidence.add(
                    "production_process_shutdown",
                    **shutdown_result,
                    process="in-process uvicorn server",
                    port=server_port,
                )
            if task_logger is not None:
                task_logger.removeHandler(log_handler)
            if request_log:
                evidence.add(
                    "production_request_log",
                    requests=request_log,
                    count=len(request_log),
                )
            if final_state is not None:
                evidence.add("terminal_database_readback", **final_state)
            if style_id is not None or project_id is not None or task_ids:
                cleanup_result = await slow_page_cleanup(
                    raw_url,
                    style_id,
                    project_id,
                    episode_ids,
                    task_ids,
                )
                evidence.add(
                    "task_fixture_cleanup",
                    style_id=style_id,
                    project_id=project_id,
                    episode_count=len(episode_ids),
                    task_count=len(task_ids),
                    result=cleanup_result,
                )

        if shutdown_result is None or shutdown_result.get("timed_out"):
            raise AcceptanceFailure(
                f"slow-page production server did not stop cleanly: {shutdown_result!r}"
            )
        if shutdown_result.get("exception") is not None:
            raise AcceptanceFailure(
                f"slow-page production server raised during shutdown: "
                f"{shutdown_result!r}"
            )
        listeners = observe_windows_listeners([server_port]) if server_port else {}
        evidence.add("owned_listener_cleanup", **listeners)
        if listeners.get("listeners"):
            raise AcceptanceFailure(
                f"slow-page owned port still has listeners: {listeners!r}"
            )

    if runtime_dir.exists():
        raise AcceptanceFailure("slow-page runtime directory was not released")
    evidence.add(
        "owned_resource_cleanup",
        runtime_directory_exists=runtime_dir.exists(),
        dependency_stub_stopped=True,
        production_server_stopped=True,
        database_connections_closed=True,
        cleanup=cleanup_result,
    )


async def command_ws_slow_page_browser(
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

    request_log: list[dict[str, object]] = []
    fixture: dict[str, object] = {}
    task_ids: list[int] = []
    episode_ids: list[int] = []
    style_id: int | None = None
    project_id: int | None = None
    target_task_id: int | None = None
    final_state: dict[str, object] | None = None
    gate: RecordingSlowASGISendGate | None = None
    server: Any | None = None
    server_task: asyncio.Task[Any] | None = None
    server_port: int | None = None
    shutdown_result: dict[str, object] | None = None
    cleanup_result: str | None = None
    task_logger: logging.Logger | None = None
    gen_assets_module: Any | None = None
    original_vllm_client: Any | None = None
    log_handler = CapturedLogHandler()
    release_path_value = os.environ.get("C012_T41_RELEASE_FILE")
    release_path = Path(
        release_path_value
        if release_path_value
        else EVIDENCE_DIR / "t41-browser-release-model"
    ).resolve()
    if release_path.exists():
        raise AcceptanceFailure(
            f"T41 browser release marker already exists: {release_path}"
        )
    confirmation_path_value = os.environ.get("C012_T41_CONFIRM_FILE")
    confirmation_path = Path(
        confirmation_path_value
        if confirmation_path_value
        else EVIDENCE_DIR / "t41-browser-final-confirmation"
    ).resolve()
    if confirmation_path.exists():
        raise AcceptanceFailure(
            f"T41 browser final confirmation marker already exists: {confirmation_path}"
        )
    raw_port = os.environ.get("C012_T41_BACKEND_PORT")
    if raw_port is None:
        requested_port = free_tcp_port()
    else:
        try:
            requested_port = int(raw_port)
        except ValueError as exc:
            raise AcceptanceFailure(
                f"C012_T41_BACKEND_PORT is not an integer: {raw_port!r}"
            ) from exc
        if not 1 <= requested_port <= 65535:
            raise AcceptanceFailure(
                f"C012_T41_BACKEND_PORT is outside the TCP port range: {requested_port}"
            )
    frontend_address = os.environ.get(
        "C012_T41_FRONTEND_URL", "http://127.0.0.1:5174/tasks"
    )
    if not frontend_address.startswith(("http://", "https://")):
        raise AcceptanceFailure(
            f"C012_T41_FRONTEND_URL is not an HTTP address: {frontend_address!r}"
        )

    with tempfile.TemporaryDirectory(
        prefix="c012-ws-slow-page-browser-", dir=str(data_dir)
    ) as runtime_name:
        runtime_dir = Path(runtime_name)
        try:
            with SlowBrowserHTTPStub() as dependency_stub:
                os.environ.update(
                    {
                        "DATABASE_URL": raw_url,
                        "PYTHONUTF8": "1",
                        "DATA_DIR": str(runtime_dir),
                        "VLLM_BASE_URL": dependency_stub.base_url,
                        "COMFY_BASE_URL": dependency_stub.base_url,
                    }
                )
                if "app.main" in sys.modules:
                    raise AcceptanceFailure(
                        "production app was imported before the isolated browser runtime"
                    )
                import uvicorn

                from app.main import app as production_app
                import app.tasks.gen_assets as gen_assets_module

                original_vllm_client = gen_assets_module.VLLMClient
                gen_assets_module.VLLMClient = functools.partial(
                    original_vllm_client,
                    timeout=T41_BROWSER_MANUAL_TIMEOUT_SECONDS,
                )

                gate = RecordingSlowASGISendGate(production_app)
                server_port = requested_port
                server = uvicorn.Server(
                    uvicorn.Config(
                        gate,
                        host="127.0.0.1",
                        port=server_port,
                        log_level="warning",
                        lifespan="on",
                        access_log=False,
                    )
                )
                task_logger = logging.getLogger("app.api.tasks")
                task_logger.addHandler(log_handler)
                server_task = asyncio.create_task(
                    server.serve(), name="c012-browser-production-server"
                )
                base_url = f"http://127.0.0.1:{server_port}"
                health = await wait_for_http(
                    f"{base_url}/api/system/health", timeout=30
                )
                if health.status_code != 200:
                    raise AcceptanceFailure(
                        f"T41 browser production health returned {health.status_code}: "
                        f"{health.body!r}"
                    )
                evidence.add(
                    "production_runtime",
                    pid=os.getpid(),
                    port=server_port,
                    health=health.body,
                    app_module="app.main:app",
                    lifespan=True,
                    queue="production TaskQueue",
                    handler="gen_assets_handler",
                    event_bus="production EventBus",
                    dependency_stub=dependency_stub.base_url,
                    asgi_gate="websocket.send only",
                    frontend_address=frontend_address,
                )

                async with httpx.AsyncClient(
                    timeout=10, trust_env=False
                ) as client:
                    fixture = await slow_page_create_fixture(
                        client,
                        base_url,
                        request_log,
                        task_count=SLOW_PAGE_BROWSER_TASK_COUNT,
                    )
                    style_id = int(fixture["style_id"])
                    project_id = int(fixture["project_id"])
                    episode_ids = [int(value) for value in fixture["episode_ids"]]
                    if len(episode_ids) != SLOW_PAGE_BROWSER_TASK_COUNT:
                        raise AcceptanceFailure(
                            "T41 browser fixture episode count did not match the planned matrix"
                        )

                    for episode_id in episode_ids[:SLOW_PAGE_BROWSER_PRE_TASK_COUNT]:
                        generation_path = (
                            f"/api/episodes/{episode_id}/generate-assets"
                        )
                        status_code, body = await slow_page_http_json(
                            client, "POST", f"{base_url}{generation_path}"
                        )
                        request_entry: dict[str, object] = {
                            "method": "POST",
                            "path": generation_path,
                            "status": status_code,
                            "phase": "pre_browser",
                        }
                        if isinstance(body, Mapping):
                            request_entry["response"] = dict(body)
                        request_log.append(request_entry)
                        if status_code != 202:
                            raise AcceptanceFailure(
                                f"T41 pre-browser generation returned {status_code}: "
                                f"{body!r}"
                            )
                        mapping = require_mapping(body, "T41 pre-browser generation")
                        raw_task_id = mapping.get("task_id")
                        if not isinstance(raw_task_id, int):
                            raise AcceptanceFailure(
                                f"T41 pre-browser task id missing: {body!r}"
                            )
                        task_ids.append(raw_task_id)
                        pre_state = await slow_page_wait_for_terminal(
                            raw_url, [raw_task_id], [episode_id], timeout=30
                        )
                        pre_tasks = pre_state["tasks"]
                        if not isinstance(pre_tasks, list) or len(pre_tasks) != 1:
                            raise AcceptanceFailure(
                                f"T41 pre-browser task state was incomplete: {pre_state!r}"
                            )
                        if pre_tasks[0].get("status") != "done":
                            raise AcceptanceFailure(
                                f"T41 pre-browser task did not finish done: {pre_state!r}"
                            )

                    dependency_stub.server.block_enabled.set()
                    target_episode_id = episode_ids[SLOW_PAGE_BROWSER_PRE_TASK_COUNT]
                    target_path = (
                        f"/api/episodes/{target_episode_id}/generate-assets"
                    )
                    target_status, target_body = await slow_page_http_json(
                        client, "POST", f"{base_url}{target_path}"
                    )
                    target_entry: dict[str, object] = {
                        "method": "POST",
                        "path": target_path,
                        "status": target_status,
                        "phase": "browser_target",
                    }
                    if isinstance(target_body, Mapping):
                        target_entry["response"] = dict(target_body)
                    request_log.append(target_entry)
                    if target_status != 202:
                        raise AcceptanceFailure(
                            f"T41 browser target generation returned {target_status}: "
                            f"{target_body!r}"
                        )
                    target_mapping = require_mapping(
                        target_body, "T41 browser target generation"
                    )
                    raw_target_task_id = target_mapping.get("task_id")
                    if not isinstance(raw_target_task_id, int):
                        raise AcceptanceFailure(
                            f"T41 browser target task id missing: {target_body!r}"
                        )
                    target_task_id = raw_target_task_id
                    task_ids.append(target_task_id)

                    chat_deadline = time.monotonic() + 30
                    while (
                        not dependency_stub.server.chat_started.is_set()
                        and time.monotonic() < chat_deadline
                    ):
                        await asyncio.sleep(0.05)
                    if not dependency_stub.server.chat_started.is_set():
                        raise AcceptanceFailure(
                            "T41 browser target handler did not reach the held model response"
                        )
                    target_state = await slow_page_read_state(
                        raw_url, [target_task_id], [target_episode_id]
                    )
                    target_tasks = target_state["tasks"]
                    if (
                        not isinstance(target_tasks, list)
                        or len(target_tasks) != 1
                        or target_tasks[0].get("status") != "running"
                    ):
                        raise AcceptanceFailure(
                            f"T41 browser target was not running before page interaction: "
                            f"{target_state!r}"
                        )

                    print(
                        json.dumps(
                            {
                                "status": "browser-ready",
                                "browser_address": frontend_address,
                                "backend_base_url": base_url,
                                "task_id": target_task_id,
                                "target_episode_id": target_episode_id,
                                "release_file": str(release_path),
                                "confirmation_file": str(confirmation_path),
                                "instruction": (
                                    "Open the running task detail, then create the release marker; "
                                    "the marker releases only the external model stub. After the "
                                    "reconnected page visibly renders the terminal target row and "
                                    "expanded detail, create the confirmation marker."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    release_deadline = (
                        time.monotonic() + T41_BROWSER_MANUAL_TIMEOUT_SECONDS
                    )
                    while not release_path.is_file():
                        if server_task.done():
                            raise AcceptanceFailure(
                                "T41 production server exited before browser release marker"
                            )
                        if time.monotonic() >= release_deadline:
                            raise AcceptanceFailure(
                                f"T41 browser release marker was not observed: {release_path}"
                            )
                        await asyncio.sleep(0.1)

                    dependency_stub.server.chat_release.set()
                    for episode_id in episode_ids[
                        SLOW_PAGE_BROWSER_PRE_TASK_COUNT + 1 :
                    ]:
                        generation_path = (
                            f"/api/episodes/{episode_id}/generate-assets"
                        )
                        status_code, body = await slow_page_http_json(
                            client, "POST", f"{base_url}{generation_path}"
                        )
                        request_entry = {
                            "method": "POST",
                            "path": generation_path,
                            "status": status_code,
                            "phase": "post_release",
                        }
                        if isinstance(body, Mapping):
                            request_entry["response"] = dict(body)
                        request_log.append(request_entry)
                        if status_code != 202:
                            raise AcceptanceFailure(
                                f"T41 post-release generation returned {status_code}: "
                                f"{body!r}"
                            )
                        mapping = require_mapping(body, "T41 post-release generation")
                        raw_task_id = mapping.get("task_id")
                        if not isinstance(raw_task_id, int):
                            raise AcceptanceFailure(
                                f"T41 post-release task id missing: {body!r}"
                            )
                        task_ids.append(raw_task_id)

                    final_state = await slow_page_wait_for_terminal(
                        raw_url, task_ids, episode_ids, timeout=120
                    )
                    task_rows = final_state["tasks"]
                    if not isinstance(task_rows, list) or any(
                        not isinstance(row, Mapping)
                        or row.get("status") != "done"
                        or row.get("error_msg") is not None
                        for row in task_rows
                    ):
                        raise AcceptanceFailure(
                            f"T41 production handlers did not all finish done: "
                            f"{task_rows!r}"
                        )

                    try:
                        await asyncio.wait_for(
                            gate.send_cancelled.wait(), timeout=40
                        )
                    except asyncio.TimeoutError as exc:
                        raise AcceptanceFailure(
                            "T41 browser WebSocket did not cancel the held send after overflow"
                        ) from exc
                    try:
                        await asyncio.wait_for(
                            asyncio.sleep(0), timeout=0.1
                        )
                    except asyncio.TimeoutError:
                        pass

                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        list100 = [
                            request
                            for request in gate.http_requests
                            if request.get("method") == "GET"
                            and request.get("path") == "/api/tasks"
                            and request.get("query_string") == "limit=100"
                            and request.get("status") == 200
                        ]
                        detail_reads = [
                            request
                            for request in gate.http_requests
                            if request.get("method") == "GET"
                            and request.get("path")
                            == f"/api/tasks/{target_task_id}"
                            and request.get("status") == 200
                        ]
                        if len(list100) >= 2 and len(detail_reads) >= 2:
                            break
                        await asyncio.sleep(0.1)
                    list100 = [
                        request
                        for request in gate.http_requests
                        if request.get("method") == "GET"
                        and request.get("path") == "/api/tasks"
                        and request.get("query_string") == "limit=100"
                        and request.get("status") == 200
                    ]
                    detail_reads = [
                        request
                        for request in gate.http_requests
                        if request.get("method") == "GET"
                        and request.get("path") == f"/api/tasks/{target_task_id}"
                        and request.get("status") == 200
                    ]
                    if len(list100) < 2 or len(detail_reads) < 2:
                        raise AcceptanceFailure(
                            "T41 browser did not perform the second limit=100 list and target detail reads: "
                            f"list100={list100!r} detail={detail_reads!r}"
                        )

                    generation_posts = [
                        request
                        for request in gate.http_requests
                        if request.get("method") == "POST"
                        and isinstance(request.get("path"), str)
                        and request["path"].endswith("/generate-assets")
                    ]
                    cancel_posts = [
                        request
                        for request in gate.http_requests
                        if request.get("method") == "POST"
                        and isinstance(request.get("path"), str)
                        and request["path"].endswith("/cancel")
                    ]
                    if len(generation_posts) != len(task_ids):
                        raise AcceptanceFailure(
                            f"T41 generation POST count changed during browser reconnect: "
                            f"expected={len(task_ids)} actual={len(generation_posts)}"
                        )
                    if cancel_posts:
                        raise AcceptanceFailure(
                            f"T41 browser emitted cancel POSTs: {cancel_posts!r}"
                        )
                    second_ws = (
                        gate.websocket_connections[1]
                        if len(gate.websocket_connections) >= 2
                        else None
                    )
                    if second_ws is None:
                        raise AcceptanceFailure(
                            f"T41 browser did not establish a reconnecting WebSocket: "
                            f"{gate.websocket_connections!r}"
                        )
                    if int(second_ws["sequence"]) >= int(list100[1]["sequence"]):
                        raise AcceptanceFailure(
                            "T41 reconnect list GET was not socket-first"
                        )
                    target_detail = detail_reads[-1]
                    if target_detail.get("status") != 200:
                        raise AcceptanceFailure(
                            f"T41 final target detail read was not HTTP 200: {target_detail!r}"
                        )
                    terminal_tasks = final_state.get("tasks")
                    terminal_target = next(
                        (
                            task
                            for task in terminal_tasks
                            if isinstance(task, Mapping)
                            and task.get("id") == target_task_id
                        ),
                        None,
                    ) if isinstance(terminal_tasks, list) else None
                    if not isinstance(terminal_target, Mapping):
                        raise AcceptanceFailure(
                            f"T41 final target task was not in terminal DB state: {final_state!r}"
                        )
                    print(
                        json.dumps(
                            {
                                "status": "browser-final-confirmation-required",
                                "browser_address": frontend_address,
                                "task_id": target_task_id,
                                "confirmation_file": str(confirmation_path),
                                "expected_terminal_detail": {
                                    key: terminal_target.get(key)
                                    for key in (
                                        "status",
                                        "progress",
                                        "error_msg",
                                        "finished_at",
                                    )
                                },
                                "instruction": (
                                    "Do not submit a mutation. Confirm the target row and its "
                                    "expanded terminal detail are visibly rendered, then create "
                                    "the confirmation file."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    confirmation_deadline = (
                        time.monotonic() + T41_BROWSER_MANUAL_TIMEOUT_SECONDS
                    )
                    while not confirmation_path.is_file():
                        if server_task.done():
                            raise AcceptanceFailure(
                                "T41 production server exited before browser final confirmation"
                            )
                        if time.monotonic() >= confirmation_deadline:
                            raise AcceptanceFailure(
                                "T41 browser final confirmation marker was not observed: "
                                f"{confirmation_path}"
                            )
                        await asyncio.sleep(0.1)
                    evidence.add(
                        "browser_final_confirmation",
                        confirmation_file=str(confirmation_path),
                        marker_size=confirmation_path.stat().st_size,
                        target_task= {
                            key: terminal_target.get(key)
                            for key in (
                                "id",
                                "status",
                                "progress",
                                "error_msg",
                                "finished_at",
                            )
                        },
                    )
                    evidence.add(
                        "browser_ready_and_reconnect",
                        browser_address=frontend_address,
                        websocket_uri=f"ws://127.0.0.1:{server_port}/ws/tasks",
                        target_task_id=target_task_id,
                        target_episode_id=target_episode_id,
                        release_file=str(release_path),
                        target_before_release=target_state,
                        websocket_connections=gate.websocket_connections,
                        first_gated_message=gate.first_message,
                        send_cancelled=gate.send_cancelled.is_set(),
                        overflow_logs=[
                            message
                            for message in log_handler.messages
                            if "subscription_overflow" in message
                        ],
                        task_count=len(task_ids),
                        event_lower_bound=(
                            SLOW_PAGE_BROWSER_POST_TASK_COUNT * 3 + 1
                        ),
                        websocket_close_code=1013,
                        list_limit_100_reads=list100,
                        target_detail_reads=detail_reads,
                        http_trace=gate.http_requests,
                        generation_post_count=len(generation_posts),
                        cancel_post_count=len(cancel_posts),
                    )
        finally:
            if gate is not None:
                gate.release.set()
            if server is not None and server_task is not None:
                shutdown_result = await stop_slow_page_server(
                    server, server_task
                )
                evidence.add(
                    "production_process_shutdown",
                    **shutdown_result,
                    process="in-process uvicorn server",
                    port=server_port,
                )
            if task_logger is not None:
                task_logger.removeHandler(log_handler)
            if gen_assets_module is not None and original_vllm_client is not None:
                gen_assets_module.VLLMClient = original_vllm_client
            if request_log:
                evidence.add(
                    "production_request_log",
                    requests=request_log,
                    count=len(request_log),
                )
            if final_state is not None:
                evidence.add("terminal_database_readback", **final_state)
            if style_id is not None or project_id is not None or task_ids:
                cleanup_result = await slow_page_cleanup(
                    raw_url,
                    style_id,
                    project_id,
                    episode_ids,
                    task_ids,
                )
                evidence.add(
                    "task_fixture_cleanup",
                    style_id=style_id,
                    project_id=project_id,
                    episode_count=len(episode_ids),
                    task_count=len(task_ids),
                    result=cleanup_result,
                )

        if shutdown_result is None or shutdown_result.get("timed_out"):
            raise AcceptanceFailure(
                f"T41 browser production server did not stop cleanly: {shutdown_result!r}"
            )
        if shutdown_result.get("exception") is not None:
            raise AcceptanceFailure(
                f"T41 browser production server raised during shutdown: "
                f"{shutdown_result!r}"
            )
        listeners = observe_windows_listeners([server_port]) if server_port else {}
        evidence.add("owned_listener_cleanup", **listeners)
        if listeners.get("listeners"):
            raise AcceptanceFailure(
                f"T41 browser owned port still has listeners: {listeners!r}"
            )

    if runtime_dir.exists():
        raise AcceptanceFailure("T41 browser runtime directory was not released")
    evidence.add(
        "owned_resource_cleanup",
        runtime_directory_exists=runtime_dir.exists(),
        dependency_stub_stopped=True,
        production_server_stopped=True,
        database_connections_closed=True,
        cleanup=cleanup_result,
        release_marker_exists=release_path.exists(),
    )


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
        task_targets = [
            int(fixture["edit_episode_id"]),
            int(fixture["generation_episode_id"]),
            int(fixture["success_clip_id"]),
            *[int(asset_id) for asset_id in fixture["asset_ids"]],
        ]
        await connection.execute(
            "DELETE FROM tasks WHERE target_id = ANY($1::integer[])",
            task_targets,
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


async def cascade_cache_seed_current_image(
    raw_url: str, fixture: Mapping[str, object], runtime_dir: Path
) -> None:
    from app.services.asset_files import asset_image_relative_path

    asset_id = int(fixture["asset_ids"][0])
    project_id = int(fixture["project_id"])
    image_bytes = controlled_png_bytes()
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    try:
        async with connection.transaction():
            image_id = await connection.fetchval(
                "INSERT INTO asset_images "
                "(asset_id, file_path, sha256, source, is_current) "
                "VALUES ($1, 'pending', $2, 'uploaded', true) RETURNING id",
                asset_id,
                hashlib.sha256(image_bytes).hexdigest(),
            )
            relative_path = asset_image_relative_path(
                project_id, asset_id, int(image_id), "png"
            )
            image_path = runtime_dir / relative_path
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(image_bytes)
            await connection.execute(
                "UPDATE asset_images SET file_path = $1 WHERE id = $2",
                relative_path.as_posix(),
                image_id,
            )
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


def _cascade_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _cascade_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_cascade_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise AcceptanceFailure(
        f"cascade cache readback encountered a non-JSON database value: {type(value).__name__}"
    )


def _cascade_task_payload(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        raise AcceptanceFailure(
            f"cascade cache task payload is not JSON text: {type(value).__name__}"
        )
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AcceptanceFailure("cascade cache task payload is invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise AcceptanceFailure("cascade cache task payload is not an object")
    return decoded


def _cascade_file_observation(runtime_dir: Path, relative_path: object) -> dict[str, object]:
    if not isinstance(relative_path, str) or not relative_path:
        raise AcceptanceFailure(f"cascade cache file path is invalid: {relative_path!r}")
    path = (runtime_dir / Path(relative_path)).resolve()
    root = runtime_dir.resolve()
    if path != root and root not in path.parents:
        raise AcceptanceFailure(f"cascade cache file path escaped fixture: {path}")
    exists = path.is_file()
    content = path.read_bytes() if exists else b""
    return {
        "path": str(path),
        "relative_path": relative_path,
        "exists": exists,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest() if exists else None,
    }


async def cascade_cache_read_state(
    raw_url: str,
    fixture: Mapping[str, object],
    runtime_dir: Path,
) -> dict[str, object]:
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    episode_ids = [
        int(fixture["edit_episode_id"]),
        int(fixture["generation_episode_id"]),
    ]
    asset_ids = [int(asset_id) for asset_id in fixture["asset_ids"]]
    clip_ids = [
        int(fixture["clip_id"]),
        int(fixture["success_clip_id"]),
    ]
    target_ids = [*episode_ids, *asset_ids, *clip_ids]
    try:
        style_row = await connection.fetchrow(
            "SELECT id, name, prompt_fragment FROM styles WHERE id = $1",
            int(fixture["style_id"]),
        )
        template_rows = await connection.fetch(
            "SELECT key, content FROM prompt_templates ORDER BY key"
        )
        episode_rows = await connection.fetch(
            "SELECT id, seq, script_text, script_revision, "
            "assets_generated_script_revision, shots_generated_script_revision "
            "FROM episodes WHERE id = ANY($1::integer[]) ORDER BY id",
            episode_ids,
        )
        asset_rows = await connection.fetch(
            "SELECT id, type, name, description, source, revision, "
            "image_prompt_cache, image_prompt_hash "
            "FROM assets WHERE project_id = $1 ORDER BY id",
            int(fixture["project_id"]),
        )
        image_rows = await connection.fetch(
            "SELECT id, asset_id, file_path, sha256, seed, source, is_current, "
            "built_prompt, input_hash, input_snapshot, user_note "
            "FROM asset_images WHERE asset_id = ANY($1::integer[]) ORDER BY id",
            asset_ids,
        )
        shot_rows = await connection.fetch(
            "SELECT id, episode_id, order_index, duration_est, shot_type, camera, "
            "description, dialogue, status, revision "
            "FROM shots WHERE episode_id = ANY($1::integer[]) ORDER BY id",
            episode_ids,
        )
        shot_ids = [int(row["id"]) for row in shot_rows]
        shot_asset_rows = await connection.fetch(
            "SELECT shot_id, asset_id FROM shot_assets "
            "WHERE shot_id = ANY($1::integer[]) ORDER BY shot_id, asset_id",
            shot_ids,
        )
        clip_rows = await connection.fetch(
            "SELECT id, episode_id, generation_mode, user_note, requested_duration, "
            "prompt_cache, prompt_input_hash, generation_state, freshness, revision "
            "FROM clips WHERE id = ANY($1::integer[]) ORDER BY id",
            clip_ids,
        )
        clip_shot_rows = await connection.fetch(
            "SELECT clip_id, shot_id, position FROM clip_shots "
            "WHERE clip_id = ANY($1::integer[]) ORDER BY clip_id, position",
            clip_ids,
        )
        slot_rows = await connection.fetch(
            "SELECT id, clip_id, slot_no, asset_id, asset_name_snapshot, "
            "asset_type_snapshot, override_image_path, override_sha256, enabled "
            "FROM clip_ref_slots WHERE clip_id = ANY($1::integer[]) "
            "ORDER BY clip_id, slot_no, id",
            clip_ids,
        )
        video_rows = await connection.fetch(
            "SELECT id, clip_id, file_path, sha256, seed, requested_duration, "
            "actual_duration, is_current, built_prompt, input_hash, input_snapshot "
            "FROM clip_videos WHERE clip_id = ANY($1::integer[]) ORDER BY id",
            clip_ids,
        )
        task_rows = await connection.fetch(
            "SELECT id, type, target_id, request_id, status, progress, error_msg, payload "
            "FROM tasks WHERE target_id = ANY($1::integer[]) ORDER BY id",
            target_ids,
        )
    finally:
        await connection.close()

    images = [
        {
            "id": int(row["id"]),
            "asset_id": int(row["asset_id"]),
            "file_path": row["file_path"],
            "sha256": row["sha256"],
            "seed": row["seed"],
            "source": row["source"],
            "is_current": row["is_current"],
            "built_prompt": row["built_prompt"],
            "input_hash": row["input_hash"],
            "input_snapshot": _cascade_json_value(row["input_snapshot"]),
            "user_note": row["user_note"],
        }
        for row in image_rows
    ]
    videos = [
        {
            "id": int(row["id"]),
            "clip_id": int(row["clip_id"]),
            "file_path": row["file_path"],
            "sha256": row["sha256"],
            "seed": row["seed"],
            "requested_duration": row["requested_duration"],
            "actual_duration": row["actual_duration"],
            "is_current": row["is_current"],
            "built_prompt": row["built_prompt"],
            "input_hash": row["input_hash"],
            "input_snapshot": _cascade_json_value(row["input_snapshot"]),
        }
        for row in video_rows
    ]
    return {
        "style": None
        if style_row is None
        else {
            "id": int(style_row["id"]),
            "name": style_row["name"],
            "prompt_fragment": style_row["prompt_fragment"],
        },
        "templates": {
            row["key"]: row["content"] for row in template_rows
        },
        "episodes": [
            {
                "id": int(row["id"]),
                "seq": row["seq"],
                "script_text": row["script_text"],
                "script_revision": row["script_revision"],
                "assets_generated_script_revision": row[
                    "assets_generated_script_revision"
                ],
                "shots_generated_script_revision": row[
                    "shots_generated_script_revision"
                ],
            }
            for row in episode_rows
        ],
        "assets": [
            {
                "id": int(row["id"]),
                "type": row["type"],
                "name": row["name"],
                "description": row["description"],
                "source": row["source"],
                "revision": row["revision"],
                "image_prompt_cache": row["image_prompt_cache"],
                "image_prompt_hash": row["image_prompt_hash"],
            }
            for row in asset_rows
        ],
        "asset_images": images,
        "shots": [
            {
                "id": int(row["id"]),
                "episode_id": int(row["episode_id"]),
                "order_index": row["order_index"],
                "duration_est": row["duration_est"],
                "shot_type": row["shot_type"],
                "camera": row["camera"],
                "description": row["description"],
                "dialogue": row["dialogue"],
                "status": row["status"],
                "revision": row["revision"],
            }
            for row in shot_rows
        ],
        "shot_assets": [
            {"shot_id": int(row["shot_id"]), "asset_id": int(row["asset_id"])}
            for row in shot_asset_rows
        ],
        "clips": [
            {
                "id": int(row["id"]),
                "episode_id": int(row["episode_id"]),
                "generation_mode": row["generation_mode"],
                "user_note": row["user_note"],
                "requested_duration": row["requested_duration"],
                "prompt_cache": row["prompt_cache"],
                "prompt_input_hash": row["prompt_input_hash"],
                "generation_state": row["generation_state"],
                "freshness": row["freshness"],
                "revision": row["revision"],
            }
            for row in clip_rows
        ],
        "clip_shots": [
            {
                "clip_id": int(row["clip_id"]),
                "shot_id": int(row["shot_id"]),
                "position": row["position"],
            }
            for row in clip_shot_rows
        ],
        "clip_ref_slots": [
            {
                "id": int(row["id"]),
                "clip_id": int(row["clip_id"]),
                "slot_no": row["slot_no"],
                "asset_id": row["asset_id"],
                "asset_name_snapshot": row["asset_name_snapshot"],
                "asset_type_snapshot": row["asset_type_snapshot"],
                "override_image_path": row["override_image_path"],
                "override_sha256": row["override_sha256"],
                "enabled": row["enabled"],
            }
            for row in slot_rows
        ],
        "clip_videos": videos,
        "tasks": [
            {
                "id": int(row["id"]),
                "type": row["type"],
                "target_id": int(row["target_id"]),
                "request_id": row["request_id"],
                "status": row["status"],
                "progress": row["progress"],
                "error_msg": row["error_msg"],
                "payload": _cascade_task_payload(row["payload"]),
            }
            for row in task_rows
        ],
        "files": [
            *[
                _cascade_file_observation(runtime_dir, row["file_path"])
                for row in images
            ],
            *[
                _cascade_file_observation(runtime_dir, row["file_path"])
                for row in videos
            ],
        ],
    }


def cascade_stub_counts(stub: ControlledComfyStub) -> dict[str, object]:
    by_schema: dict[str, int] = {}
    by_route: dict[str, int] = {}
    for observation in stub.chat_observations:
        key = str(observation.get("schema_name"))
        by_schema[key] = by_schema.get(key, 0) + 1
    for observation in stub.http_observations:
        key = f"{observation['method']} {observation['path']}"
        by_route[key] = by_route.get(key, 0) + 1
    return {
        "chat_total": len(stub.chat_observations),
        "chat_by_schema": by_schema,
        "http_total": len(stub.http_observations),
        "http_by_route": by_route,
    }


def _cascade_cache_task_record(
    state: Mapping[str, object], task_id: int
) -> Mapping[str, object]:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        raise AcceptanceFailure("cascade cache task readback is not a list")
    for task in tasks:
        if isinstance(task, Mapping) and task.get("id") == task_id:
            return task
    raise AcceptanceFailure(f"cascade cache task {task_id} missing from database")


async def cascade_cache_run_task(
    client: httpx.AsyncClient,
    base_url: str,
    raw_url: str,
    fixture: Mapping[str, object],
    runtime_dir: Path,
    stub: ControlledComfyStub,
    evidence: RunEvidence,
    *,
    operation: str,
    path: str,
    payload: object,
) -> tuple[int, dict[str, object], dict[str, object]]:
    before_chat = len(stub.chat_observations)
    before_http = len(stub.http_observations)
    observation = await cascade_http_json(
        client, "POST", f"{base_url}{path}", payload
    )
    if observation.status_code != 202:
        raise AcceptanceFailure(
            f"cascade cache {operation} enqueue returned "
            f"{observation.status_code}: {observation.body!r}"
        )
    body = require_mapping(observation.body, f"cascade cache {operation} enqueue")
    task_id = body.get("task_id")
    if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
        raise AcceptanceFailure(
            f"cascade cache {operation} returned an invalid task id: {body!r}"
        )
    try:
        task = await cascade_wait_task(client, base_url, task_id)
    except httpx.ReadTimeout as exc:
        timeout_state = await cascade_cache_read_state(
            raw_url, fixture, runtime_dir
        )
        evidence.add(
            "cache_task_timeout",
            operation=operation,
            path=path,
            task_id=task_id,
            error=repr(exc),
            state=timeout_state,
            external={
                "chat_delta": list(stub.chat_observations[before_chat:]),
                "http_delta": list(stub.http_observations[before_http:]),
                "model_errors": list(stub.model_errors),
                "counts_after": cascade_stub_counts(stub),
            },
        )
        raise AcceptanceFailure(
            f"cascade cache {operation} task polling timed out: task_id={task_id}"
        ) from exc
    if task.get("status") != "done":
        evidence.add(
            "cache_task_failure",
            operation=operation,
            path=path,
            request_payload=payload,
            api_task=task,
            external={
                "chat_delta": list(stub.chat_observations[before_chat:]),
                "http_delta": list(stub.http_observations[before_http:]),
                "model_errors": list(stub.model_errors),
                "counts_after": cascade_stub_counts(stub),
            },
        )
        raise AcceptanceFailure(
            f"cascade cache {operation} task did not complete: {task!r}"
        )
    state = await cascade_cache_read_state(raw_url, fixture, runtime_dir)
    task_record = _cascade_cache_task_record(state, task_id)
    if task_record.get("status") != "done":
        raise AcceptanceFailure(
            f"cascade cache {operation} database task is not done: {task_record!r}"
        )
    evidence.add(
        "cache_task",
        operation=operation,
        path=path,
        request_payload=payload,
        enqueue={"status": observation.status_code, "body": observation.body},
        api_task=task,
        database_task=task_record,
        state=state,
        external={
            "chat_delta": list(stub.chat_observations[before_chat:]),
            "http_delta": list(stub.http_observations[before_http:]),
            "counts_after": cascade_stub_counts(stub),
        },
    )
    return task_id, dict(task_record), state


def cascade_cache_rows_without_tasks(state: Mapping[str, object]) -> dict[str, object]:
    return {
        key: state[key]
        for key in (
            "style",
            "templates",
            "episodes",
            "assets",
            "asset_images",
            "shots",
            "shot_assets",
            "clips",
            "clip_shots",
            "clip_ref_slots",
            "clip_videos",
            "files",
        )
    }


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
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    def drain(stream: Any, buffer: bytearray) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            buffer.extend(chunk)

    stdout_thread = threading.Thread(
        target=drain,
        args=(process.stdout, stdout_buffer),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=drain,
        args=(process.stderr, stderr_buffer),
        daemon=True,
    )
    setattr(
        process,
        "_c012_drain_state",
        (stdout_buffer, stderr_buffer, stdout_thread, stderr_thread),
    )
    stdout_thread.start()
    stderr_thread.start()
    return process, port


async def command_cascade_cache(
    _arguments: argparse.Namespace,
    evidence: RunEvidence,
) -> None:
    raw_url, data_dir, identity = explicit_runtime()
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

    with tempfile.TemporaryDirectory(
        prefix="c012-cascade-cache-", dir=str(data_dir)
    ) as runtime_name:
        runtime_dir = Path(runtime_name)
        fixture = await cascade_seed_fixture(raw_url, runtime_dir)
        await cascade_cache_seed_current_image(raw_url, fixture, runtime_dir)
        process: subprocess.Popen[bytes] | None = None
        stopped: ChildResult | None = None
        try:
            async with ControlledComfyStub(response_mode="t27-browser") as stub:
                process, port = start_backend_process(
                    raw_url,
                    runtime_dir,
                    stub,
                    comfy_dependency_stub=stub,
                )
                base_url = f"http://127.0.0.1:{port}"
                health = await wait_for_http(f"{base_url}/api/system/health")
                if health.status_code != 200:
                    raise AcceptanceFailure(
                        f"cascade cache backend health returned {health.status_code}"
                    )
                evidence.add(
                    "production_process",
                    pid=process.pid,
                    port=port,
                    health=health.body,
                    dependency_stub=stub.base_url,
                )
                async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                    baseline_templates = {
                        "script2assets": (
                            "existing={{existing_assets}}|style={{style}}|"
                            "script={{script}}|cache-baseline"
                        ),
                        "script2shots": (
                            "assets={{assets}}|style={{style}}|"
                            "script={{script}}|cache-baseline"
                        ),
                        "zimage": (
                            "asset={{asset}}|style={{style}}|"
                            "user={{user_note}}|cache-baseline"
                        ),
                        "minimaxh3": (
                            "shots={{shots}}|references={{references}}|"
                            "style={{style}}|requested_duration={{requested_duration}}|"
                            "user_note={{user_note}}|cache-baseline"
                        ),
                    }
                    baseline_changes: dict[str, object] = {}
                    for key, content in baseline_templates.items():
                        baseline_path = f"{base_url}/api/prompt-templates/{key}"
                        baseline = await cascade_http_json(
                            client,
                            "PATCH",
                            baseline_path,
                            {"content": content},
                        )
                        if baseline.status_code != 200:
                            raise AcceptanceFailure(
                                f"cascade cache baseline template {key} PATCH returned "
                                f"{baseline.status_code}: {baseline.body!r}"
                            )
                        baseline_changes[key] = {
                            "path": f"/api/prompt-templates/{key}",
                            "status": baseline.status_code,
                            "body": baseline.body,
                        }
                    evidence.add(
                        "settings_baseline_install",
                        templates=baseline_changes,
                    )
                    before_state = await cascade_cache_read_state(
                        raw_url, fixture, runtime_dir
                    )
                    evidence.add("cache_state", phase="before", state=before_state)

                    image_path = f"/api/assets/{fixture['asset_ids'][0]}/generate-image"
                    image_first_id, image_first_task, image_first_state = (
                        await cascade_cache_run_task(
                            client,
                            base_url,
                            raw_url,
                            fixture,
                            runtime_dir,
                            stub,
                            evidence,
                            operation="image_miss_initial",
                            path=image_path,
                            payload={},
                        )
                    )
                    image_hit_id, image_hit_task, image_hit_state = (
                        await cascade_cache_run_task(
                            client,
                            base_url,
                            raw_url,
                            fixture,
                            runtime_dir,
                            stub,
                            evidence,
                            operation="image_hit",
                            path=image_path,
                            payload={},
                        )
                    )

                    video_path = (
                        f"/api/clips/{fixture['success_clip_id']}/generate-video"
                    )
                    video_first_id, video_first_task, video_first_state = (
                        await cascade_cache_run_task(
                            client,
                            base_url,
                            raw_url,
                            fixture,
                            runtime_dir,
                            stub,
                            evidence,
                            operation="video_miss_initial",
                            path=video_path,
                            payload={},
                        )
                    )
                    video_hit_id, video_hit_task, video_hit_state = (
                        await cascade_cache_run_task(
                            client,
                            base_url,
                            raw_url,
                            fixture,
                            runtime_dir,
                            stub,
                            evidence,
                            operation="video_hit",
                            path=video_path,
                            payload={},
                        )
                    )
                    pre_change_state = await cascade_cache_read_state(
                        raw_url, fixture, runtime_dir
                    )
                    evidence.add(
                        "cache_state",
                        phase="after_initial_miss_and_hit",
                        state=pre_change_state,
                    )

                    style_change = await cascade_http_json(
                        client,
                        "PATCH",
                        f"{base_url}/api/styles/{fixture['style_id']}",
                        {"prompt_fragment": "cache cascade style changed"},
                    )
                    if style_change.status_code != 200:
                        raise AcceptanceFailure(
                            f"cascade cache style PATCH returned "
                            f"{style_change.status_code}: {style_change.body!r}"
                        )
                    changed_templates = {
                        "script2assets": (
                            "existing={{existing_assets}}|style={{style}}|"
                            "script={{script}}|cache-change"
                        ),
                        "script2shots": (
                            "assets={{assets}}|style={{style}}|"
                            "script={{script}}|cache-change"
                        ),
                        "zimage": (
                            "asset={{asset}}|style={{style}}|"
                            "user={{user_note}}|cache-change"
                        ),
                        "minimaxh3": (
                            "shots={{shots}}|references={{references}}|"
                            "style={{style}}|requested_duration={{requested_duration}}|"
                            "user_note={{user_note}}|cache-change"
                        ),
                    }
                    template_changes: dict[str, object] = {}
                    for key, content in changed_templates.items():
                        template_path = f"{base_url}/api/prompt-templates/{key}"
                        template_change = await cascade_http_json(
                            client,
                            "PATCH",
                            template_path,
                            {"content": content},
                        )
                        if template_change.status_code != 200:
                            raise AcceptanceFailure(
                                f"cascade cache template {key} PATCH returned "
                                f"{template_change.status_code}: {template_change.body!r}"
                            )
                        template_changes[key] = {
                            "path": f"/api/prompt-templates/{key}",
                            "status": template_change.status_code,
                            "body": template_change.body,
                        }
                    changed_state = await cascade_cache_read_state(
                        raw_url, fixture, runtime_dir
                    )
                    pre_without_tasks = cascade_cache_rows_without_tasks(
                        pre_change_state
                    )
                    changed_without_tasks = cascade_cache_rows_without_tasks(
                        changed_state
                    )
                    for key in (
                        "episodes",
                        "assets",
                        "asset_images",
                        "shots",
                        "shot_assets",
                        "clips",
                        "clip_shots",
                        "clip_ref_slots",
                        "clip_videos",
                        "files",
                    ):
                        if changed_without_tasks[key] != pre_without_tasks[key]:
                            raise AcceptanceFailure(
                                f"style/template edit changed downstream {key}"
                            )
                    evidence.add(
                        "settings_mutation",
                        style={
                            "path": f"/api/styles/{fixture['style_id']}",
                            "status": style_change.status_code,
                            "body": style_change.body,
                        },
                        templates=template_changes,
                        state=changed_state,
                    )

                    image_miss_id, image_miss_task, image_miss_state = (
                        await cascade_cache_run_task(
                            client,
                            base_url,
                            raw_url,
                            fixture,
                            runtime_dir,
                            stub,
                            evidence,
                            operation="image_miss_after_style_template_change",
                            path=image_path,
                            payload={},
                        )
                    )
                    video_miss_id, video_miss_task, video_miss_state = (
                        await cascade_cache_run_task(
                            client,
                            base_url,
                            raw_url,
                            fixture,
                            runtime_dir,
                            stub,
                            evidence,
                            operation="video_miss_after_style_template_change",
                            path=video_path,
                            payload={},
                        )
                    )
                    assets_path = (
                        f"/api/episodes/{fixture['generation_episode_id']}/generate-assets"
                    )
                    assets_id, assets_task, assets_state = await cascade_cache_run_task(
                        client,
                        base_url,
                        raw_url,
                        fixture,
                        runtime_dir,
                        stub,
                        evidence,
                        operation="extract_assets_after_template_change",
                        path=assets_path,
                        payload=None,
                    )
                    impact_path = (
                        f"/api/episodes/{fixture['generation_episode_id']}"
                        "/generate-shots/impact"
                    )
                    impact = await cascade_http_json(
                        client, "POST", f"{base_url}{impact_path}", None
                    )
                    if impact.status_code != 200:
                        raise AcceptanceFailure(
                            f"cascade cache shots impact returned "
                            f"{impact.status_code}: {impact.body!r}"
                        )
                    impact_body = require_mapping(impact.body, "cascade cache shots impact")
                    if impact_body.get("confirm_token") is not None:
                        raise AcceptanceFailure(
                            f"cascade cache fixture unexpectedly requires a shots token: {impact.body!r}"
                        )
                    shots_path = (
                        f"/api/episodes/{fixture['generation_episode_id']}/generate-shots"
                    )
                    shots_id, shots_task, shots_state = await cascade_cache_run_task(
                        client,
                        base_url,
                        raw_url,
                        fixture,
                        runtime_dir,
                        stub,
                        evidence,
                        operation="extract_shots_after_template_change",
                        path=shots_path,
                        payload={"confirm_token": None},
                    )
                    final_state = await cascade_cache_read_state(
                        raw_url, fixture, runtime_dir
                    )
                    evidence.add(
                        "cache_state",
                        phase="after_template_mismatch_handlers",
                        state=final_state,
                    )

                    first_image_record = _cascade_cache_task_record(
                        image_first_state, image_first_id
                    )
                    hit_image_record = _cascade_cache_task_record(
                        image_hit_state, image_hit_id
                    )
                    changed_image_record = _cascade_cache_task_record(
                        image_miss_state, image_miss_id
                    )
                    first_video_record = _cascade_cache_task_record(
                        video_first_state, video_first_id
                    )
                    hit_video_record = _cascade_cache_task_record(
                        video_hit_state, video_hit_id
                    )
                    changed_video_record = _cascade_cache_task_record(
                        video_miss_state, video_miss_id
                    )
                    for label, record in (
                        ("image-first", first_image_record),
                        ("image-hit", hit_image_record),
                        ("image-changed", changed_image_record),
                        ("video-first", first_video_record),
                        ("video-hit", hit_video_record),
                        ("video-changed", changed_video_record),
                    ):
                        if record["status"] != "done":
                            raise AcceptanceFailure(
                                f"cascade cache {label} task was not done: {record!r}"
                            )
                    first_image_snapshot = first_image_record["payload"]["input_snapshot"]
                    hit_image_snapshot = hit_image_record["payload"]["input_snapshot"]
                    changed_image_snapshot = changed_image_record["payload"]["input_snapshot"]
                    first_video_snapshot = first_video_record["payload"]["input_snapshot"]
                    hit_video_snapshot = hit_video_record["payload"]["input_snapshot"]
                    changed_video_snapshot = changed_video_record["payload"]["input_snapshot"]
                    if (
                        first_image_snapshot["cached_prompt"] is not None
                        or not isinstance(hit_image_snapshot["cached_prompt"], str)
                        or changed_image_snapshot["cached_prompt"] is not None
                        or first_image_record["payload"]["input_hash"]
                        != hit_image_record["payload"]["input_hash"]
                        or first_image_record["payload"]["input_hash"]
                        == changed_image_record["payload"]["input_hash"]
                    ):
                        raise AcceptanceFailure(
                            "zimage cache miss/hit/mismatch payload evidence is inconsistent"
                        )
                    if (
                        first_video_snapshot["cached_prompt"] is not None
                        or not isinstance(hit_video_snapshot["cached_prompt"], str)
                        or changed_video_snapshot["cached_prompt"] is not None
                        or first_video_record["payload"]["input_hash"]
                        != hit_video_record["payload"]["input_hash"]
                        or first_video_record["payload"]["input_hash"]
                        == changed_video_record["payload"]["input_hash"]
                    ):
                        raise AcceptanceFailure(
                            "minimaxh3 cache miss/hit/mismatch payload evidence is inconsistent"
                        )

                    changed_assets_record = _cascade_cache_task_record(
                        assets_state, assets_id
                    )
                    changed_shots_record = _cascade_cache_task_record(
                        shots_state, shots_id
                    )
                    for label, record, template_key in (
                        ("script2assets", changed_assets_record, "script2assets"),
                        ("script2shots", changed_shots_record, "script2shots"),
                    ):
                        payload_record = record["payload"]
                        if payload_record["input_hash"] is not None:
                            raise AcceptanceFailure(
                                f"{label} task input_hash is not null: {record!r}"
                            )
                        snapshot = payload_record["input_snapshot"]
                        if snapshot["template_content"] != changed_templates[template_key]:
                            raise AcceptanceFailure(
                                f"{label} task did not freeze the changed template"
                            )
                        if snapshot["style"] != "cache cascade style changed":
                            raise AcceptanceFailure(
                                f"{label} task did not freeze the changed style"
                            )

                    counts = cascade_stub_counts(stub)
                    expected_schema_counts = {
                        "zimage": 2,
                        "minimaxh3": 2,
                        "script2assets": 1,
                        "script2shots": 1,
                    }
                    if counts["chat_by_schema"] != expected_schema_counts:
                        raise AcceptanceFailure(
                            f"cascade cache external chat counts mismatch: {counts!r}"
                        )
                    for label, schema_name in (
                        ("zimage", "zimage"),
                        ("minimaxh3", "minimaxh3"),
                    ):
                        changed_chats = [
                            item
                            for item in stub.chat_observations
                            if item.get("schema_name") == schema_name
                        ]
                        if not changed_chats:
                            raise AcceptanceFailure(
                                f"{label} changed request was not observed"
                            )
                        request = changed_chats[-1].get("request")
                        messages = (
                            request.get("messages")
                            if isinstance(request, Mapping)
                            else None
                        )
                        if (
                            not isinstance(messages, list)
                            or not messages
                            or not isinstance(messages[0], Mapping)
                            or "cache-change" not in str(messages[0].get("content"))
                        ):
                            raise AcceptanceFailure(
                                f"{label} changed template was absent from rendered external request"
                            )
                    for event in evidence.events:
                        if (
                            event.get("name") == "cache_task"
                            and event.get("operation") in {"image_hit", "video_hit"}
                            and event.get("external", {}).get("chat_delta")
                        ):
                            raise AcceptanceFailure(
                                "a cache hit unexpectedly made an external chat request"
                            )

                    initial_asset_images = [
                        row
                        for row in before_state["asset_images"]
                        if row["asset_id"] == fixture["asset_ids"][0]
                    ]
                    final_asset_images = [
                        row
                        for row in final_state["asset_images"]
                        if row["asset_id"] == fixture["asset_ids"][0]
                    ]
                    initial_videos = [
                        row
                        for row in before_state["clip_videos"]
                        if row["clip_id"] == fixture["success_clip_id"]
                    ]
                    final_videos = [
                        row
                        for row in final_state["clip_videos"]
                        if row["clip_id"] == fixture["success_clip_id"]
                    ]
                    if (
                        len(initial_asset_images) != 1
                        or len(final_asset_images) != 4
                        or len(initial_videos) != 0
                        or len(final_videos) != 3
                    ):
                        raise AcceptanceFailure(
                            "cache image/video persistence counts did not show miss, hit, mismatch"
                        )
                    if any(
                        not item["exists"] or item["bytes"] <= 0
                        for item in final_state["files"]
                    ):
                        raise AcceptanceFailure(
                            "cache final database media rows do not have readable files"
                        )
                    evidence.add(
                        "cache_assertions",
                        task_ids={
                            "image_first": image_first_id,
                            "image_hit": image_hit_id,
                            "image_changed": image_miss_id,
                            "video_first": video_first_id,
                            "video_hit": video_hit_id,
                            "video_changed": video_miss_id,
                            "assets_changed": assets_id,
                            "shots_changed": shots_id,
                        },
                        expected_schema_counts=expected_schema_counts,
                        observed_counts=counts,
                        cache_payloads={
                            "image_first": first_image_snapshot,
                            "image_hit": hit_image_snapshot,
                            "image_changed": changed_image_snapshot,
                            "video_first": first_video_snapshot,
                            "video_hit": hit_video_snapshot,
                            "video_changed": changed_video_snapshot,
                        },
                        changed_extraction_payloads={
                            "script2assets": changed_assets_record["payload"],
                            "script2shots": changed_shots_record["payload"],
                        },
                        storage_counts={
                            "asset_images_before": len(initial_asset_images),
                            "asset_images_after": len(final_asset_images),
                            "clip_videos_before": len(initial_videos),
                            "clip_videos_after": len(final_videos),
                        },
                    )
                evidence.add(
                    "external_stub_observations",
                    chat=list(stub.chat_observations),
                    http=list(stub.http_observations),
                    counts=cascade_stub_counts(stub),
                )
        finally:
            if process is not None:
                stopped = stop_process(process)
                evidence.add(
                    "production_process_shutdown",
                    **child_observation(stopped),
                    process_exited=process.poll() is not None,
                )
            await cascade_cleanup_fixture(raw_url, fixture)
        if (
            stopped is None
            or stopped.timed_out
            or process is None
            or process.poll() is None
        ):
            raise AcceptanceFailure(
                "cascade cache owned production process did not cleanly stop"
            )
    evidence.add(
        "owned_resource_cleanup",
        production_process_stopped=True,
        runtime_directory_exists=runtime_dir.exists(),
    )
    intentional_failure = run_child(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('c012 intentional child failure\\n'); "
            "raise SystemExit(17)",
        ],
        cwd=ROOT,
        timeout=10.0,
    )
    evidence.add("intentional_child_failure", **child_observation(intentional_failure))
    if (
        intentional_failure.returncode == 0
        or intentional_failure.timed_out
        or "c012 intentional child failure" not in intentional_failure.text_stderr()
    ):
        raise AcceptanceFailure(
            "cascade cache intentional child failure did not return the expected non-zero result"
        )

async def command_cascade(_arguments: argparse.Namespace, evidence: RunEvidence) -> None:
    if getattr(_arguments, "case", "matrix") == "cache":
        await command_cascade_cache(_arguments, evidence)
        return
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


async def recovery_create_episode(
    client: httpx.AsyncClient,
    base_url: str,
    project_id: int,
    sequence: int,
    request_log: list[dict[str, object]],
) -> int:
    path = f"/api/projects/{project_id}/episodes"
    status, body = await slow_page_http_json(
        client,
        "POST",
        f"{base_url}{path}",
        {
            "seq": sequence,
            "title": f"恢复任务 {sequence}",
            "script_text": f"recovery controlled script {sequence}",
        },
    )
    entry: dict[str, object] = {
        "method": "POST",
        "path": path,
        "status": status,
        "sequence": sequence,
    }
    if isinstance(body, Mapping):
        entry["response"] = dict(body)
    request_log.append(entry)
    if status != 201:
        raise AcceptanceFailure(
            f"recovery episode creation returned {status}: {body!r}"
        )
    episode = require_mapping(body, "recovery episode response")
    episode_id = episode.get("id")
    if not isinstance(episode_id, int):
        raise AcceptanceFailure(f"recovery episode id missing: {body!r}")
    return episode_id


def recovery_file_manifest(data_dir: Path) -> list[dict[str, object]]:
    manifest: list[dict[str, object]] = []
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            manifest.append(
                {
                    "path": path.relative_to(data_dir).as_posix(),
                    "bytes": path.stat().st_size,
                }
            )
    return manifest


async def recovery_read_state(
    raw_url: str,
    project_id: int,
    task_ids: Sequence[int],
    data_dir: Path,
) -> dict[str, object]:
    tasks = await read_database_tasks(raw_url)
    task_id_set = set(task_ids)
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    try:
        rows = await connection.fetch(
            "SELECT id, project_id, type, name, description, source, revision "
            "FROM assets WHERE project_id = $1 ORDER BY id",
            project_id,
        )
    finally:
        await connection.close()
    selected_tasks: list[dict[str, object]] = []
    for task in tasks:
        if task["id"] not in task_id_set:
            continue
        selected_task = dict(task)
        payload = selected_task.get("payload")
        if isinstance(payload, str):
            try:
                selected_task["payload"] = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise AcceptanceFailure(
                    f"recovery task {task['id']} payload is not valid JSON: {payload!r}"
                ) from exc
        selected_tasks.append(selected_task)
    return {
        "tasks": selected_tasks,
        "assets": [
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "type": row["type"],
                "name": row["name"],
                "description": row["description"],
                "source": row["source"],
                "revision": row["revision"],
            }
            for row in rows
        ],
        "file_manifest": recovery_file_manifest(data_dir),
    }


def recovery_task_row(
    state: Mapping[str, object], task_id: int, label: str
) -> Mapping[str, object]:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        raise AcceptanceFailure(f"{label} state has no task list")
    for task in tasks:
        if isinstance(task, Mapping) and task.get("id") == task_id:
            return task
    raise AcceptanceFailure(f"{label} task {task_id} was not found: {state!r}")


def recovery_assert_legal_payload(
    task: Mapping[str, object], episode_id: int, label: str
) -> None:
    payload = task.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != {
        "input_snapshot",
        "input_hash",
        "source_revisions",
    }:
        raise AcceptanceFailure(f"{label} payload is not the frozen task contract: {task!r}")
    snapshot = payload.get("input_snapshot")
    if not isinstance(snapshot, Mapping) or not snapshot:
        raise AcceptanceFailure(f"{label} payload input_snapshot is empty: {task!r}")
    if snapshot.get("episode_id") != episode_id:
        raise AcceptanceFailure(f"{label} payload episode identity mismatch: {task!r}")
    if snapshot.get("template_key") != "script2assets":
        raise AcceptanceFailure(f"{label} payload template snapshot mismatch: {task!r}")
    if not isinstance(snapshot.get("rendered_prompt"), str) or not snapshot["rendered_prompt"]:
        raise AcceptanceFailure(f"{label} payload rendered prompt is missing: {task!r}")
    if not isinstance(payload.get("source_revisions"), Mapping):
        raise AcceptanceFailure(f"{label} payload source revisions are invalid: {task!r}")


async def recovery_wait_for_task_status(
    raw_url: str,
    project_id: int,
    task_ids: Sequence[int],
    data_dir: Path,
    task_id: int,
    expected: set[str],
    *,
    timeout: float,
) -> Mapping[str, object]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last_state = await recovery_read_state(
            raw_url, project_id, task_ids, data_dir
        )
        row = recovery_task_row(last_state, task_id, "recovery wait")
        if row.get("status") in expected:
            return row
        await asyncio.sleep(0.1)
    raise AcceptanceFailure(
        f"recovery task {task_id} did not reach {sorted(expected)}: {last_state!r}"
    )


async def recovery_wait_for_chat_count(
    stub: RecoveryHTTPStub, expected: int, *, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(stub.chat_requests) >= expected:
            return
        await asyncio.sleep(0.05)
    raise AcceptanceFailure(
        f"recovery stub saw {len(stub.chat_requests)} chat requests, expected {expected}"
    )


async def recovery_wait_for_chat_disconnect(
    stub: RecoveryHTTPStub, expected: int, *, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(stub.chat_disconnects) >= expected:
            return
        await asyncio.sleep(0.05)
    raise AcceptanceFailure(
        "recovery stub did not observe the canceled external request: "
        f"disconnects={stub.chat_disconnects!r}"
    )


def recovery_database_name(raw_url: str) -> str:
    database = urlsplit(raw_url).path.lstrip("/")
    if not database:
        raise AcceptanceFailure("recovery database name is missing")
    return database.replace('"', '""')


async def recovery_set_database_read_only(raw_url: str) -> dict[str, object]:
    database = recovery_database_name(raw_url)
    admin_url = migration_database_url(raw_url, "postgres").replace(
        "+asyncpg", "", 1
    )
    connection = await asyncpg.connect(admin_url)
    try:
        rows = await connection.fetch(
            "SELECT pid, application_name, state, wait_event_type, wait_event, query "
            "FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid() ORDER BY pid",
            database,
        )
        await connection.execute(
            f'ALTER DATABASE "{database}" SET default_transaction_read_only = on'
        )
        terminated: list[dict[str, object]] = []
        for row in rows:
            terminated.append(
                {
                    "pid": row["pid"],
                    "application_name": row["application_name"],
                    "state": row["state"],
                    "wait_event_type": row["wait_event_type"],
                    "wait_event": row["wait_event"],
                    "query": row["query"],
                    "terminated": bool(
                        await connection.fetchval(
                            "SELECT pg_terminate_backend($1)", row["pid"]
                        )
                    ),
                }
            )
    finally:
        await connection.close()

    verification_connection = await asyncpg.connect(
        raw_url.replace("+asyncpg", "", 1)
    )
    try:
        new_session_setting = await verification_connection.fetchval(
            "SELECT current_setting('default_transaction_read_only')"
        )
    finally:
        await verification_connection.close()
    if new_session_setting != "on":
        raise AcceptanceFailure(
            f"recovery database read-only fault was not applied: {new_session_setting!r}"
        )
    if not any(item["terminated"] for item in terminated):
        raise AcceptanceFailure(
            f"recovery database fault did not terminate an application session: {terminated!r}"
        )
    return {
        "database": database,
        "default_transaction_read_only": new_session_setting,
        "database_config": "ALTER DATABASE SET default_transaction_read_only = on",
        "terminated_sessions": terminated,
    }


async def recovery_restore_database_read_write(raw_url: str) -> dict[str, object]:
    database = recovery_database_name(raw_url)
    admin_url = migration_database_url(raw_url, "postgres").replace(
        "+asyncpg", "", 1
    )
    connection = await asyncpg.connect(admin_url)
    try:
        await connection.execute(
            f'ALTER DATABASE "{database}" SET default_transaction_read_only = off'
        )
    finally:
        await connection.close()
    verification_connection = await asyncpg.connect(
        raw_url.replace("+asyncpg", "", 1)
    )
    try:
        setting = await verification_connection.fetchval(
            "SELECT current_setting('default_transaction_read_only')"
        )
    finally:
        await verification_connection.close()
    if setting != "off":
        raise AcceptanceFailure(
            f"recovery database read-write restore failed: {setting!r}"
        )
    return {"database": database, "default_transaction_read_only": setting}


async def recovery_cleanup_fixture(
    raw_url: str, fixture: Mapping[str, object]
) -> None:
    project_id = int(fixture["project_id"])
    style_id = int(fixture["style_id"])
    episode_ids = [int(value) for value in fixture["episode_ids"]]
    task_ids = [int(value) for value in fixture.get("task_ids", [])]
    connection = await asyncpg.connect(raw_url.replace("+asyncpg", "", 1))
    try:
        async with connection.transaction():
            if task_ids or episode_ids:
                await connection.execute(
                    "DELETE FROM tasks WHERE "
                    "($1::int[] <> '{}'::int[] AND id = ANY($1::int[])) "
                    "OR ($2::int[] <> '{}'::int[] AND target_id = ANY($2::int[]))",
                    task_ids,
                    episode_ids,
                )
            await connection.execute(
                "DELETE FROM asset_images WHERE asset_id IN "
                "(SELECT id FROM assets WHERE project_id = $1)",
                project_id,
            )
            await connection.execute("DELETE FROM assets WHERE project_id = $1", project_id)
            await connection.execute(
                "DELETE FROM episodes WHERE id = ANY($1::int[])", episode_ids
            )
            await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
            await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


async def command_recovery(
    _arguments: argparse.Namespace, evidence: RunEvidence
) -> None:
    raw_url, data_dir, identity = explicit_runtime()
    database_identity = await read_database_identity(raw_url)
    if database_identity["current_database"] != identity["database_from_url"]:
        raise AcceptanceFailure(
            "database identity does not match explicit DATABASE_URL database"
        )
    evidence.add(
        "runtime_identity",
        database_url=identity,
        database=database_identity,
        data_dir=str(data_dir),
    )

    fixture: dict[str, object] = {}
    task_ids: list[int] = []
    first_process: subprocess.Popen[bytes] | None = None
    second_process: subprocess.Popen[bytes] | None = None
    restart_process: subprocess.Popen[bytes] | None = None
    database_fault_maybe_active = False
    with tempfile.TemporaryDirectory(
        prefix="c012-recovery-", dir=str(data_dir)
    ) as runtime_name:
        runtime_dir = Path(runtime_name)
        recovery_stub = RecoveryHTTPStub()
        try:
            with recovery_stub:
                request_log: list[dict[str, object]] = []
                first_process, first_port = start_backend_process(
                    raw_url, runtime_dir, recovery_stub
                )
                first_health = await wait_for_http(
                    f"http://127.0.0.1:{first_port}/api/system/health"
                )
                if first_health.status_code != 200:
                    raise AcceptanceFailure(
                        f"recovery first backend health returned "
                        f"{first_health.status_code}: {first_health.body!r}"
                    )
                evidence.add(
                    "first_production_process",
                    pid=first_process.pid,
                    port=first_port,
                    health=first_health.body,
                    queue="production TaskQueue",
                    handlers="production gen_assets_handler",
                    dependency_stub=recovery_stub.base_url,
                )
                async with httpx.AsyncClient(
                    timeout=20, trust_env=False
                ) as client:
                    initial_fixture = await slow_page_create_fixture(
                        client,
                        f"http://127.0.0.1:{first_port}",
                        request_log,
                        task_count=2,
                    )
                    fixture.update(initial_fixture)
                    episode_ids = [
                        int(value) for value in initial_fixture["episode_ids"]
                    ]
                    third_episode_id = await recovery_create_episode(
                        client,
                        f"http://127.0.0.1:{first_port}",
                        int(initial_fixture["project_id"]),
                        3,
                        request_log,
                    )
                    fixture["episode_ids"] = [*episode_ids, third_episode_id]

                    recovery_stub.set_blocked()
                    first_path = (
                        f"/api/episodes/{episode_ids[0]}/generate-assets"
                    )
                    first_status, first_body = await slow_page_http_json(
                        client, "POST", f"http://127.0.0.1:{first_port}{first_path}"
                    )
                    request_log.append(
                        {
                            "method": "POST",
                            "path": first_path,
                            "status": first_status,
                            "response": first_body,
                        }
                    )
                    if first_status != 202:
                        raise AcceptanceFailure(
                            f"recovery running enqueue returned "
                            f"{first_status}: {first_body!r}"
                        )
                    first_response = require_mapping(
                        first_body, "recovery running enqueue response"
                    )
                    first_task_id = first_response.get("task_id")
                    if not isinstance(first_task_id, int):
                        raise AcceptanceFailure(
                            f"recovery running task id missing: {first_body!r}"
                        )
                    task_ids.append(first_task_id)
                    await recovery_wait_for_chat_count(
                        recovery_stub, 1, timeout=20
                    )
                    first_running_state = await recovery_read_state(
                        raw_url,
                        int(initial_fixture["project_id"]),
                        task_ids,
                        runtime_dir,
                    )
                    first_running = recovery_task_row(
                        first_running_state, first_task_id, "running task"
                    )
                    if first_running.get("status") != "running":
                        raise AcceptanceFailure(
                            f"first task did not become running: {first_running!r}"
                        )
                    recovery_assert_legal_payload(
                        first_running, episode_ids[0], "running task"
                    )

                    queued_path = (
                        f"/api/episodes/{episode_ids[1]}/generate-assets"
                    )
                    queued_status, queued_body = await slow_page_http_json(
                        client,
                        "POST",
                        f"http://127.0.0.1:{first_port}{queued_path}",
                    )
                    request_log.append(
                        {
                            "method": "POST",
                            "path": queued_path,
                            "status": queued_status,
                            "response": queued_body,
                        }
                    )
                    if queued_status != 202:
                        raise AcceptanceFailure(
                            f"recovery queued enqueue returned "
                            f"{queued_status}: {queued_body!r}"
                        )
                    queued_response = require_mapping(
                        queued_body, "recovery queued enqueue response"
                    )
                    queued_task_id = queued_response.get("task_id")
                    if not isinstance(queued_task_id, int):
                        raise AcceptanceFailure(
                            f"recovery queued task id missing: {queued_body!r}"
                        )
                    task_ids.append(queued_task_id)
                    queued_state = await recovery_read_state(
                        raw_url,
                        int(initial_fixture["project_id"]),
                        task_ids,
                        runtime_dir,
                    )
                    queued_row = recovery_task_row(
                        queued_state, queued_task_id, "queued task"
                    )
                    if queued_row.get("status") != "queued":
                        raise AcceptanceFailure(
                            f"second task did not remain queued behind running task: "
                            f"{queued_row!r}"
                        )
                    recovery_assert_legal_payload(
                        queued_row, episode_ids[1], "queued task"
                    )
                    evidence.add(
                        "running_and_queued",
                        request_log=list(request_log),
                        running_task=first_running,
                        queued_task=queued_row,
                        external_stub=recovery_stub.snapshot(),
                    )

                second_process, second_port = start_backend_process(
                    raw_url, runtime_dir, recovery_stub
                )
                try:
                    await asyncio.to_thread(second_process.wait, 15)
                except subprocess.TimeoutExpired:
                    pass
                second_lock_stop = stop_process(second_process, timeout=30)
                evidence.add(
                    "advisory_lock_exclusion",
                    pid=second_process.pid,
                    port=second_port,
                    **child_observation(second_lock_stop),
                )
                second_process = None
                lock_output = (
                    second_lock_stop.text_stdout()
                    + second_lock_stop.text_stderr()
                )
                if (
                    second_lock_stop.returncode == 0
                    or second_lock_stop.timed_out
                    or second_lock_stop.termination_requested
                    or "AdvisoryLockNotAcquired" not in lock_output
                    or "advisory lock is already held" not in lock_output
                ):
                    raise AcceptanceFailure(
                        "second backend did not naturally reject the shared advisory lock "
                        "with the expected startup error"
                    )

                first_stop = stop_process(first_process, timeout=30)
                evidence.add(
                    "first_process_terminated",
                    **child_observation(first_stop),
                )
                first_process = None
                recovery_stub.release()
                await recovery_wait_for_chat_disconnect(
                    recovery_stub, 1, timeout=10
                )
                after_termination_state = await recovery_read_state(
                    raw_url,
                    int(fixture["project_id"]),
                    task_ids,
                    runtime_dir,
                )
                after_termination_running = recovery_task_row(
                    after_termination_state,
                    task_ids[0],
                    "post-termination running task",
                )
                after_termination_queued = recovery_task_row(
                    after_termination_state,
                    task_ids[1],
                    "post-termination queued task",
                )
                if (
                    after_termination_running.get("status") != "running"
                    or after_termination_queued.get("status") != "queued"
                    or after_termination_running.get("started_at") is None
                    or after_termination_queued.get("started_at") is not None
                ):
                    raise AcceptanceFailure(
                        "terminating the first backend did not preserve running/queued "
                        f"state: {after_termination_state!r}"
                    )
                evidence.add(
                    "termination_preserves_tasks",
                    running_task=after_termination_running,
                    queued_task=after_termination_queued,
                    assets=after_termination_state["assets"],
                    file_manifest=after_termination_state["file_manifest"],
                )

                second_process, second_port = start_backend_process(
                    raw_url, runtime_dir, recovery_stub
                )
                second_health = await wait_for_http(
                    f"http://127.0.0.1:{second_port}/api/system/health"
                )
                if second_health.status_code != 200:
                    raise AcceptanceFailure(
                        f"recovery restart health returned {second_health.status_code}: "
                        f"{second_health.body!r}"
                    )
                recovered_running = await recovery_wait_for_task_status(
                    raw_url,
                    int(fixture["project_id"]),
                    task_ids,
                    runtime_dir,
                    task_ids[0],
                    {"failed"},
                    timeout=20,
                )
                recovered_queued = await recovery_wait_for_task_status(
                    raw_url,
                    int(fixture["project_id"]),
                    task_ids,
                    runtime_dir,
                    task_ids[1],
                    {"done"},
                    timeout=60,
                )
                recovered_state = await recovery_read_state(
                    raw_url,
                    int(fixture["project_id"]),
                    task_ids,
                    runtime_dir,
                )
                if recovered_running.get("error_msg") != "server restarted":
                    raise AcceptanceFailure(
                        f"restarted running task has the wrong error: {recovered_running!r}"
                    )
                assets_after_queue = recovered_state["assets"]
                if not isinstance(assets_after_queue, list) or len(assets_after_queue) != 1:
                    raise AcceptanceFailure(
                        "queued recovery did not create exactly one generated asset: "
                        f"{recovered_state!r}"
                    )
                generated_asset = assets_after_queue[0]
                if not isinstance(generated_asset, Mapping) or generated_asset.get(
                    "source"
                ) != "generated":
                    raise AcceptanceFailure(
                        f"queued recovery asset is not a generated production row: "
                        f"{generated_asset!r}"
                    )
                evidence.add(
                    "queued_recovery",
                    restart_pid=second_process.pid,
                    restart_port=second_port,
                    health=second_health.body,
                    running_task=recovered_running,
                    queued_task=recovered_queued,
                    assets=recovered_state["assets"],
                    file_manifest=recovered_state["file_manifest"],
                    external_stub=recovery_stub.snapshot(),
                )

                async with httpx.AsyncClient(
                    timeout=20, trust_env=False
                ) as client:
                    heartbeat_episode_id = int(fixture["episode_ids"][2])
                    recovery_stub.set_blocked()
                    heartbeat_path = (
                        f"/api/episodes/{heartbeat_episode_id}/generate-assets"
                    )
                    heartbeat_status, heartbeat_body = await slow_page_http_json(
                        client,
                        "POST",
                        f"http://127.0.0.1:{second_port}{heartbeat_path}",
                    )
                    request_log.append(
                        {
                            "method": "POST",
                            "path": heartbeat_path,
                            "status": heartbeat_status,
                            "response": heartbeat_body,
                        }
                    )
                    if heartbeat_status != 202:
                        raise AcceptanceFailure(
                            f"recovery heartbeat enqueue returned "
                            f"{heartbeat_status}: {heartbeat_body!r}"
                        )
                    heartbeat_response = require_mapping(
                        heartbeat_body, "recovery heartbeat enqueue response"
                    )
                    heartbeat_task_id = heartbeat_response.get("task_id")
                    if not isinstance(heartbeat_task_id, int):
                        raise AcceptanceFailure(
                            f"recovery heartbeat task id missing: {heartbeat_body!r}"
                        )
                    task_ids.append(heartbeat_task_id)
                    await recovery_wait_for_chat_count(
                        recovery_stub, 3, timeout=20
                    )
                    heartbeat_before_state = await recovery_read_state(
                        raw_url,
                        int(fixture["project_id"]),
                        task_ids,
                        runtime_dir,
                    )
                    heartbeat_running = recovery_task_row(
                        heartbeat_before_state,
                        heartbeat_task_id,
                        "heartbeat task",
                    )
                    if heartbeat_running.get("status") != "running":
                        raise AcceptanceFailure(
                            f"heartbeat task did not become running: {heartbeat_running!r}"
                        )
                    recovery_assert_legal_payload(
                        heartbeat_running,
                        heartbeat_episode_id,
                        "heartbeat task",
                    )
                    heartbeat_at_before = heartbeat_running.get("heartbeat_at")
                    disconnect_count_before = len(recovery_stub.chat_disconnects)
                    database_fault_maybe_active = True
                    database_fault = await recovery_set_database_read_only(raw_url)
                    await asyncio.sleep(11.5)
                    await recovery_wait_for_chat_disconnect(
                        recovery_stub,
                        disconnect_count_before + 1,
                        timeout=10,
                    )
                    heartbeat_fault_state = await recovery_read_state(
                        raw_url,
                        int(fixture["project_id"]),
                        task_ids,
                        runtime_dir,
                    )
                    heartbeat_fault_task = recovery_task_row(
                        heartbeat_fault_state,
                        heartbeat_task_id,
                        "heartbeat fault task",
                    )
                    if (
                        heartbeat_fault_task.get("status") != "running"
                        or heartbeat_fault_task.get("heartbeat_at") != heartbeat_at_before
                        or len(heartbeat_fault_state["assets"]) != 1
                    ):
                        raise AcceptanceFailure(
                            "heartbeat database fault changed task state or side effects: "
                            f"before={heartbeat_running!r} after={heartbeat_fault_state!r}"
                        )
                    if recovery_stub.chat_handlers_started != 0:
                        raise AcceptanceFailure(
                            "heartbeat cancellation left a recovery stub handler active: "
                            f"{recovery_stub.snapshot()!r}"
                        )
                    recovery_stub.release()
                    evidence.add(
                        "heartbeat_database_failure",
                        database_fault=database_fault,
                        task_before=heartbeat_running,
                        task_after=heartbeat_fault_task,
                        heartbeat_at_unchanged=True,
                        assets=heartbeat_fault_state["assets"],
                        file_manifest=heartbeat_fault_state["file_manifest"],
                        external_stub=recovery_stub.snapshot(),
                    )

                heartbeat_stop = stop_process(second_process, timeout=30)
                evidence.add(
                    "heartbeat_process_shutdown",
                    **child_observation(heartbeat_stop),
                )
                second_process = None
                restored = await recovery_restore_database_read_write(raw_url)
                database_fault_maybe_active = False
                evidence.add("database_read_write_restored", **restored)

                restart_process, restart_port = start_backend_process(
                    raw_url, runtime_dir, recovery_stub
                )
                restart_health = await wait_for_http(
                    f"http://127.0.0.1:{restart_port}/api/system/health"
                )
                if restart_health.status_code != 200:
                    raise AcceptanceFailure(
                        f"heartbeat recovery restart health returned "
                        f"{restart_health.status_code}: {restart_health.body!r}"
                    )
                recovered_heartbeat = await recovery_wait_for_task_status(
                    raw_url,
                    int(fixture["project_id"]),
                    task_ids,
                    runtime_dir,
                    heartbeat_task_id,
                    {"failed"},
                    timeout=20,
                )
                if recovered_heartbeat.get("error_msg") != "server restarted":
                    raise AcceptanceFailure(
                        "heartbeat task did not recover as server restarted: "
                        f"{recovered_heartbeat!r}"
                    )
                final_state = await recovery_read_state(
                    raw_url,
                    int(fixture["project_id"]),
                    task_ids,
                    runtime_dir,
                )
                if len(final_state["assets"]) != 1:
                    raise AcceptanceFailure(
                        f"heartbeat recovery changed generated asset count: {final_state!r}"
                    )
                evidence.add(
                    "heartbeat_restart_recovery",
                    pid=restart_process.pid,
                    port=restart_port,
                    health=restart_health.body,
                    task=recovered_heartbeat,
                    final_state=final_state,
                    external_stub=recovery_stub.snapshot(),
                )
                restart_stop = stop_process(restart_process, timeout=30)
                evidence.add(
                    "restart_process_shutdown",
                    **child_observation(restart_stop),
                )
                restart_process = None
        finally:
            recovery_stub.release()
            for label, process in (
                ("first", first_process),
                ("second", second_process),
                ("restart", restart_process),
            ):
                if process is not None and process.poll() is None:
                    stopped = stop_process(process, timeout=30)
                    evidence.add(
                        f"{label}_process_shutdown_cleanup",
                        **child_observation(stopped),
                    )
            if database_fault_maybe_active:
                restored = await recovery_restore_database_read_write(raw_url)
                evidence.add("database_read_write_restored_cleanup", **restored)
            if fixture:
                await recovery_cleanup_fixture(raw_url, fixture)
                evidence.add(
                    "fixture_cleanup",
                    project_id=fixture["project_id"],
                    task_ids=task_ids,
                    asset_count_removed=True,
                )
    if runtime_dir.exists():
        raise AcceptanceFailure(
            f"recovery runtime directory was not removed: {runtime_dir}"
        )
    evidence.add(
        "owned_resource_cleanup",
        production_processes_stopped=True,
        runtime_directory_exists=False,
        external_stub=recovery_stub.snapshot(),
    )


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
        "trash",
        "verify-inputs",
    ):
        subparsers.add_parser(name)
    recovery = subparsers.add_parser("recovery")
    recovery.add_argument("--case", choices=("lifecycle",), required=True)
    cascade = subparsers.add_parser("cascade")
    cascade.add_argument("--case", choices=("matrix", "cache"), default="matrix")
    ws = subparsers.add_parser("ws")
    ws.add_argument(
        "--case",
        choices=("cancel", "slow-page", "slow-page-browser"),
        default="cancel",
    )
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
        if arguments.case == "slow-page":
            await command_ws_slow_page(arguments, evidence)
            return
        if arguments.case == "slow-page-browser":
            await command_ws_slow_page_browser(arguments, evidence)
            return
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
