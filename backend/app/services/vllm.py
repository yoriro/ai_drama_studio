from collections.abc import Mapping, Sequence
from typing import Any

import httpx


class VLLMClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def wake(self) -> None:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
        ) as client:
            response = await client.post(f"{self._base_url}/wake_up")
            response.raise_for_status()

    async def structured_chat(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        model: str,
        temperature: float,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        request_body = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(schema),
                },
            },
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=request_body,
            )
            response.raise_for_status()
            return response.json()
