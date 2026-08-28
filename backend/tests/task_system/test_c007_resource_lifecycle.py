import asyncio
import json
import multiprocessing
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from app.integrations.comfy import ComfyClient
from app.services.vllm import VLLMClient


_protocol_records = None


def _record(method: str, path: str, body: object) -> None:
    if _protocol_records is None:
        raise RuntimeError("protocol server record queue is not configured")
    _protocol_records.put((method, path, body))


class _ProtocolHandler(BaseHTTPRequestHandler):
    server_version = "C007ProtocolServer/1.0"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _read_json(self) -> object:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return None
        return json.loads(raw)

    def _send_json(self, status: int, value: object) -> None:
        raw = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/bad-json"):
            _record("GET", self.path, None)
            raw = b"{"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path.startswith("/bad-shape"):
            _record("GET", self.path, None)
            self._send_json(200, [])
            return
        if path.startswith("/error"):
            _record("GET", self.path, None)
            self._send_json(503, {"error": "unhealthy"})
            return
        if path == "/system_stats":
            _record("GET", self.path, None)
            self._send_json(200, {"system": "ready"})
            return
        if path.startswith("/history/"):
            _record("GET", self.path, None)
            prompt_id = unquote(path.rsplit("/", 1)[1])
            self._send_json(200, {prompt_id: {"status": "success"}})
            return
        if path == "/view":
            _record("GET", self.path, None)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(b"view-chunk-1")
            self.wfile.write(b"view-chunk-2")
            return
        _record("GET", self.path, None)
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._read_json()
        _record("POST", self.path, body)
        path = urlsplit(self.path).path
        if path == "/sleep":
            self._send_json(200, {})
            return
        if path == "/prompt":
            if not isinstance(body, dict):
                self._send_json(400, {"error": "body"})
                return
            prompt_id = body.get("prompt_id")
            self._send_json(200, {"prompt_id": prompt_id, "number": 1})
            return
        if path in {"/interrupt", "/free"}:
            self._send_json(200, {})
            return
        self._send_json(404, {"error": "not found"})


async def _websocket_handler(connection: ServerConnection) -> None:
    path = connection.request.path
    _record("WS", path, None)
    await connection.send(json.dumps({"type": "progress", "value": 1}))
    await connection.wait_closed()


def _run_protocol_server(ready: object, records: object) -> None:
    global _protocol_records
    _protocol_records = records
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), _ProtocolHandler)
    http_thread = threading.Thread(
        target=http_server.serve_forever,
        name="c007-http-server",
        daemon=True,
    )
    http_thread.start()

    async def run_websocket_server() -> None:
        websocket_server = await serve(
            _websocket_handler,
            "127.0.0.1",
            0,
        )
        websocket_port = websocket_server.sockets[0].getsockname()[1]
        ready.put((http_server.server_port, websocket_port))
        await asyncio.Future()

    try:
        asyncio.run(run_websocket_server())
    finally:
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=5)


def _start_protocol_server() -> tuple[multiprocessing.Process, object, int, int]:
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    records = context.Queue()
    process = context.Process(
        target=_run_protocol_server,
        args=(ready, records),
    )
    process.start()
    try:
        http_port, websocket_port = ready.get(timeout=10)
    except queue.Empty:
        process.terminate()
        process.join(timeout=5)
        raise AssertionError("protocol server did not start")
    return process, records, http_port, websocket_port


def _stop_protocol_server(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)


def test_client_protocol() -> None:
    async def run() -> None:
        process, records, http_port, websocket_port = _start_protocol_server()
        try:
            vllm = VLLMClient(f"http://127.0.0.1:{http_port}")
            comfy = ComfyClient(f"http://127.0.0.1:{http_port}")
            comfy_ws = ComfyClient(f"http://127.0.0.1:{websocket_port}")
            await vllm.sleep()
            assert await comfy.health() == {"system": "ready"}

            prompt_id = "11111111-1111-4111-8111-111111111111"
            async with comfy_ws.connect_ws(
                client_id=prompt_id,
            ) as websocket:
                message = await websocket.recv()
            assert json.loads(message) == {
                "type": "progress",
                "value": 1,
            }

            workflow = {"3": {"inputs": {"seed": 1}}}
            assert await comfy.submit(
                prompt=workflow,
                client_id=prompt_id,
                prompt_id=prompt_id,
            ) == {"prompt_id": prompt_id, "number": 1}
            assert await comfy.history(prompt_id) == {
                prompt_id: {"status": "success"}
            }
            chunks = [
                chunk
                async for chunk in comfy.view_stream(
                    filename="image.png",
                    subfolder="",
                    media_type="output",
                )
            ]
            assert b"".join(chunks) == b"view-chunk-1view-chunk-2"
            await comfy.interrupt(prompt_id)
            await comfy.free()

            with pytest.raises(httpx.HTTPStatusError):
                await ComfyClient(
                    f"http://127.0.0.1:{http_port}/error"
                ).health()
            with pytest.raises(json.JSONDecodeError):
                await ComfyClient(
                    f"http://127.0.0.1:{http_port}/bad-json"
                ).health()
            with pytest.raises(ValueError, match="JSON object"):
                await ComfyClient(
                    f"http://127.0.0.1:{http_port}/bad-shape"
                ).health()
        finally:
            _stop_protocol_server(process)

        observed = []
        while True:
            try:
                observed.append(records.get_nowait())
            except queue.Empty:
                break

        assert observed[:8] == [
            ("POST", "/sleep?level=1", None),
            ("GET", "/system_stats", None),
            ("WS", f"/ws?clientId={prompt_id}", None),
            (
                "POST",
                "/prompt",
                {
                    "prompt": workflow,
                    "client_id": prompt_id,
                    "prompt_id": prompt_id,
                },
            ),
            ("GET", f"/history/{prompt_id}", None),
            (
                "GET",
                "/view?filename=image.png&subfolder=&type=output",
                None,
            ),
            ("POST", "/interrupt", {"prompt_id": prompt_id}),
            (
                "POST",
                "/free",
                {"unload_models": True, "free_memory": True},
            ),
        ]
        assert observed[8:] == [
            ("GET", "/error/system_stats", None),
            ("GET", "/bad-json/system_stats", None),
            ("GET", "/bad-shape/system_stats", None),
        ]

    asyncio.run(run())
