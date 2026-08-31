import math

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.clip_rules import (
    ClipRuleAsset,
    ClipRuleDataError,
    ClipRuleShot,
    evaluate_clip_selection,
)


def _shot(
    shot_id: int,
    order_index: int,
    duration: float,
    *assets: tuple[int, str, str],
) -> ClipRuleShot:
    return ClipRuleShot(
        id=shot_id,
        order_index=order_index,
        duration_est=duration,
        assets=tuple(ClipRuleAsset(id=asset_id, type=asset_type, name=name) for asset_id, asset_type, name in assets),
    )


def _evaluate(shots: list[ClipRuleShot], **kwargs: object):
    return evaluate_clip_selection(
        shots,
        clip_min_seconds=5,
        clip_max_seconds=15,
        slot_soft_limit=4,
        slot_hard_limit=9,
        **kwargs,
    )


def test_normalizes_shots_and_sorts_candidates_by_first_appearance() -> None:
    result = _evaluate(
        [
            _shot(12, 2, 2, (20, "scene", "屋内"), (4, "character", "乙")),
            _shot(11, 1, 2, (8, "character", "甲"), (4, "character", "乙")),
        ]
    )

    assert [shot.id for shot in result.shots] == [11, 12]
    assert [candidate.asset_id for candidate in result.reference_candidates] == [4, 8, 20]
    assert [(candidate.first_shot_id, candidate.first_order_index) for candidate in result.reference_candidates] == [
        (11, 1),
        (11, 1),
        (12, 2),
    ]
    assert result.default_reference_asset_ids == (4, 8, 20)


def test_all_closed_rule_codes_and_warning_order_are_emitted() -> None:
    result = _evaluate(
        [
            _shot(1, 1, 1, (10, "scene", "一"), (11, "scene", "二")),
            _shot(2, 3, 1, (12, "character", "人")),
        ],
        occupied_shot_ids={2},
    )

    assert [item.code for item in result.violations] == [
        "shots_not_contiguous",
        "shot_already_in_clip",
        "shot_has_multiple_scenes",
        "multiple_scenes",
    ]
    assert [item.code for item in result.warnings] == ["duration_below_min"]
    assert all(item.message for item in (*result.violations, *result.warnings))

    over_max = _evaluate(
        [
            _shot(index, index, 5, (10, "character", "人"))
            for index in range(1, 5)
        ]
    )
    assert [item.code for item in over_max.violations] == ["duration_exceeds_max"]

    no_candidates = _evaluate([_shot(1, 1, 1)])
    assert [item.code for item in no_candidates.violations] == ["no_reference_candidates"]


def test_duration_is_not_rounded_and_suggestion_ceil_clamps() -> None:
    result = _evaluate([_shot(1, 1, 2.2), _shot(2, 2, 2.2)])
    assert result.duration_est_total == pytest.approx(4.4)
    assert result.suggested_requested_duration == 5

    low = _evaluate([_shot(1, 1, 1)])
    assert low.suggested_requested_duration == 5

    high = _evaluate(
        [_shot(index, index, 5, (10, "character", "人")) for index in range(1, 5)]
    )
    assert high.duration_est_total == pytest.approx(20)
    assert high.suggested_requested_duration == 15
    assert [item.code for item in high.violations] == ["duration_exceeds_max"]


def test_candidate_hard_limit_is_a_warning_and_a_legal_subset_remains_selectable() -> None:
    shots = [
        _shot(1, 1, 2, *[(asset_id, "character", str(asset_id)) for asset_id in range(1, 11)])
    ]
    result = evaluate_clip_selection(
        shots,
        clip_min_seconds=1,
        clip_max_seconds=15,
        slot_soft_limit=2,
        slot_hard_limit=3,
    )

    assert result.default_reference_asset_ids == (1, 2, 3)
    assert [item.code for item in result.warnings] == [
        "reference_selection_required",
        "enabled_slots_exceed_recommendation",
    ]
    assert "建议 2 张以内" in result.warnings[-1].message
    assert all(candidate.selected_by_default == (candidate.asset_id <= 3) for candidate in result.reference_candidates)


def test_enabled_slot_warning_uses_actual_enabled_count() -> None:
    result = evaluate_clip_selection(
        [_shot(1, 1, 5, (1, "character", "人"))],
        clip_min_seconds=5,
        clip_max_seconds=15,
        slot_soft_limit=1,
        slot_hard_limit=3,
        enabled_slot_count=2,
    )
    assert [item.code for item in result.warnings] == [
        "enabled_slots_exceed_recommendation"
    ]


@pytest.mark.parametrize("value", [0, 10])
def test_settings_rejects_hard_limit_outside_absolute_database_range(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(SLOT_HARD_LIMIT=value)


def test_settings_rejects_soft_limit_above_hard_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(SLOT_HARD_LIMIT=3, SLOT_SOFT_LIMIT=4)


@pytest.mark.parametrize("duration", [0, -1, math.inf, math.nan, 6])
def test_invalid_persisted_duration_is_not_replaced(duration: float) -> None:
    with pytest.raises(ClipRuleDataError):
        _evaluate([_shot(1, 1, duration)])
