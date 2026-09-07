import type { ClipFreshness, ClipGenerationState } from "../../api/clips";
import type { ShotStatus } from "../../api/shots";

export interface StatusBadgePresentation {
  label: string;
  className: string;
}

const SHOT_STATUS_PRESENTATIONS = {
  normal: null,
  changed: {
    label: "已变更（changed）",
    className: "shot-badge-changed",
  },
} satisfies Record<ShotStatus, StatusBadgePresentation | null>;

const CLIP_GENERATION_PRESENTATIONS = {
  empty: {
    label: "未生成（empty）",
    className: "director-generation-empty",
  },
  queued: {
    label: "排队中（queued）",
    className: "director-generation-queued",
  },
  generating: {
    label: "生成中（generating）",
    className: "director-generation-generating",
  },
  ready: {
    label: "可用（ready）",
    className: "director-generation-ready",
  },
  failed: {
    label: "失败（failed）",
    className: "director-generation-failed",
  },
} satisfies Record<ClipGenerationState, StatusBadgePresentation>;

const CLIP_FRESHNESS_PRESENTATIONS = {
  fresh: null,
  stale: {
    label: "待更新（stale）",
    className: "director-freshness-stale",
  },
} satisfies Record<ClipFreshness, StatusBadgePresentation | null>;

export function presentShotStatus(
  status: ShotStatus,
): StatusBadgePresentation | null {
  return SHOT_STATUS_PRESENTATIONS[status];
}

export function presentClipGenerationState(
  state: ClipGenerationState,
): StatusBadgePresentation {
  return CLIP_GENERATION_PRESENTATIONS[state];
}

export function presentClipFreshness(
  freshness: ClipFreshness,
): StatusBadgePresentation | null {
  return CLIP_FRESHNESS_PRESENTATIONS[freshness];
}
