from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import ceil, fsum, isfinite
from typing import Literal


AssetType = Literal["character", "scene"]

VIOLATION_CODES = (
    "shots_not_contiguous",
    "shot_already_in_clip",
    "shot_has_multiple_scenes",
    "multiple_scenes",
    "duration_exceeds_max",
    "no_reference_candidates",
)
WARNING_CODES = (
    "duration_below_min",
    "reference_selection_required",
    "enabled_slots_exceed_recommendation",
)


class ClipRuleDataError(ValueError):
    """Raised when persisted shot or asset data violates its database contract."""


@dataclass(frozen=True, slots=True)
class ClipRuleAsset:
    id: int
    type: AssetType
    name: str


@dataclass(frozen=True, slots=True)
class ClipRuleShot:
    id: int
    order_index: int
    duration_est: float
    assets: tuple[ClipRuleAsset, ...] = ()


@dataclass(frozen=True, slots=True)
class ClipRuleMessage:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ClipReferenceCandidate:
    asset_id: int
    asset_type: AssetType
    asset_name: str
    first_shot_id: int
    first_order_index: int
    selected_by_default: bool


@dataclass(frozen=True, slots=True)
class ClipRuleResult:
    shots: tuple[ClipRuleShot, ...]
    duration_est_total: float
    suggested_requested_duration: int
    reference_candidates: tuple[ClipReferenceCandidate, ...]
    default_reference_asset_ids: tuple[int, ...]
    violations: tuple[ClipRuleMessage, ...]
    warnings: tuple[ClipRuleMessage, ...]


def normalize_shots(shots: Sequence[ClipRuleShot]) -> tuple[ClipRuleShot, ...]:
    return tuple(sorted(shots, key=lambda shot: (shot.order_index, shot.id)))


def slot_warnings(
    *, enabled_slot_count: int, slot_soft_limit: int
) -> tuple[ClipRuleMessage, ...]:
    if enabled_slot_count > slot_soft_limit:
        return (
            ClipRuleMessage(
                code="enabled_slots_exceed_recommendation",
                message=f"建议 {slot_soft_limit} 张以内",
            ),
        )
    return ()


def evaluate_clip_selection(
    shots: Sequence[ClipRuleShot],
    *,
    occupied_shot_ids: Collection[int] = (),
    clip_min_seconds: int,
    clip_max_seconds: int,
    slot_soft_limit: int,
    slot_hard_limit: int,
    enabled_slot_count: int | None = None,
) -> ClipRuleResult:
    _validate_limits(
        clip_min_seconds=clip_min_seconds,
        clip_max_seconds=clip_max_seconds,
        slot_soft_limit=slot_soft_limit,
        slot_hard_limit=slot_hard_limit,
    )
    normalized_shots = normalize_shots(shots)
    durations = tuple(_validated_duration(shot) for shot in normalized_shots)
    duration_total = fsum(durations)
    suggested_duration = min(
        clip_max_seconds, max(clip_min_seconds, ceil(duration_total))
    )

    violations: list[ClipRuleMessage] = []
    order_indexes = tuple(shot.order_index for shot in normalized_shots)
    if any(
        current - previous != 1
        for previous, current in zip(order_indexes, order_indexes[1:])
    ):
        violations.append(
            ClipRuleMessage(
                code="shots_not_contiguous",
                message="Selected shots must have consecutive order indexes.",
            )
        )

    occupied = sorted(
        shot.id for shot in normalized_shots if shot.id in set(occupied_shot_ids)
    )
    if occupied:
        occupied_text = ", ".join(str(shot_id) for shot_id in occupied)
        violations.append(
            ClipRuleMessage(
                code="shot_already_in_clip",
                message=f"Shots already belong to a clip: {occupied_text}.",
            )
        )

    scene_ids_by_shot: list[tuple[int, tuple[int, ...]]] = []
    for shot in normalized_shots:
        scene_ids = tuple(
            sorted(
                {
                    asset.id
                    for asset in shot.assets
                    if asset.type == "scene"
                }
            )
        )
        scene_ids_by_shot.append((shot.id, scene_ids))
        if len(scene_ids) > 1:
            violations.append(
                ClipRuleMessage(
                    code="shot_has_multiple_scenes",
                    message=(
                        f"Shot {shot.id} is bound to more than one scene asset."
                    ),
                )
            )

    all_scene_ids = {scene_id for _, scene_ids in scene_ids_by_shot for scene_id in scene_ids}
    if len(all_scene_ids) > 1:
        violations.append(
            ClipRuleMessage(
                code="multiple_scenes",
                message="Selected shots reference more than one scene asset.",
            )
        )

    if duration_total > clip_max_seconds:
        violations.append(
            ClipRuleMessage(
                code="duration_exceeds_max",
                message=(
                    "Estimated duration exceeds the maximum of "
                    f"{clip_max_seconds} seconds."
                ),
            )
        )

    candidates = _build_candidates(normalized_shots, slot_hard_limit)
    if not candidates:
        violations.append(
            ClipRuleMessage(
                code="no_reference_candidates",
                message="Selected shots have no character or scene reference assets.",
            )
        )

    warnings: list[ClipRuleMessage] = []
    if duration_total < clip_min_seconds:
        warnings.append(
            ClipRuleMessage(
                code="duration_below_min",
                message=(
                    "Estimated duration is below the minimum of "
                    f"{clip_min_seconds} seconds."
                ),
            )
        )
    if len(candidates) > slot_hard_limit:
        warnings.append(
            ClipRuleMessage(
                code="reference_selection_required",
                message=(
                    "Select a reference asset subset of at most "
                    f"{slot_hard_limit} assets to create the clip."
                ),
            )
        )
    selected_count = (
        len(candidates[:slot_hard_limit])
        if enabled_slot_count is None
        else enabled_slot_count
    )
    warnings.extend(
        slot_warnings(
            enabled_slot_count=selected_count,
            slot_soft_limit=slot_soft_limit,
        )
    )

    default_ids = tuple(candidate.asset_id for candidate in candidates[:slot_hard_limit])
    return ClipRuleResult(
        shots=normalized_shots,
        duration_est_total=duration_total,
        suggested_requested_duration=suggested_duration,
        reference_candidates=tuple(candidates),
        default_reference_asset_ids=default_ids,
        violations=tuple(violations),
        warnings=tuple(warnings),
    )


