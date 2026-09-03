import { describe, expect, it } from "vitest";

import type { ClipPreviewResponse } from "../../api/clips";
import {
  applyDirectorPreview,
  buildDirectorProjection,
  clearDirectorPreview,
  createDirectorPreviewState,
  DirectorProjectionError,
  failDirectorPreview,
  getClipStatusToken,
  invalidateDirectorPreview,
  preserveDirectorPreviewAfterCreateError,
  projectClipCreateRequest,
  projectDirectorClipSettingsPatch,
  projectDirectorGenerationGate,
  projectReferenceSelection,
  projectShotSelection,
  parseDirectorRequestedDuration,
  createDirectorClipSettingsDraft,
  startDirectorPreview,
  updateDirectorClipSettingsDraft,
  type DirectorAsset,
  type DirectorClip,
  type DirectorShot,
} from "./directorModel";

function shot(overrides: Partial<DirectorShot> = {}): DirectorShot {
  return {
    id: 1,
    order_index: 1,
    duration_est: 1,
    shot_type: "远景",
    asset_ids: [],
    status: "normal",
    ...overrides,
  };
}

function clip(overrides: Partial<DirectorClip> = {}): DirectorClip {
  return {
    id: 1,
    shot_ids: [1],
    generation_state: "empty",
    freshness: "fresh",
    ...overrides,
  };
}

function sceneAsset(id: number, name: string): DirectorAsset {
  return { id, type: "scene", name };
}

function projection(
  shots: readonly DirectorShot[],
  assets: readonly DirectorAsset[] = [],
  clips: readonly DirectorClip[] = [],
) {
  return buildDirectorProjection({ shots, assets, clips });
}

function expectProjectionError(
  action: () => unknown,
  code: DirectorProjectionError["code"],
  message: string,
): void {
  let thrown: unknown = null;
  try {
    action();
  } catch (error: unknown) {
    thrown = error;
  }
  expect(thrown).toBeInstanceOf(DirectorProjectionError);
  expect(thrown).toMatchObject({ code, message });
}

