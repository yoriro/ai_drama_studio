from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import tomli


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BINDING_PATH = _BACKEND_ROOT / "workflows" / "bindings.toml"
_NODE_ID = re.compile(r"^[0-9]+$")
_PATH_FORBIDDEN = frozenset("*[]|?")


class WorkflowBindingError(ValueError):
    """Raised when the Z-Image binding or API workflow is invalid."""


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True, slots=True)
class WorkflowBindingSnapshot:
    """Validated Z-Image binding and a read-only workflow snapshot."""

    name: str
    workflow_path: Path
    workflow_hash: str
    prompt_path: str
    seed_path: str
    output_node: str
    definition: Mapping[str, Any]

    @property
    def hash(self) -> str:
        """Return the workflow hash used in the task payload contract."""

        return self.workflow_hash

    def workflow_payload(self) -> dict[str, Any]:
        """Return a detached workflow object for a task payload or injection."""

        return {
            "name": self.name,
            "hash": self.workflow_hash,
            "prompt_path": self.prompt_path,
            "seed_path": self.seed_path,
            "output_node": self.output_node,
            "definition": _thaw_json(self.definition),
        }


def _require_mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowBindingError(f"{context} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], context: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        suffix = ": " + "; ".join(details) if details else ""
        raise WorkflowBindingError(f"{context} has invalid fields{suffix}")


def _require_non_empty_string(
    value: object, context: str
) -> str:
    if not isinstance(value, str) or not value:
        raise WorkflowBindingError(f"{context} must be a non-empty string")
    return value


def _resolve_object_path(
    workflow: Mapping[str, Any], path: str, context: str
) -> object:
    segments = path.split(".")
    if any(
        not segment or any(character in segment for character in _PATH_FORBIDDEN)
        for segment in segments
    ):
        raise WorkflowBindingError(
            f"{context} must use exact dot-separated object keys"
        )

    current: object = workflow
    for segment in segments:
        if not isinstance(current, Mapping):
            raise WorkflowBindingError(
                f"{context} traverses a non-object at segment {segment}"
            )
        if segment not in current:
            raise WorkflowBindingError(
                f"{context} does not exist at segment {segment}"
            )
        current = current[segment]
    return current


def _read_binding(binding_path: Path) -> Mapping[str, Any]:
    try:
        with binding_path.open("rb") as binding_file:
            parsed = tomli.load(binding_file)
    except FileNotFoundError as exc:
        raise WorkflowBindingError(
            f"workflow binding file does not exist: {binding_path}"
        ) from exc
    except OSError as exc:
        raise WorkflowBindingError(
            f"workflow binding file cannot be read: {binding_path}"
        ) from exc
    except tomli.TOMLDecodeError as exc:
        raise WorkflowBindingError(
            f"workflow binding TOML is invalid: {binding_path}"
        ) from exc
    return _require_mapping(parsed, "workflow binding")


def _read_workflow(workflow_path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = workflow_path.read_bytes()
    except FileNotFoundError as exc:
        raise WorkflowBindingError(
            f"workflow file does not exist: {workflow_path}"
        ) from exc
    except OSError as exc:
        raise WorkflowBindingError(
            f"workflow file cannot be read: {workflow_path}"
        ) from exc

    workflow_hash = hashlib.sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowBindingError(
            f"workflow JSON is invalid: {workflow_path}"
        ) from exc
    if not isinstance(parsed, dict) or not parsed:
        raise WorkflowBindingError(
            f"workflow must be a non-empty API object: {workflow_path}"
        )
    if "nodes" in parsed or "links" in parsed:
        raise WorkflowBindingError(
            f"workflow is a UI graph, not an API object: {workflow_path}"
        )

    for node_id, node in parsed.items():
        if not isinstance(node_id, str) or _NODE_ID.fullmatch(node_id) is None:
            raise WorkflowBindingError(
                f"workflow node id must be numeric: {node_id!r}"
            )
        node_object = _require_mapping(node, f"workflow node {node_id}")
        class_type = node_object.get("class_type")
        if not isinstance(class_type, str) or not class_type.strip():
            raise WorkflowBindingError(
                f"workflow node {node_id} class_type must be non-empty"
            )
        if not isinstance(node_object.get("inputs"), Mapping):
            raise WorkflowBindingError(
                f"workflow node {node_id} inputs must be an object"
            )
    return parsed, workflow_hash


def _resolve_workflow_path(
    backend_root: Path, workflow_value: str, binding_path: Path
) -> Path:
    relative_path = Path(workflow_value)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise WorkflowBindingError(
            f"workflow path must be relative to backend: {binding_path}"
        )
    backend_root = backend_root.resolve()
    workflow_path = (backend_root / relative_path).resolve()
    try:
        workflow_path.relative_to(backend_root)
    except ValueError as exc:
        raise WorkflowBindingError(
            f"workflow path escapes backend directory: {binding_path}"
        ) from exc
    return workflow_path


def load_binding_snapshot(
    binding_path: str | Path = DEFAULT_BINDING_PATH,
    *,
    backend_root: str | Path | None = None,
) -> WorkflowBindingSnapshot:
    """Load, validate, and snapshot the single configured Z-Image workflow."""

    resolved_binding_path = Path(binding_path).resolve()
    binding = _read_binding(resolved_binding_path)
    _require_exact_keys(binding, {"comfy"}, "workflow binding")
    comfy = _require_mapping(binding["comfy"], "workflow binding comfy")
    _require_exact_keys(comfy, {"zimage"}, "workflow binding comfy")
    zimage = _require_mapping(comfy["zimage"], "workflow binding comfy.zimage")
    _require_exact_keys(
        zimage,
        {"workflow", "prompt_path", "seed_path", "output_node"},
        "workflow binding comfy.zimage",
    )

    workflow_value = _require_non_empty_string(
        zimage["workflow"], "workflow binding workflow"
    )
    prompt_path = _require_non_empty_string(
        zimage["prompt_path"], "workflow binding prompt_path"
    )
    seed_path = _require_non_empty_string(
        zimage["seed_path"], "workflow binding seed_path"
    )
    output_node = _require_non_empty_string(
        zimage["output_node"], "workflow binding output_node"
    )
    if _NODE_ID.fullmatch(output_node) is None:
        raise WorkflowBindingError("workflow binding output_node must be a node id")

    root = _BACKEND_ROOT if backend_root is None else Path(backend_root)
    workflow_path = _resolve_workflow_path(root, workflow_value, resolved_binding_path)
    workflow, workflow_hash = _read_workflow(workflow_path)
    prompt_value = _resolve_object_path(workflow, prompt_path, "prompt_path")
    if not isinstance(prompt_value, str):
        raise WorkflowBindingError("prompt_path leaf must be a string")
    seed_value = _resolve_object_path(workflow, seed_path, "seed_path")
    if isinstance(seed_value, bool) or not isinstance(seed_value, int):
        raise WorkflowBindingError("seed_path leaf must be an integer")
    if output_node not in workflow:
        raise WorkflowBindingError(
            f"output_node does not exist in workflow: {output_node}"
        )

    return WorkflowBindingSnapshot(
        name="zimage",
        workflow_path=workflow_path,
        workflow_hash=workflow_hash,
        prompt_path=prompt_path,
        seed_path=seed_path,
        output_node=output_node,
        definition=_freeze_json(workflow),
    )
