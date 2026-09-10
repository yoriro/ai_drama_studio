from __future__ import annotations

import asyncio
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import cast

import asyncpg
import pytest


BACKEND = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = BACKEND / "deployment" / "templates"
TEMPLATE_KEYS = ("script2assets", "script2shots", "zimage", "minimaxh3")
TEMPLATE_PATH = "/api/prompt-templates"


def _approved_templates() -> dict[str, str]:
    return {
        key: (TEMPLATE_DIR / f"{key}.txt").read_text(encoding="utf-8")
        for key in TEMPLATE_KEYS
    }


def _write_template_input(directory: Path) -> None:
    directory.mkdir()
    for key in TEMPLATE_KEYS:
        shutil.copyfile(
            TEMPLATE_DIR / f"{key}.txt",
            directory / f"{key}.txt",
        )


def _run_cli(input_dir: Path, base_url: str, mode: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "app.deploy_templates",
            "--base-url",
            base_url,
            "--input-dir",
            str(input_dir),
            "--mode",
            mode,
        ],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )


@dataclass
class _TemplateServerState:
    templates: dict[str, str]
    fail_patch_key: str | None = None
    patch_response_mismatch_key: str | None = None
    invalid_get_body: bytes | None = None
    final_get_drift_key: str | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)
    patch_payloads: list[tuple[str, str]] = field(default_factory=list)
    get_count: int = 0


class _TemplateHTTPServer(ThreadingHTTPServer):
    state: _TemplateServerState

    def __init__(self, state: _TemplateServerState) -> None:
        super().__init__(("127.0.0.1", 0), _TemplateHTTPHandler)
        self.state = state


class _TemplateHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        server = cast(_TemplateHTTPServer, self.server)
        state = server.state
        state.calls.append(("GET", self.path))
        if self.path != TEMPLATE_PATH:
            self._send(404, b'{"detail":"not found"}')
            return
        state.get_count += 1
        if state.invalid_get_body is not None:
            self._send(200, state.invalid_get_body)
            return
        templates = dict(state.templates)
        if state.final_get_drift_key is not None and state.get_count >= 2:
            templates[state.final_get_drift_key] += " response drift"
        body = json.dumps(
            [
                {"key": key, "content": templates[key]}
                for key in TEMPLATE_KEYS
            ],
            ensure_ascii=False,
        ).encode("utf-8")
        self._send(200, body)

    def do_PATCH(self) -> None:
        server = cast(_TemplateHTTPServer, self.server)
        state = server.state
        state.calls.append(("PATCH", self.path))
        content_length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(content_length)
        payload = json.loads(request_body.decode("utf-8"))
        key = self.path.rsplit("/", 1)[-1]
        content = payload["content"]
        state.patch_payloads.append((key, content))
        if key not in TEMPLATE_KEYS:
            self._send(404, b'{"detail":"not found"}')
            return
        if key == state.fail_patch_key:
            self._send(503, b'{"detail":"controlled failure"}')
            return
        state.templates[key] = content
        response_content = content
        if key == state.patch_response_mismatch_key:
            response_content += " response drift"
        self._send(
            200,
            json.dumps(
                {"key": key, "content": response_content},
                ensure_ascii=False,
            ).encode("utf-8"),
        )


