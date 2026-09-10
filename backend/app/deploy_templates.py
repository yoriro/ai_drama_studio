from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from app.services.asset_image_inputs import (
    _PLACEHOLDER_PATTERN,
    _REQUIRED_PLACEHOLDERS as _ZIMAGE_PLACEHOLDERS,
)
from app.services.clip_video_inputs import (
    _REQUIRED_PLACEHOLDERS as _MINIMAXH3_PLACEHOLDERS,
)
from app.services.generate_assets import (
    _REQUIRED_PLACEHOLDERS as _SCRIPT2ASSETS_PLACEHOLDERS,
)
from app.services.generate_shots import (
    _REQUIRED_PLACEHOLDERS as _SCRIPT2SHOTS_PLACEHOLDERS,
)
from app.services.prompt_templates import TEMPLATE_KEYS


_TEMPLATE_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "script2assets": _SCRIPT2ASSETS_PLACEHOLDERS,
    "script2shots": _SCRIPT2SHOTS_PLACEHOLDERS,
    "zimage": _ZIMAGE_PLACEHOLDERS,
    "minimaxh3": _MINIMAXH3_PLACEHOLDERS,
}
_TEMPLATE_PATH = "/api/prompt-templates"
_HTTP_TIMEOUT_SECONDS = 10.0


class DeploymentError(RuntimeError):
    """A user-actionable template deployment or protocol failure."""


def _format_keys(keys: list[str]) -> str:
    return ",".join(keys) if keys else "none"


def _validate_template_content(key: str, content: str) -> None:
    if not content.strip():
        raise DeploymentError(f"input validation failed: {key} is blank")
    if content.lstrip().startswith("[占位]"):
        raise DeploymentError(f"input validation failed: {key} is a placeholder")

    matches = list(_PLACEHOLDER_PATTERN.finditer(content))
    names = [match.group(1) for match in matches]
    unmatched = _PLACEHOLDER_PATTERN.sub("", content)
    required = _TEMPLATE_PLACEHOLDERS[key]
    if (
        set(names) != required
        or "{{" in unmatched
        or "}}" in unmatched
    ):
        expected = ", ".join(f"{{{{{name}}}}}" for name in sorted(required))
        raise DeploymentError(
            f"input validation failed: {key} placeholders must be exactly {expected}"
        )


def _read_templates(input_dir: Path) -> dict[str, str]:
    try:
        if not input_dir.is_dir():
            raise DeploymentError(
                f"input validation failed: directory does not exist: {input_dir}"
            )
        files = {
            entry.name: entry
            for entry in input_dir.iterdir()
            if entry.is_file()
        }
    except OSError as exc:
        raise DeploymentError(
            f"input validation failed: cannot read directory {input_dir}: {exc}"
        ) from exc

    expected_names = {f"{key}.txt" for key in TEMPLATE_KEYS}
    actual_names = set(files)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unknown = sorted(actual_names - expected_names)
        raise DeploymentError(
            "input validation failed: template file set is not exact; "
            f"missing={missing or 'none'} unknown={unknown or 'none'}"
        )

    templates: dict[str, str] = {}
    for key in TEMPLATE_KEYS:
        path = files[f"{key}.txt"]
        try:
            content = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise DeploymentError(
                f"input validation failed: {key} is not valid UTF-8"
            ) from exc
        except OSError as exc:
            raise DeploymentError(
                f"input validation failed: cannot read {path}: {exc}"
            ) from exc
        _validate_template_content(key, content)
        templates[key] = content
    return templates


def _response_json(response: httpx.Response, method: str, path: str) -> Any:
    if not 200 <= response.status_code < 300:
        raise DeploymentError(
            f"{method} {path} returned HTTP {response.status_code}"
        )
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DeploymentError(f"{method} {path} returned invalid JSON") from exc


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    payload: Mapping[str, object] | None = None,
) -> Any:
    try:
        response = client.request(method, path, json=payload)
    except httpx.HTTPError as exc:
        raise DeploymentError(f"{method} {path} failed: {exc}") from exc
    return _response_json(response, method, path)


