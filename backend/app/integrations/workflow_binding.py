from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import tomli


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BINDING_PATH = _BACKEND_ROOT / "workflows" / "bindings.toml"
DEFAULT_MINIMAX_BINDING_PATH = _BACKEND_ROOT / "workflows" / "minimaxh3.toml"
_NODE_ID = re.compile(r"^[0-9]+$")
_PATH_FORBIDDEN = frozenset("*[]|?")
_MINIMAX_REFERENCE_COUNT = 9


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


@dataclass(frozen=True, slots=True)
class MiniMaxWorkflowBindingSnapshot:
    """Validated MiniMax H3 binding and a read-only workflow snapshot."""

    name: str
    workflow_path: Path
    workflow_hash: str
    prompt_path: str
    seed_path: str
    duration_path: str
    ref_image_paths: tuple[str, ...]
    ref_consumer_paths: tuple[str, ...]
    optional_refs: bool
    output_node: str
    definition: Mapping[str, Any]

    @property
    def hash(self) -> str:
        """Return the raw workflow hash used by the input contract."""

        return self.workflow_hash

    def workflow_payload(self) -> dict[str, Any]:
        """Return a detached workflow object for injection."""

        return {
            "name": self.name,
            "hash": self.workflow_hash,
            "prompt_path": self.prompt_path,
            "seed_path": self.seed_path,
            "duration_path": self.duration_path,
            "ref_image_paths": list(self.ref_image_paths),
            "ref_consumer_paths": list(self.ref_consumer_paths),
            "optional_refs": self.optional_refs,
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


def _resolve_minimax_path(
    workflow: Mapping[str, Any], path: str, context: str
) -> object:
    """Resolve an API workflow input path with Comfy's dotted input keys."""

    segments = path.split(".")
    if any(
        not segment or any(character in segment for character in _PATH_FORBIDDEN)
        for segment in segments
    ):
        raise WorkflowBindingError(
            f"{context} must use exact dot-separated object keys"
        )
    if len(segments) < 3:
        raise WorkflowBindingError(f"{context} must include node.inputs.path")

    inputs = _resolve_object_path(
        workflow, f"{segments[0]}.inputs", context
    )
    if not isinstance(inputs, Mapping):
        raise WorkflowBindingError(f"{context} inputs must be an object")
    input_key = ".".join(segments[2:])
    if input_key not in inputs:
        raise WorkflowBindingError(
            f"{context} does not exist at input {input_key}"
        )
    return inputs[input_key]


def _require_minimax_path_list(
    value: object, context: str
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != _MINIMAX_REFERENCE_COUNT:
        raise WorkflowBindingError(
            f"{context} must contain exactly {_MINIMAX_REFERENCE_COUNT} paths"
        )
    paths = tuple(
        _require_non_empty_string(item, f"{context}[{index}]")
        for index, item in enumerate(value)
    )
    if len(set(paths)) != _MINIMAX_REFERENCE_COUNT:
        raise WorkflowBindingError(f"{context} paths must be unique")
    return paths


def load_minimax_binding_snapshot(
    binding_path: str | Path = DEFAULT_MINIMAX_BINDING_PATH,
    *,
    backend_root: str | Path | None = None,
) -> MiniMaxWorkflowBindingSnapshot:
    """Load and validate the independent MiniMax H3 workflow binding."""

    resolved_binding_path = Path(binding_path).resolve()
    binding = _read_binding(resolved_binding_path)
    _require_exact_keys(binding, {"comfy"}, "workflow binding")
    comfy = _require_mapping(binding["comfy"], "workflow binding comfy")
    _require_exact_keys(comfy, {"minimaxh3"}, "workflow binding comfy")
    minimax = _require_mapping(
        comfy["minimaxh3"], "workflow binding comfy.minimaxh3"
    )
    _require_exact_keys(
        minimax,
        {
            "workflow",
            "prompt_path",
            "seed_path",
            "duration_path",
            "ref_image_paths",
            "ref_consumer_paths",
            "optional_refs",
            "output_node",
        },
        "workflow binding comfy.minimaxh3",
    )

    workflow_value = _require_non_empty_string(
        minimax["workflow"], "workflow binding workflow"
    )
    prompt_path = _require_non_empty_string(
        minimax["prompt_path"], "workflow binding prompt_path"
    )
    seed_path = _require_non_empty_string(
        minimax["seed_path"], "workflow binding seed_path"
    )
    duration_path = _require_non_empty_string(
        minimax["duration_path"], "workflow binding duration_path"
    )
    output_node = _require_non_empty_string(
        minimax["output_node"], "workflow binding output_node"
    )
    if _NODE_ID.fullmatch(output_node) is None:
        raise WorkflowBindingError("workflow binding output_node must be a node id")
    optional_refs = minimax["optional_refs"]
    if optional_refs is not False:
        raise WorkflowBindingError("workflow binding optional_refs must be false")

    ref_image_paths = _require_minimax_path_list(
        minimax["ref_image_paths"], "workflow binding ref_image_paths"
    )
    ref_consumer_paths = _require_minimax_path_list(
        minimax["ref_consumer_paths"], "workflow binding ref_consumer_paths"
    )

    root = _BACKEND_ROOT if backend_root is None else Path(backend_root)
    workflow_path = _resolve_workflow_path(
        root, workflow_value, resolved_binding_path
    )
    workflow, workflow_hash = _read_workflow(workflow_path)

    prompt_value = _resolve_minimax_path(
        workflow, prompt_path, "prompt_path"
    )
    if not isinstance(prompt_value, str):
        raise WorkflowBindingError("prompt_path leaf must be a string")
    seed_value = _resolve_minimax_path(workflow, seed_path, "seed_path")
    if isinstance(seed_value, bool) or not isinstance(seed_value, int):
        raise WorkflowBindingError("seed_path leaf must be an integer")
    duration_value = _resolve_minimax_path(
        workflow, duration_path, "duration_path"
    )
    if isinstance(duration_value, bool) or not isinstance(
        duration_value, (int, float)
    ) or not math.isfinite(float(duration_value)):
        raise WorkflowBindingError(
            "duration_path leaf must be a finite number"
        )
    if output_node not in workflow:
        raise WorkflowBindingError(
            f"output_node does not exist in workflow: {output_node}"
        )
    output = _require_mapping(workflow[output_node], f"workflow node {output_node}")
    if output.get("class_type") != "VHS_VideoCombine":
        raise WorkflowBindingError(
            "output_node must reference a VHS_VideoCombine node"
        )

    for index, (image_path, consumer_path) in enumerate(
        zip(ref_image_paths, ref_consumer_paths, strict=True)
    ):
        image_value = _resolve_minimax_path(
            workflow, image_path, f"ref_image_paths[{index}]"
        )
        image_segments = image_path.split(".")
        image_node_id = image_segments[0]
        image_node = _require_mapping(
            workflow.get(image_node_id),
            f"workflow node {image_node_id}",
        )
        if image_node.get("class_type") != "LoadImage":
            raise WorkflowBindingError(
                f"ref_image_paths[{index}] must reference a LoadImage node"
            )
        expected_sentinel = f"__C009_REFERENCE_{index + 1:02d}__.png"
        if image_value != expected_sentinel:
            raise WorkflowBindingError(
                f"ref_image_paths[{index}] must use the C009 reference sentinel"
            )

        consumer_segments = consumer_path.split(".")
        expected_consumer_key = f"ref_image_{index}"
        if consumer_segments[1:] != [
            "inputs",
            "ref_images",
            expected_consumer_key,
        ]:
            raise WorkflowBindingError(
                f"ref_consumer_paths[{index}] has an invalid H3 input path"
            )
        consumer_value = _resolve_minimax_path(
            workflow, consumer_path, f"ref_consumer_paths[{index}]"
        )
        consumer_node_id = consumer_segments[0]
        consumer_node = _require_mapping(
            workflow.get(consumer_node_id),
            f"workflow node {consumer_node_id}",
        )
        if consumer_node.get("class_type") != "MiniMaxH3ReferenceToVideo":
            raise WorkflowBindingError(
                f"ref_consumer_paths[{index}] must reference the H3 consumer"
            )
        if (
            not isinstance(consumer_value, list)
            or len(consumer_value) != 2
            or consumer_value[0] != image_node_id
            or isinstance(consumer_value[1], bool)
            or consumer_value[1] != 0
        ):
            raise WorkflowBindingError(
                f"ref_consumer_paths[{index}] is not linked to its image node"
            )

    return MiniMaxWorkflowBindingSnapshot(
        name="minimaxh3",
        workflow_path=workflow_path,
        workflow_hash=workflow_hash,
        prompt_path=prompt_path,
        seed_path=seed_path,
        duration_path=duration_path,
        ref_image_paths=ref_image_paths,
        ref_consumer_paths=ref_consumer_paths,
        optional_refs=False,
        output_node=output_node,
        definition=_freeze_json(workflow),
    )
