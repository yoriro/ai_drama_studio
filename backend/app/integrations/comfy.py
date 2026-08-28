from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
import websockets.asyncio.client


class ComfyClient:
    """Small protocol-only client for the ComfyUI HTTP and WS endpoints."""

    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
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
        ) as client:
            response = await client.post(
                self._http_url("/free"),
                json={"unload_models": True, "free_memory": True},
            )
            response.raise_for_status()