def _read_template_items(value: object, *, method: str, path: str) -> dict[str, str]:
    if not isinstance(value, list):
        raise DeploymentError(f"{method} {path} returned a non-list body")

    items: dict[str, str] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise DeploymentError(f"{method} {path} returned an invalid item")
        key = item.get("key")
        content = item.get("content")
        if not isinstance(key, str) or not isinstance(content, str):
            raise DeploymentError(f"{method} {path} returned an invalid template item")
        if key in items:
            raise DeploymentError(f"{method} {path} returned a duplicate key: {key}")
        items[key] = content

    if set(items) != set(TEMPLATE_KEYS):
        raise DeploymentError(
            f"{method} {path} returned an unexpected key set: "
            f"{sorted(items)}"
        )
    return items


def _read_template_item(value: object, *, key: str, method: str, path: str) -> str:
    if not isinstance(value, Mapping):
        raise DeploymentError(f"{method} {path} returned an invalid object")
    response_key = value.get("key")
    content = value.get("content")
    if response_key != key or not isinstance(content, str):
        raise DeploymentError(
            f"{method} {path} returned an invalid response for {key}"
        )
    return content


def _get_templates(client: httpx.Client, phase: str) -> dict[str, str]:
    try:
        value = _request_json(client, "GET", _TEMPLATE_PATH)
        return _read_template_items(
            value,
            method="GET",
            path=_TEMPLATE_PATH,
        )
    except DeploymentError as exc:
        raise DeploymentError(f"phase={phase} failed: {exc}") from exc


def _patch_template(client: httpx.Client, key: str, content: str) -> None:
    path = f"{_TEMPLATE_PATH}/{key}"
    value = _request_json(client, "PATCH", path, {"content": content})
    response_content = _read_template_item(
        value,
        key=key,
        method="PATCH",
        path=path,
    )
    if response_content != content:
        raise DeploymentError(
            f"PATCH {path} returned content different from the requested body"
        )


def _client(base_url: str) -> httpx.Client:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise DeploymentError("base URL must not be blank")
    try:
        return httpx.Client(
            base_url=normalized,
            follow_redirects=False,
            timeout=_HTTP_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise DeploymentError(f"invalid base URL: {exc}") from exc


def _install(base_url: str, input_dir: Path) -> int:
    templates = _read_templates(input_dir)
    succeeded: list[str] = []
    try:
        with _client(base_url) as client:
            _get_templates(client, "baseline")
            for key in TEMPLATE_KEYS:
                try:
                    _patch_template(client, key, templates[key])
                except DeploymentError as exc:
                    print(
                        "template deployment failed: "
                        f"phase=install succeeded={_format_keys(succeeded)} "
                        f"failed={key} error={exc}",
                        file=sys.stderr,
                    )
                    return 1
                succeeded.append(key)
            final = _get_templates(client, "final verification")
    except DeploymentError as exc:
        print(
            "template deployment failed: "
            f"phase=install succeeded={_format_keys(succeeded)} "
            f"failed=baseline-or-verification error={exc}",
            file=sys.stderr,
        )
        return 1

    mismatches = [key for key in TEMPLATE_KEYS if final[key] != templates[key]]
    if mismatches:
        print(
            "template deployment failed: "
            f"phase=final verification succeeded={_format_keys(succeeded)} "
            f"failed={_format_keys(mismatches)} error=content mismatch",
            file=sys.stderr,
        )
        return 1
    print(f"installed={_format_keys(succeeded)}")
    return 0


def _verify(base_url: str, input_dir: Path) -> int:
    templates = _read_templates(input_dir)
    try:
        with _client(base_url) as client:
            actual = _get_templates(client, "verify")
    except DeploymentError as exc:
        print(
            f"template verification failed: error={exc}",
            file=sys.stderr,
        )
        return 1

    mismatches = [key for key in TEMPLATE_KEYS if actual[key] != templates[key]]
    if mismatches:
        print(
            "template verification failed: "
            f"mismatched={_format_keys(mismatches)} error=content mismatch",
            file=sys.stderr,
        )
        return 1
    print(f"verified={_format_keys(list(TEMPLATE_KEYS))}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deploy_templates")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("install", "verify"), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.mode == "install":
            return _install(arguments.base_url, arguments.input_dir)
        return _verify(arguments.base_url, arguments.input_dir)
    except DeploymentError as exc:
        print(f"template deployment failed: error={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