describe("Director projection", () => {
  it("builds canonical shared columns and merges adjacent scene bands", () => {
    const result = projection(
      [
        shot({ id: 20, order_index: 3, duration_est: 5, asset_ids: [101] }),
        shot({
          id: 10,
          order_index: 1,
          duration_est: 1,
          status: "changed",
        }),
        shot({ id: 11, order_index: 2, duration_est: 2, asset_ids: [101] }),
        shot({ id: 21, order_index: 4, duration_est: 1, asset_ids: [102] }),
      ],
      [sceneAsset(101, "室内"), sceneAsset(102, "街道")],
    );

    expect(result.shots.map(({ shot: item }) => item.id)).toEqual([10, 11, 20, 21]);
    expect(result.gridColumns.map((column) => column.template)).toEqual([
      "1fr",
      "2fr",
      "5fr",
      "1fr",
    ]);
    expect(result.gridTemplateColumns).toBe("1fr 2fr 5fr 1fr");
    expect(result.shots[0].shot.status).toBe("changed");
    expect(result.sceneBands).toEqual([
      {
        startIndex: 0,
        endIndex: 0,
        shotIds: [10],
        classification: {
          kind: "unbound",
          key: "unbound",
          sceneIds: [],
          sceneNames: [],
          label: "未绑定场景",
          paletteIndex: null,
        },
      },
      {
        startIndex: 1,
        endIndex: 2,
        shotIds: [11, 20],
        classification: {
          kind: "scene",
          key: "scene:101",
          sceneIds: [101],
          sceneNames: ["室内"],
          label: "室内",
          paletteIndex: 5,
        },
      },
      {
        startIndex: 3,
        endIndex: 3,
        shotIds: [21],
        classification: {
          kind: "scene",
          key: "scene:102",
          sceneIds: [102],
          sceneNames: ["街道"],
          label: "街道",
          paletteIndex: 0,
        },
      },
    ]);
  });

  it("keeps clip spans on the shared index and merges uncovered gaps", () => {
    const result = projection(
      [
        shot({ id: 1, order_index: 1 }),
        shot({ id: 2, order_index: 2 }),
        shot({ id: 3, order_index: 3 }),
        shot({ id: 4, order_index: 4 }),
        shot({ id: 5, order_index: 5 }),
        shot({ id: 6, order_index: 6 }),
        shot({ id: 7, order_index: 7 }),
      ],
      [],
      [
        clip({ id: 201, shot_ids: [2, 3], generation_state: "ready" }),
        clip({ id: 202, shot_ids: [6], generation_state: "failed", freshness: "stale" }),
      ],
    );

    expect(result.clipSpans.map(({ startIndex, endIndex, shotIds }) => ({
      startIndex,
      endIndex,
      shotIds,
    }))).toEqual([
      { startIndex: 1, endIndex: 2, shotIds: [2, 3] },
      { startIndex: 5, endIndex: 5, shotIds: [6] },
    ]);
    expect(result.shots.map(({ occupiedByClipId }) => occupiedByClipId)).toEqual([
      null,
      201,
      201,
      null,
      null,
      202,
      null,
    ]);
    expect(result.gaps).toEqual([
      { startIndex: 0, endIndex: 0, shotIds: [1] },
      { startIndex: 3, endIndex: 4, shotIds: [4, 5] },
      { startIndex: 6, endIndex: 6, shotIds: [7] },
    ]);
    expect(result.clipSpans[1].status).toEqual({
      generationState: "failed",
      freshness: "stale",
      generationLabel: "failed",
      freshnessLabel: "stale",
      generationClassName: "director-generation-failed",
      freshnessClassName: "director-freshness-stale",
    });
  });

  it("keeps generation and freshness as independent status dimensions", () => {
    const states = ["empty", "queued", "generating", "ready", "failed"] as const;
    const freshness = ["fresh", "stale"] as const;

    for (const generationState of states) {
      for (const freshnessState of freshness) {
        const token = getClipStatusToken({
          generation_state: generationState,
          freshness: freshnessState,
        });
        expect(token.generationState).toBe(generationState);
        expect(token.freshness).toBe(freshnessState);
        expect(token.generationClassName).toBe(
          `director-generation-${generationState}`,
        );
        expect(token.freshnessClassName).toBe(
          `director-freshness-${freshnessState}`,
        );
      }
    }
  });

  it("applies zero-scene, cross-scene, multiple-scene, occupied and cancel rules", () => {
    const result = projection(
      [
        shot({ id: 1, order_index: 1, asset_ids: [101] }),
        shot({ id: 2, order_index: 2 }),
        shot({ id: 3, order_index: 3, asset_ids: [102] }),
        shot({ id: 4, order_index: 4, asset_ids: [101, 102] }),
        shot({ id: 5, order_index: 5, asset_ids: [101] }),
      ],
      [sceneAsset(101, "室内"), sceneAsset(102, "街道")],
      [clip({ id: 301, shot_ids: [5] })],
    );

    const singleScene = projectShotSelection(result, [1]);
    expect(singleScene.selectedShotIds).toEqual([1]);
    expect(singleScene.selectedSceneIds).toEqual([101]);
    expect(singleScene.eligibility).toEqual([
      {
        shotId: 1,
        selected: true,
        disabled: false,
        canSelect: false,
        canDeselect: true,
        reason: null,
      },
      {
        shotId: 2,
        selected: false,
        disabled: false,
        canSelect: true,
        canDeselect: false,
        reason: null,
      },
      {
        shotId: 3,
        selected: false,
        disabled: true,
        canSelect: false,
        canDeselect: false,
        reason: "当前选择属于场景 101，不能选择其他场景",
      },
      {
        shotId: 4,
        selected: false,
        disabled: true,
        canSelect: false,
        canDeselect: false,
        reason: "绑定多个场景，需先到分镜页修正",
      },
      {
        shotId: 5,
        selected: false,
        disabled: true,
        canSelect: false,
        canDeselect: false,
        reason: "已被 Clip 占用",
      },
    ]);

    const noScene = projectShotSelection(result, []);
    expect(noScene.eligibility[0].canSelect).toBe(true);
    expect(noScene.eligibility[1].canSelect).toBe(true);
    expect(noScene.eligibility[2].canSelect).toBe(true);
    expect(noScene.eligibility[3].reason).toBe("绑定多个场景，需先到分镜页修正");

    const clickOrder = projectShotSelection(result, [3, 1]);
    expect(clickOrder.selectedShotIds).toEqual([3, 1]);
    expect(clickOrder.eligibility[0].canDeselect).toBe(true);
    expect(clickOrder.eligibility[2].canDeselect).toBe(true);
  });

  it("derives the reference limit from the preview and keeps candidate order", () => {
    const overflowPreview: ClipPreviewResponse = {
      episode_id: 1,
      shot_ids: [1, 2, 3],
      duration_est_total: 3,
      suggested_requested_duration: 5,
      reference_candidates: [10, 11, 12, 13, 14].map((asset_id) => ({
        asset_id,
        asset_type: "character",
        asset_name: `角色${asset_id}`,
        first_shot_id: 1,
        first_order_index: 1,
        selected_by_default: asset_id < 12,
      })),
      default_reference_asset_ids: [10, 11],
      violations: [],
      warnings: [],
    };

    expect(projectReferenceSelection(overflowPreview)).toEqual({
      candidateIds: [10, 11, 12, 13, 14],
      selectedReferenceAssetIds: [10, 11],
      maxSelectableReferenceAssets: 2,
      validationMessage: null,
    });
    expect(projectReferenceSelection(overflowPreview, [14, 12])).toEqual({
      candidateIds: [10, 11, 12, 13, 14],
      selectedReferenceAssetIds: [12, 14],
      maxSelectableReferenceAssets: 2,
      validationMessage: null,
    });
    expect(projectReferenceSelection(overflowPreview, [10, 12, 14]).validationMessage).toBe(
      "参考资产最多选择 2 个",
    );
    expect(projectReferenceSelection(overflowPreview, []).validationMessage).toBe(
      "至少选择 1 个参考资产",
    );

    const equalPreview = {
      ...overflowPreview,
      reference_candidates: overflowPreview.reference_candidates.slice(0, 2),
    };
    expect(projectReferenceSelection(equalPreview).maxSelectableReferenceAssets).toBe(2);
  });

  it("keeps preview state authoritative, preserves warnings, and builds the exact create body", () => {
    const response: ClipPreviewResponse = {
      episode_id: 1,
      shot_ids: [3, 1],
      duration_est_total: 7,
      suggested_requested_duration: 9,
      reference_candidates: [10, 11, 12, 13].map((asset_id) => ({
        asset_id,
        asset_type: "character",
        asset_name: `角色${asset_id}`,
        first_shot_id: asset_id === 10 ? 3 : 1,
        first_order_index: asset_id === 10 ? 3 : 1,
        selected_by_default: asset_id < 12,
      })),
      default_reference_asset_ids: [10, 11],
      violations: [],
      warnings: [{ code: "soft_limit", message: "参考资产超过软提示" }],
    };

    let state = createDirectorPreviewState([3, 1]);
    state = startDirectorPreview(state.selectedShotIds);
    expect(state).toMatchObject({
      phase: "previewing",
      selectedShotIds: [3, 1],
      response: null,
      selectedReferenceAssetIds: [],
      requestedDuration: "",
      error: null,
    });

    state = applyDirectorPreview(state, response);
    expect(state.phase).toBe("ready");
    expect(state.selectedShotIds).toEqual([3, 1]);
    expect(state.requestedDuration).toBe("9");
    expect(state.selectedReferenceAssetIds).toEqual([10, 11]);
    expect(state.response?.warnings).toEqual([
      { code: "soft_limit", message: "参考资产超过软提示" },
    ]);

    const replacementState = {
      ...state,
      selectedReferenceAssetIds: [12, 10],
      requestedDuration: "7",
    };
    expect(projectClipCreateRequest(replacementState, "保留空串语义")).toEqual({
      input: {
        shot_ids: [3, 1],
        reference_asset_ids: [10, 12],
        requested_duration: 7,
        user_note: "保留空串语义",
      },
      validationMessage: null,
    });
    expect(projectReferenceSelection(response, []).validationMessage).toBe(
      "至少选择 1 个参考资产",
    );
    expect(
      projectReferenceSelection(response, [10, 11, 12]).validationMessage,
    ).toBe("参考资产最多选择 2 个");
    expect(projectReferenceSelection(response, [10, 11, 12, 13]).candidateIds).toEqual([
      10,
      11,
      12,
      13,
    ]);
    expect(parseDirectorRequestedDuration("7")).toBe(7);
    expect(parseDirectorRequestedDuration("7.5")).toBeNull();
    expect(projectClipCreateRequest({ ...state, requestedDuration: "7.5" }).input).toBeNull();

    const violationState = applyDirectorPreview(state, {
      ...response,
      violations: [{ code: "R5", message: "分镜不连续" }],
    });
    expect(projectClipCreateRequest(violationState).validationMessage).toBe(
      "存在服务端违规，暂不能创建",
    );
    expect(violationState.response?.violations).toEqual([
      { code: "R5", message: "分镜不连续" },
    ]);

    const createError = new Error("服务端重新裁决失败");
    const preserved = preserveDirectorPreviewAfterCreateError(state, createError);
    expect(preserved.phase).toBe("ready");
    expect(preserved.response).toBe(response);
    expect(preserved.selectedShotIds).toEqual([3, 1]);
    expect(preserved.error).toBe(createError);

    expect(failDirectorPreview(state, createError)).toMatchObject({
      phase: "error",
      selectedShotIds: [3, 1],
      response: null,
      selectedReferenceAssetIds: [],
      requestedDuration: "",
      error: createError,
    });
    expect(invalidateDirectorPreview([1])).toEqual({
      phase: "idle",
      selectedShotIds: [1],
      response: null,
      selectedReferenceAssetIds: [],
      requestedDuration: "",
      error: null,
    });
    expect(clearDirectorPreview()).toEqual(createDirectorPreviewState());
  });

  it("projects Clip settings as exact changed-field PATCH and preserves note semantics", () => {
    const base = createDirectorClipSettingsDraft({
      user_note: null,
      requested_duration: 5,
    });

    expect(projectDirectorClipSettingsPatch(base)).toEqual({
      input: null,
      validationMessage: null,
      hasChanges: false,
    });

    const emptyNote = updateDirectorClipSettingsDraft(base, { userNote: "" });
    expect(emptyNote).toMatchObject({
      userNote: "",
      requestedDuration: "5",
      dirtyUserNote: true,
      dirtyRequestedDuration: false,
    });
    expect(projectDirectorClipSettingsPatch(emptyNote)).toEqual({
      input: { user_note: "" },
      validationMessage: null,
      hasChanges: true,
    });

    const whitespaceNote = updateDirectorClipSettingsDraft(base, {
      userNote: "  原样保留  ",
    });
    expect(projectDirectorClipSettingsPatch(whitespaceNote).input).toEqual({
      user_note: "  原样保留  ",
    });

    const changedBoth = updateDirectorClipSettingsDraft(base, {
      userNote: "  精确意见  ",
      requestedDuration: "999",
    });
    expect(projectDirectorClipSettingsPatch(changedBoth)).toEqual({
      input: {
        user_note: "  精确意见  ",
        requested_duration: 999,
      },
      validationMessage: null,
      hasChanges: true,
    });

    const reverted = updateDirectorClipSettingsDraft(changedBoth, {
      userNote: null,
      requestedDuration: "5",
    });
    expect(reverted).toMatchObject({
      userNote: null,
      requestedDuration: "5",
      dirtyUserNote: false,
      dirtyRequestedDuration: false,
    });
    expect(projectDirectorClipSettingsPatch(reverted).input).toBeNull();

    const invalidDuration = updateDirectorClipSettingsDraft(base, {
      requestedDuration: "7.5",
    });
    expect(projectDirectorClipSettingsPatch(invalidDuration)).toEqual({
      input: null,
      validationMessage: "请求时长必须是十进制整数",
      hasChanges: true,
    });
  });

  it("blocks generation only for an unsaved requested duration", () => {
    const base = createDirectorClipSettingsDraft({
      user_note: null,
      requested_duration: 5,
    });
    expect(projectDirectorGenerationGate(base)).toEqual({
      allowed: true,
      message: null,
    });
    expect(
      projectDirectorGenerationGate(
        updateDirectorClipSettingsDraft(base, { userNote: "未保存意见" }),
      ),
    ).toEqual({
      allowed: true,
      message: null,
    });
    expect(
      projectDirectorGenerationGate(
        updateDirectorClipSettingsDraft(base, { requestedDuration: "6" }),
      ),
    ).toEqual({
      allowed: false,
      message: "请先保存请求时长",
    });
  });

  it("throws a clear visible error for every invalid clip or shot projection fact", () => {
    expectProjectionError(
      () => projection([shot({ id: 1, duration_est: 0 })]),
      "invalid-shot-duration",
      "Shot 1 has invalid duration_est 0",
    );
    expectProjectionError(
      () =>
        projection(
          [shot({ id: 1 })],
          [],
          [clip({ id: 10, shot_ids: [99] })],
        ),
      "unknown-clip-shot",
      "Clip 10 references unknown Shot 99",
    );
    expectProjectionError(
      () =>
        projection(
          [shot({ id: 1 }), shot({ id: 3, order_index: 3 })],
          [],
          [clip({ id: 10, shot_ids: [1, 3] })],
        ),
      "noncontiguous-clip",
      "Clip 10 spans non-contiguous Shots 1, 3",
    );
    expectProjectionError(
      () =>
        projection(
          [shot({ id: 1 }), shot({ id: 2, order_index: 2 }), shot({ id: 3, order_index: 3 })],
          [],
          [
            clip({ id: 10, shot_ids: [1, 2] }),
            clip({ id: 11, shot_ids: [2, 3] }),
          ],
        ),
      "overlapping-clips",
      "Clip 11 overlaps Clip 10 at Shot 2",
    );
  });
});