def _validate_limits(
    *,
    clip_min_seconds: int,
    clip_max_seconds: int,
    slot_soft_limit: int,
    slot_hard_limit: int,
) -> None:
    if clip_min_seconds <= 0 or clip_max_seconds <= 0:
        raise ValueError("clip duration limits must be positive")
    if clip_min_seconds > clip_max_seconds:
        raise ValueError("clip minimum must not exceed clip maximum")
    if not 1 <= slot_hard_limit <= 9:
        raise ValueError("slot hard limit must be between 1 and 9")
    if not 1 <= slot_soft_limit <= slot_hard_limit:
        raise ValueError("slot soft limit must be between 1 and the hard limit")


def _validated_duration(shot: ClipRuleShot) -> float:
    duration = shot.duration_est
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ClipRuleDataError(
            f"Shot {shot.id} has an invalid duration_est value."
        )
    duration_value = float(duration)
    if not isfinite(duration_value) or not 1 <= duration_value <= 5:
        raise ClipRuleDataError(
            f"Shot {shot.id} has an invalid duration_est value."
        )
    return duration_value


def _build_candidates(
    normalized_shots: Sequence[ClipRuleShot], slot_hard_limit: int
) -> list[ClipReferenceCandidate]:
    first_seen: dict[int, tuple[ClipRuleAsset, int, int]] = {}
    for position, shot in enumerate(normalized_shots, start=1):
        for asset in shot.assets:
            if asset.type not in ("character", "scene"):
                raise ClipRuleDataError(
                    f"Asset {asset.id} has an invalid clip reference type."
                )
            existing = first_seen.get(asset.id)
            if existing is None:
                first_seen[asset.id] = (asset, position, shot.order_index)
            elif existing[0].type != asset.type or existing[0].name != asset.name:
                raise ClipRuleDataError(
                    f"Asset {asset.id} has inconsistent clip reference data."
                )

    ordered = sorted(
        first_seen.values(),
        key=lambda item: (
            1 if item[0].type == "scene" else 0,
            item[1],
            item[0].id,
        ),
    )
    default_ids = {item[0].id for item in ordered[:slot_hard_limit]}
    return [
        ClipReferenceCandidate(
            asset_id=asset.id,
            asset_type=asset.type,
            asset_name=asset.name,
            first_shot_id=normalized_shots[position - 1].id,
            first_order_index=order_index,
            selected_by_default=asset.id in default_ids,
        )
        for asset, position, order_index in ordered
    ]