@contextmanager
def _serve_template_state(state: _TemplateServerState):
    server = _TemplateHTTPServer(state)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def template_server():
    return _serve_template_state


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("missing", id="missing"),
        pytest.param("unknown", id="unknown"),
        pytest.param("invalid_utf8", id="invalid_utf8"),
        pytest.param("placeholder", id="placeholder"),
        pytest.param("missing_variable", id="missing_variable"),
    ],
)
def test_cli_rejects_invalid_input_before_any_http(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
    case: str,
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    target = input_dir / "script2assets.txt"
    if case == "missing":
        target.unlink()
    elif case == "unknown":
        (input_dir / "unknown.txt").write_text("unknown", encoding="utf-8")
    elif case == "invalid_utf8":
        target.write_bytes(b"\xff")
    elif case == "placeholder":
        target.write_text("[占位] not approved", encoding="utf-8")
    elif case == "missing_variable":
        target.write_text(
            target.read_text(encoding="utf-8").replace(
                "{{existing_assets}}", "{{missing}}", 1
            ),
            encoding="utf-8",
        )
    else:
        raise AssertionError(case)

    state = _TemplateServerState(
        templates={key: f"baseline-{key}" for key in TEMPLATE_KEYS}
    )
    with template_server(state) as server:
        result = _run_cli(input_dir, f"http://127.0.0.1:{server.server_port}", "install")

    assert result.returncode == 1
    assert "input validation failed" in result.stderr
    assert state.calls == []
    assert state.patch_payloads == []


def test_install_patches_all_keys_in_order_and_verifies(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    expected = _approved_templates()
    state = _TemplateServerState(
        templates={key: f"baseline-{key}" for key in TEMPLATE_KEYS}
    )

    with template_server(state) as server:
        result = _run_cli(
            input_dir,
            f"http://127.0.0.1:{server.server_port}",
            "install",
        )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == "installed=script2assets,script2shots,zimage,minimaxh3"
    assert state.calls == [
        ("GET", TEMPLATE_PATH),
        *[("PATCH", f"{TEMPLATE_PATH}/{key}") for key in TEMPLATE_KEYS],
        ("GET", TEMPLATE_PATH),
    ]
    assert state.templates == expected
    assert state.patch_payloads == [(key, expected[key]) for key in TEMPLATE_KEYS]


def test_install_stops_at_failed_patch_and_reports_partial_commit(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    expected = _approved_templates()
    baseline = {key: f"baseline-{key}" for key in TEMPLATE_KEYS}
    state = _TemplateServerState(
        templates=dict(baseline),
        fail_patch_key="zimage",
    )

    with template_server(state) as server:
        result = _run_cli(
            input_dir,
            f"http://127.0.0.1:{server.server_port}",
            "install",
        )

    assert result.returncode == 1
    assert "phase=install" in result.stderr
    assert "succeeded=script2assets,script2shots" in result.stderr
    assert "failed=zimage" in result.stderr
    assert "HTTP 503" in result.stderr
    assert state.calls == [
        ("GET", TEMPLATE_PATH),
        ("PATCH", f"{TEMPLATE_PATH}/script2assets"),
        ("PATCH", f"{TEMPLATE_PATH}/script2shots"),
        ("PATCH", f"{TEMPLATE_PATH}/zimage"),
    ]
    assert state.templates == {
        **baseline,
        "script2assets": expected["script2assets"],
        "script2shots": expected["script2shots"],
    }
    assert [key for key, _ in state.patch_payloads] == [
        "script2assets",
        "script2shots",
        "zimage",
    ]


def test_install_stops_on_patch_response_content_mismatch(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    state = _TemplateServerState(
        templates={key: f"baseline-{key}" for key in TEMPLATE_KEYS},
        patch_response_mismatch_key="script2shots",
    )

    with template_server(state) as server:
        result = _run_cli(
            input_dir,
            f"http://127.0.0.1:{server.server_port}",
            "install",
        )

    assert result.returncode == 1
    assert "succeeded=script2assets" in result.stderr
    assert "failed=script2shots" in result.stderr
    assert "different from the requested body" in result.stderr
    assert [key for key, _ in state.patch_payloads] == [
        "script2assets",
        "script2shots",
    ]
    assert all(
        method != "PATCH" or path.endswith(("script2assets", "script2shots"))
        for method, path in state.calls
    )


def test_install_rejects_invalid_baseline_json_without_patch(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    state = _TemplateServerState(
        templates={key: f"baseline-{key}" for key in TEMPLATE_KEYS},
        invalid_get_body=b"not-json",
    )

    with template_server(state) as server:
        result = _run_cli(
            input_dir,
            f"http://127.0.0.1:{server.server_port}",
            "install",
        )

    assert result.returncode == 1
    assert "invalid JSON" in result.stderr
    assert state.calls == [("GET", TEMPLATE_PATH)]
    assert state.patch_payloads == []


def test_install_rejects_final_content_mismatch_after_all_patches(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    expected = _approved_templates()
    state = _TemplateServerState(
        templates={key: f"baseline-{key}" for key in TEMPLATE_KEYS},
        final_get_drift_key="minimaxh3",
    )

    with template_server(state) as server:
        result = _run_cli(
            input_dir,
            f"http://127.0.0.1:{server.server_port}",
            "install",
        )

    assert result.returncode == 1
    assert "phase=final verification" in result.stderr
    assert "failed=minimaxh3" in result.stderr
    assert state.templates["script2assets"] == expected["script2assets"]
    assert state.templates["script2shots"] == expected["script2shots"]
    assert state.templates["zimage"] == expected["zimage"]
    assert state.templates["minimaxh3"] == expected["minimaxh3"]
    assert state.calls.count(("PATCH", f"{TEMPLATE_PATH}/minimaxh3")) == 1


def test_verify_reads_only_and_reports_content_mismatch(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    state = _TemplateServerState(
        templates={key: f"baseline-{key}" for key in TEMPLATE_KEYS}
    )

    with template_server(state) as server:
        result = _run_cli(
            input_dir,
            f"http://127.0.0.1:{server.server_port}",
            "verify",
        )

    assert result.returncode == 1
    assert "mismatched=script2assets,script2shots,zimage,minimaxh3" in result.stderr
    assert state.calls == [("GET", TEMPLATE_PATH)]
    assert state.patch_payloads == []


def test_verify_succeeds_with_zero_patch_requests(
    tmp_path: Path,
    template_server: Callable[[_TemplateServerState], object],
) -> None:
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    state = _TemplateServerState(templates=_approved_templates())

    with template_server(state) as server:
        result = _run_cli(
            input_dir,
            f"http://127.0.0.1:{server.server_port}",
            "verify",
        )

    assert result.returncode == 0
    assert result.stdout.strip() == "verified=script2assets,script2shots,zimage,minimaxh3"
    assert result.stderr == ""
    assert state.calls == [("GET", TEMPLATE_PATH)]
    assert state.patch_payloads == []


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _read_database_templates() -> dict[str, str]:
    async def read() -> dict[str, str]:
        connection = await asyncpg.connect(_database_url())
        try:
            rows = await connection.fetch(
                "SELECT key, content FROM prompt_templates "
                "WHERE key = ANY($1::text[]) ORDER BY key",
                list(TEMPLATE_KEYS),
            )
            return {str(row["key"]): str(row["content"]) for row in rows}
        finally:
            await connection.close()

    return asyncio.run(read())


def _restore_database_templates(templates: dict[str, str]) -> None:
    async def restore() -> None:
        connection = await asyncpg.connect(_database_url())
        try:
            for key in TEMPLATE_KEYS:
                await connection.execute(
                    "UPDATE prompt_templates SET content = $1 WHERE key = $2",
                    templates[key],
                    key,
                )
        finally:
            await connection.close()

    asyncio.run(restore())


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_backend_process(port: int) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def _wait_for_backend(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"backend exited before readiness: stdout={stdout!r} stderr={stderr!r}"
            )
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            connection.request("GET", TEMPLATE_PATH)
            response = connection.getresponse()
            body = response.read()
        except (ConnectionError, OSError, http.client.HTTPException):
            connection.close()
            time.sleep(0.1)
            continue
        connection.close()
        if response.status == 200:
            json.loads(body.decode("utf-8"))
            return
        time.sleep(0.1)
    raise AssertionError("backend did not become ready within 20 seconds")


@dataclass
class _ProxyState:
    backend_port: int
    fail_key: str
    calls: list[tuple[str, str]] = field(default_factory=list)
    patch_keys: list[str] = field(default_factory=list)


class _FailingProxyServer(ThreadingHTTPServer):
    state: _ProxyState

    def __init__(self, state: _ProxyState) -> None:
        super().__init__(("127.0.0.1", 0), _FailingProxyHandler)
        self.state = state


class _FailingProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send(self, status: int, headers: Mapping[str, str], body: bytes) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, body: bytes = b"") -> None:
        server = cast(_FailingProxyServer, self.server)
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.state.backend_port,
            timeout=10,
        )
        try:
            headers = {"Content-Length": str(len(body))}
            if body:
                headers["Content-Type"] = "application/json"
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            content_type = response.getheader("Content-Type") or "application/json"
            self._send(
                response.status,
                {"Content-Type": content_type},
                response_body,
            )
        finally:
            connection.close()

    def do_GET(self) -> None:
        server = cast(_FailingProxyServer, self.server)
        server.state.calls.append(("GET", self.path))
        self._forward()

    def do_PATCH(self) -> None:
        server = cast(_FailingProxyServer, self.server)
        server.state.calls.append(("PATCH", self.path))
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        key = self.path.rsplit("/", 1)[-1]
        server.state.patch_keys.append(key)
        if key == server.state.fail_key:
            self._send(
                503,
                {"Content-Type": "application/json"},
                b'{"detail":"controlled third patch failure"}',
            )
            return
        self._forward(body)


@contextmanager
def _serve_proxy(state: _ProxyState):
    server = _FailingProxyServer(state)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _stop_backend_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    process.communicate()


def test_cross_process_failure_leaves_only_prior_patches_committed(
    tmp_path: Path,
) -> None:
    baseline = _read_database_templates()
    assert set(baseline) == set(TEMPLATE_KEYS)
    input_dir = tmp_path / "templates"
    _write_template_input(input_dir)
    expected = _approved_templates()
    backend_process: subprocess.Popen[str] | None = None
    backend_port = _free_port()
    proxy_state: _ProxyState | None = None
    try:
        backend_process = _start_backend_process(backend_port)
        _wait_for_backend(backend_process, backend_port)
        proxy_state = _ProxyState(backend_port=backend_port, fail_key="zimage")
        with _serve_proxy(proxy_state) as proxy:
            result = _run_cli(
                input_dir,
                f"http://127.0.0.1:{proxy.server_port}",
                "install",
            )
            observed = _read_database_templates()
            assert result.returncode == 1
            assert "succeeded=script2assets,script2shots" in result.stderr
            assert "failed=zimage" in result.stderr
            assert proxy_state.patch_keys == [
                "script2assets",
                "script2shots",
                "zimage",
            ]
            assert proxy_state.calls == [
                ("GET", TEMPLATE_PATH),
                ("PATCH", f"{TEMPLATE_PATH}/script2assets"),
                ("PATCH", f"{TEMPLATE_PATH}/script2shots"),
                ("PATCH", f"{TEMPLATE_PATH}/zimage"),
            ]
            assert observed == {
                **baseline,
                "script2assets": expected["script2assets"],
                "script2shots": expected["script2shots"],
            }
            assert backend_process.poll() is None
    finally:
        _restore_database_templates(baseline)
        if backend_process is not None:
            _stop_backend_process(backend_process)
