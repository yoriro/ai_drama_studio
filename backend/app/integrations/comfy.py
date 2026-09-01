from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
import websockets.asyncio.client


class ComfyClient:
    """Small protocol-only client for the ComfyUI HTTP and WS endpoints."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("COMFY_BASE_URL must be an HTTP URL")
        self._base_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
        )
        websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
        self._websocket_base_url = urlunsplit(
            (websocket_scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
        )
        self._timeout = timeout
        self._transport = transport

    def _http_url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def _json_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.request(
                method,
                self._http_url(path),
                json=None if json_body is None else dict(json_body),
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError(f"Comfy {path} response must be a JSON object")
        return payload

    async def upload_image(
        self, *, filename: str, content: bytes, subfolder: str
    ) -> Mapping[str, Any]:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.post(
                self._http_url("/upload/image"),
                data={
                    "overwrite": "true",
                    "type": "input",
                    "subfolder": subfolder,
                },
                files={"image": (filename, content)},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("Comfy /upload/image response must be a JSON object")
        return payload

    async def health(self) -> Mapping[str, Any]:
        return await self._json_request("GET", "/system_stats")

    @asynccontextmanager
    async def connect_ws(self, client_id: str) -> AsyncIterator[Any]:
        query = urlencode({"clientId": client_id})
        uri = f"{self._websocket_base_url}/ws?{query}"
        async with websockets.asyncio.client.connect(
            uri,
            open_timeout=self._timeout,
        ) as websocket:
            yield websocket

    async def submit(
        self,
        *,
        prompt: Mapping[str, Any],
        client_id: str,
        prompt_id: str,
    ) -> Mapping[str, Any]:
        return await self._json_request(
            "POST",
            "/prompt",
            json_body={
                "prompt": prompt,
                "client_id": client_id,
                "prompt_id": prompt_id,
            },
        )

    async def history(self, prompt_id: str) -> Mapping[str, Any]:
        return await self._json_request(
            "GET", f"/history/{quote(prompt_id, safe='')}"
        )

    async def view_stream(
        self,
        *,
        filename: str,
        subfolder: str,
        media_type: str,
    ) -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
            transport=self._transport,
        ) as client:
            async with client.stream(
                "GET",
                self._http_url("/view"),
                params={
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": media_type,
                },
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk

    async def interrupt(self, prompt_id: str) -> None:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.post(
                self._http_url("/interrupt"),
                json={"prompt_id": prompt_id},
            )
            response.raise_for_status()

    async def free(self) -> None:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.post(
                self._http_url("/free"),
                json={"unload_models": True, "free_memory": True},
            )
            response.raise_for_status()


@dataclass(frozen=True, slots=True)
class ComfyUploadResult:
    name: str
    subfolder: str
    type: str

    @property
    def path(self) -> str:
        return self.name if not self.subfolder else f"{self.subfolder}/{self.name}"


@dataclass(frozen=True, slots=True)
class ComfyVideoOutput:
    filename: str
    subfolder: str
    type: str
    format: str


_COMFY_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})


def _safe_comfy_subfolder(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if len(value) > 1024:
        raise ValueError(f"{field} exceeds 1024 characters")
    if not value:
        return value
    if "\x00" in value or "\\" in value or value.startswith("/"):
        raise ValueError(f"{field} must be a safe relative path")
    segments = value.split("/")
    if any(
        not segment or segment in {".", ".."} or ":" in segment
        for segment in segments
    ):
        raise ValueError(f"{field} must be a safe relative path")
    return value


def _safe_comfy_basename(
    value: object, field: str, *, extension: str
) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 255:
        raise ValueError(f"{field} must be a basename of 1..255 characters")
    if "\x00" in value or "/" in value or "\\" in value:
        raise ValueError(f"{field} must be a single basename")
    suffix = value.rsplit(".", 1)[-1].lower() if "." in value else ""
    if suffix != extension.lower().lstrip("."):
        raise ValueError(f"{field} must use the .{extension.lstrip('.')} extension")
    return value


def parse_comfy_upload_response(
    response: object, *, expected_extension: str
) -> ComfyUploadResult:
    if not isinstance(response, Mapping):
        raise ValueError("Comfy upload response must be a JSON object")
    normalized_extension = expected_extension.lower().lstrip(".")
    if normalized_extension not in _COMFY_IMAGE_EXTENSIONS:
        raise ValueError("expected_extension must be a supported image extension")
    name = _safe_comfy_basename(
        response.get("name"), "Comfy upload name", extension=normalized_extension
    )
    subfolder = _safe_comfy_subfolder(
        response.get("subfolder"), "Comfy upload subfolder"
    )
    if response.get("type") != "input":
        raise ValueError('Comfy upload type must be "input"')
    return ComfyUploadResult(name=name, subfolder=subfolder, type="input")


def parse_comfy_video_history(
    history: object, *, prompt_id: str, output_node: str = "168"
) -> ComfyVideoOutput:
    if not isinstance(history, Mapping):
        raise ValueError("Comfy history must be a JSON object")
    entry = history.get(prompt_id)
    if not isinstance(entry, Mapping):
        raise ValueError("Comfy history is missing the submitted prompt")
    status = entry.get("status")
    status_success = status == "success" or (
        isinstance(status, Mapping) and status.get("status_str") == "success"
    )
    if not status_success:
        raise ValueError("Comfy history status is not successful")
    outputs = entry.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("Comfy history outputs must be an object")
    output = outputs.get(output_node)
    if not isinstance(output, Mapping):
        raise ValueError("Comfy history is missing the bound output node")
    gifs = output.get("gifs")
    if not isinstance(gifs, list) or len(gifs) != 1:
        raise ValueError("Comfy bound output must contain exactly one gif")
    gif = gifs[0]
    if not isinstance(gif, Mapping):
        raise ValueError("Comfy history gif must be an object")
    filename = _safe_comfy_basename(
        gif.get("filename"), "Comfy video filename", extension="mp4"
    )
    subfolder = _safe_comfy_subfolder(
        gif.get("subfolder"), "Comfy video subfolder"
    )
    if gif.get("type") != "output":
        raise ValueError('Comfy video type must be "output"')
    if gif.get("format") != "video/h264-mp4":
        raise ValueError('Comfy video format must be "video/h264-mp4"')
    return ComfyVideoOutput(
        filename=filename,
        subfolder=subfolder,
        type="output",
        format="video/h264-mp4",
    )
