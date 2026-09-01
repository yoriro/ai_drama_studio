from __future__ import annotations

import asyncio
import copy
import json

import httpx
import pytest

from app.integrations.comfy import (
    ComfyClient,
    ComfyUploadResult,
    ComfyVideoOutput,
    parse_comfy_upload_response,
    parse_comfy_video_history,
)


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[tuple[httpx.Request, bytes]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        self.requests.append((request, body))
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(self.response).encode("utf-8"),
            request=request,
        )


def _valid_upload_response() -> dict[str, object]:
    return {
        "name": "subject1.png",
        "subfolder": "c009/task-42",
        "type": "input",
        "fullpath": "C:/must-not-be-read/subject1.png",
    }


def _valid_history() -> dict[str, object]:
    return {
        "prompt-1": {
            "status": {"status_str": "success"},
            "outputs": {
                "168": {
                    "gifs": [
                        {
                            "filename": "clip.mp4",
                            "subfolder": "c009/task-42",
                            "type": "output",
                            "format": "video/h264-mp4",
                            "fullpath": "C:/must-not-be-read/clip.mp4",
                        }
                    ]
                }
            },
        }
    }


def test_upload_image_uses_formal_transport_and_one_multipart_image() -> None:
    async def run() -> None:
        transport = _RecordingTransport(_valid_upload_response())
        client = ComfyClient(
            "http://comfy.test",
            transport=transport,
        )

        response = await client.upload_image(
            filename="subject1.png",
            content=b"PNG-bytes",
            subfolder="c009/task-42",
        )

        assert response == _valid_upload_response()
        assert len(transport.requests) == 1
        request, body = transport.requests[0]
        assert request.method == "POST"
        assert str(request.url) == "http://comfy.test/upload/image"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert body.count(b'name="image"') == 1
        assert b'filename="subject1.png"' in body
        assert b"PNG-bytes" in body
        assert b'name="overwrite"' in body
        assert b"\r\n\r\ntrue\r\n" in body
        assert b'name="type"' in body
        assert b"\r\n\r\ninput\r\n" in body
        assert b'name="subfolder"' in body
        assert b"\r\n\r\nc009/task-42\r\n" in body

    asyncio.run(run())


def test_upload_response_parser_accepts_exact_identity_and_ignores_fullpath() -> None:
    parsed = parse_comfy_upload_response(
        _valid_upload_response(), expected_extension="png"
    )

    assert parsed == ComfyUploadResult(
        name="subject1.png",
        subfolder="c009/task-42",
        type="input",
    )
    assert parsed.path == "c009/task-42/subject1.png"


@pytest.mark.parametrize(
    ("response", "expected_extension", "message"),
    [
        (None, "png", "JSON object"),
        ({"subfolder": "c009", "type": "input"}, "png", "basename"),
        (
            {**_valid_upload_response(), "name": "nested/subject1.png"},
            "png",
            "basename",
        ),
        (
            {**_valid_upload_response(), "name": "a" * 252 + ".png"},
            "png",
            "1..255",
        ),
        (
            {**_valid_upload_response(), "name": "subject1\x00.png"},
            "png",
            "basename",
        ),
        (
            {**_valid_upload_response(), "name": "subject1.jpg"},
            "png",
            ".png",
        ),
        (
            {**_valid_upload_response(), "subfolder": None},
            "png",
            "subfolder",
        ),
        (
            {**_valid_upload_response(), "subfolder": "../escape"},
            "png",
            "safe relative path",
        ),
        (
            {**_valid_upload_response(), "subfolder": "c009//task-42"},
            "png",
            "safe relative path",
        ),
        (
            {**_valid_upload_response(), "subfolder": "c009\\task-42"},
            "png",
            "safe relative path",
        ),
        (
            {**_valid_upload_response(), "subfolder": "c009\x00task"},
            "png",
            "safe relative path",
        ),
        (
            {**_valid_upload_response(), "subfolder": "a" * 1025},
            "png",
            "1024",
        ),
        (
            {**_valid_upload_response(), "type": "output"},
            "png",
            '"input"',
        ),
    ],
    ids=[
        "null-response",
        "missing-name",
        "nested-name",
        "long-name",
        "nul-name",
        "extension-drift",
        "null-subfolder",
        "traversal-subfolder",
        "empty-subfolder-segment",
        "backslash-subfolder",
        "nul-subfolder",
        "long-subfolder",
        "wrong-type",
    ],
)
def test_upload_response_parser_rejects_hostile_contracts(
    response: object, expected_extension: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_comfy_upload_response(
            response, expected_extension=expected_extension
        )


def test_video_history_parser_accepts_only_the_bound_mp4_and_ignores_fullpath() -> None:
    parsed = parse_comfy_video_history(
        _valid_history(), prompt_id="prompt-1", output_node="168"
    )

    assert parsed == ComfyVideoOutput(
        filename="clip.mp4",
        subfolder="c009/task-42",
        type="output",
        format="video/h264-mp4",
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda history: history["prompt-1"]["outputs"]["168"].update({"gifs": []}), "exactly one gif"),
        (
            lambda history: history["prompt-1"]["outputs"]["168"].update(
                {"gifs": [
                    history["prompt-1"]["outputs"]["168"]["gifs"][0],
                    copy.deepcopy(history["prompt-1"]["outputs"]["168"]["gifs"][0]),
                ]}
            ),
            "exactly one gif",
        ),
        (lambda history: history["prompt-1"]["outputs"].update({"167": history["prompt-1"]["outputs"].pop("168")}), "bound output node"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"format": "video/mp4"}), "format"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"type": "input"}), '"output"'),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].pop("filename"), "filename"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"filename": "nested/clip.mp4"}), "basename"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"filename": "a" * 252 + ".mp4"}), "1..255"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"filename": "clip\x00.mp4"}), "basename"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"filename": "clip.png"}), ".mp4"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"subfolder": "../escape"}), "safe relative path"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"subfolder": "c009\x00task"}), "safe relative path"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].update({"subfolder": "a" * 1025}), "1024"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].pop("subfolder"), "subfolder"),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].pop("type"), '"output"'),
        (lambda history: history["prompt-1"]["outputs"]["168"]["gifs"][0].pop("format"), "format"),
        (lambda history: history["prompt-1"].update({"status": "failed"}), "not successful"),
        (lambda history: history["prompt-1"]["outputs"]["168"].update({"gifs": None}), "exactly one gif"),
    ],
    ids=[
        "zero-gifs",
        "two-gifs",
        "wrong-output-node",
        "wrong-format",
        "wrong-type",
        "missing-filename",
        "path-filename",
        "long-filename",
        "nul-filename",
        "extension-filename",
        "path-subfolder",
        "nul-subfolder",
        "long-subfolder",
        "missing-subfolder",
        "missing-type",
        "missing-format",
        "failed-status",
        "null-gifs",
    ],
)
def test_video_history_parser_rejects_hostile_contracts(
    mutator: object, message: str
) -> None:
    history = _valid_history()
    assert callable(mutator)
    mutator(history)  # type: ignore[operator]
    with pytest.raises(ValueError, match=message):
        parse_comfy_video_history(history, prompt_id="prompt-1")
