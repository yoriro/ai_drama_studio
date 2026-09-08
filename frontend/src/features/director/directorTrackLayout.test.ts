import { describe, expect, it } from "vitest";

import { calculateDirectorTrackContentWidth } from "./directorTrackLayout";

describe("calculateDirectorTrackContentWidth", () => {
  it("returns zero for an empty track", () => {
    expect(calculateDirectorTrackContentWidth([])).toBe(0);
  });

  it("uses the minimum column width for a single shot", () => {
    expect(calculateDirectorTrackContentWidth([3])).toBe(192);
  });

  it("keeps unequal duration ratios and the shared gap", () => {
    expect(calculateDirectorTrackContentWidth([1, 2, 4])).toBe(1360);
  });

  it("adds every column and gap to the common width", () => {
    expect(calculateDirectorTrackContentWidth([2, 2, 2, 2])).toBe(792);
  });

  it("preserves decimal duration proportions", () => {
    expect(calculateDirectorTrackContentWidth([0.5, 1.25])).toBe(680);
  });

  it("rounds fractional widths up to preserve the minimum CSS pixel", () => {
    expect(calculateDirectorTrackContentWidth([1.4, 1.4, 1.8])).toBe(647);
  });
});
