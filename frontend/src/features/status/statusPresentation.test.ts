import { describe, expect, it } from "vitest";

import {
  presentClipFreshness,
  presentClipGenerationState,
  presentShotStatus,
} from "./statusPresentation";

describe("status presentation", () => {
  it("only presents the changed shot badge for changed shots", () => {
    expect(presentShotStatus("normal")).toBeNull();
    expect(presentShotStatus("changed")).toEqual({
      label: "已变更（changed）",
      className: "shot-badge-changed",
    });
  });

  it.each([
    ["empty", "未生成（empty）", "director-generation-empty"],
    ["queued", "排队中（queued）", "director-generation-queued"],
    ["generating", "生成中（generating）", "director-generation-generating"],
    ["ready", "可用（ready）", "director-generation-ready"],
    ["failed", "失败（failed）", "director-generation-failed"],
  ] as const)(
    "presents the %s generation state",
    (state, label, className) => {
      expect(presentClipGenerationState(state)).toEqual({ label, className });
    },
  );

  it("keeps freshness independent from generation state", () => {
    expect(presentClipFreshness("fresh")).toBeNull();
    expect(presentClipFreshness("stale")).toEqual({
      label: "待更新（stale）",
      className: "director-freshness-stale",
    });

    for (const state of ["empty", "queued", "generating", "ready", "failed"] as const) {
      for (const freshness of ["fresh", "stale"] as const) {
        expect(presentClipGenerationState(state).label).toContain(state);
        const freshnessBadge = presentClipFreshness(freshness);
        if (freshness === "fresh") {
          expect(freshnessBadge).toBeNull();
        } else {
          expect(freshnessBadge?.label).toBe("待更新（stale）");
        }
      }
    }
  });
});
