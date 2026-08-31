from __future__ import annotations

from app.core.config import Settings
from app.services.clip_rules import (
    ClipRuleAsset,
    ClipRuleShot,
    evaluate_clip_selection,
)


def test_c008_non_default_settings_drive_selection_and_warning_boundaries() -> None:
    configured = Settings(SLOT_SOFT_LIMIT=3, SLOT_HARD_LIMIT=6)
    assert configured.SLOT_SOFT_LIMIT == 3
    assert configured.SLOT_HARD_LIMIT == 6

    shot = ClipRuleShot(
        id=1,
        order_index=1,
        duration_est=5,
        assets=tuple(
            ClipRuleAsset(id=asset_id, type="character", name=f"asset-{asset_id}")
            for asset_id in range(1, 8)
        ),
    )

    at_soft_limit = evaluate_clip_selection(
        [shot],
        clip_min_seconds=5,
        clip_max_seconds=15,
        slot_soft_limit=configured.SLOT_SOFT_LIMIT,
        slot_hard_limit=configured.SLOT_HARD_LIMIT,
        enabled_slot_count=configured.SLOT_SOFT_LIMIT,
    )
    assert len(at_soft_limit.reference_candidates) == 7
    assert at_soft_limit.default_reference_asset_ids == (1, 2, 3, 4, 5, 6)
    assert [
        candidate.selected_by_default
        for candidate in at_soft_limit.reference_candidates
    ] == [True, True, True, True, True, True, False]
    assert [item.code for item in at_soft_limit.warnings] == [
        "reference_selection_required"
    ]

    above_soft_limit = evaluate_clip_selection(
        [shot],
        clip_min_seconds=5,
        clip_max_seconds=15,
        slot_soft_limit=configured.SLOT_SOFT_LIMIT,
        slot_hard_limit=configured.SLOT_HARD_LIMIT,
        enabled_slot_count=configured.SLOT_SOFT_LIMIT + 1,
    )
    assert [item.code for item in above_soft_limit.warnings] == [
        "reference_selection_required",
        "enabled_slots_exceed_recommendation",
    ]
