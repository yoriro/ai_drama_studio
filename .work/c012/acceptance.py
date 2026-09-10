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
import json
import os
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

import asyncpg
import httpx
import websockets.asyncio.client


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
EVIDENCE_DIR = ROOT / ".work" / "c012"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class AcceptanceFailure(RuntimeError):
    """A deterministic acceptance observation did not meet its contract."""


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
        else:
            self._send_json(404, {"detail": "selfcheck route not provided"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        self._send_json(404, {"detail": "selfcheck mutation route not provided"})

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
        diagnostic_reproduced = (
            case == "L1"
            and result.returncode != 0
            and "DeadlockDetectedError" in output
            and "pg_observation=" in output
        )
        scheduled_case = (
            case == "L5"
            and result.returncode != 0
            and "scheduled for its lock-order task" in output
        )
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
