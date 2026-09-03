import type { Asset } from "../../api/assets";
import type {
  Clip,
  ClipCreateRequest,
  ClipFreshness,
  ClipGenerationState,
  ClipPreviewResponse,
} from "../../api/clips";
import type { Shot } from "../../api/shots";

export type DirectorAsset = Pick<Asset, "id" | "type" | "name">;
export type DirectorShot = Pick<
  Shot,
  "id" | "order_index" | "duration_est" | "shot_type" | "asset_ids" | "status"
>;
export type DirectorClip = Pick<
  Clip,
  "id" | "shot_ids" | "generation_state" | "freshness"
>;

export type SceneClassificationKind = "unbound" | "scene" | "multiple";

export interface SceneClassification {
  kind: SceneClassificationKind;
  key: string;
  sceneIds: number[];
  sceneNames: string[];
  label: string;
  paletteIndex: number | null;
}

export interface DirectorGridColumn {
  index: number;
  shotId: number;
  durationEst: number;
  template: string;
}

export interface ProjectedShot {
  shot: DirectorShot;
  index: number;
  column: DirectorGridColumn;
  scene: SceneClassification;
  occupiedByClipId: number | null;
}

export interface SceneBand {
  startIndex: number;
  endIndex: number;
  shotIds: number[];
  classification: SceneClassification;
}

export interface ClipStatusToken {
  generationState: ClipGenerationState;
  freshness: ClipFreshness;
  generationLabel: string;
  freshnessLabel: string;
  generationClassName: string;
  freshnessClassName: string;
}

export interface ClipSpan {
  clip: DirectorClip;
  startIndex: number;
  endIndex: number;
  shotIds: number[];
  status: ClipStatusToken;
}

export interface ShotGap {
  startIndex: number;
  endIndex: number;
  shotIds: number[];
}

export interface DirectorProjection {
  shots: ProjectedShot[];
  gridColumns: DirectorGridColumn[];
  gridTemplateColumns: string;
  sceneBands: SceneBand[];
  clipSpans: ClipSpan[];
  gaps: ShotGap[];
}

export interface DirectorProjectionInput {
  shots: readonly DirectorShot[];
  assets: readonly DirectorAsset[];
  clips: readonly DirectorClip[];
}

export type DirectorProjectionErrorCode =
  | "invalid-shot-order"
  | "duplicate-shot-id"
  | "duplicate-order-index"
  | "invalid-shot-duration"
  | "empty-clip"
  | "duplicate-clip-shot"
  | "unknown-clip-shot"
  | "noncontiguous-clip"
  | "overlapping-clips"
  | "unknown-selected-shot"
  | "duplicate-selected-shot";

export class DirectorProjectionError extends Error {
  constructor(
    public readonly code: DirectorProjectionErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "DirectorProjectionError";
  }
}

const PALETTE_SIZE = 6;

function stablePaletteIndex(sceneId: number): number {
  return ((sceneId % PALETTE_SIZE) + PALETTE_SIZE) % PALETTE_SIZE;
}

function classifyShot(
  shot: DirectorShot,
  sceneAssets: ReadonlyMap<number, DirectorAsset>,
): SceneClassification {
  const sceneIds = [...new Set(
    shot.asset_ids.filter((assetId) => sceneAssets.get(assetId)?.type === "scene"),
  )].sort((left, right) => left - right);
  const sceneNames = sceneIds.map((sceneId) => sceneAssets.get(sceneId)!.name);

  if (sceneIds.length === 0) {
    return {
      kind: "unbound",
      key: "unbound",
      sceneIds,
      sceneNames,
      label: "未绑定场景",
      paletteIndex: null,
    };
  }

  if (sceneIds.length === 1) {
    return {
      kind: "scene",
      key: `scene:${sceneIds[0]}`,
      sceneIds,
      sceneNames,
      label: sceneNames[0],
      paletteIndex: stablePaletteIndex(sceneIds[0]),
    };
  }

  return {
    kind: "multiple",
    key: `multiple:${sceneIds.join(",")}`,
    sceneIds,
    sceneNames,
    label: "多个场景",
    paletteIndex: null,
  };
}

function buildSceneBands(shots: readonly ProjectedShot[]): SceneBand[] {
  const bands: SceneBand[] = [];
  for (const projectedShot of shots) {
    const previous = bands[bands.length - 1];
    if (previous?.classification.key === projectedShot.scene.key) {
      previous.endIndex = projectedShot.index;
      previous.shotIds.push(projectedShot.shot.id);
      continue;
    }

    bands.push({
      startIndex: projectedShot.index,
      endIndex: projectedShot.index,
      shotIds: [projectedShot.shot.id],
      classification: projectedShot.scene,
    });
  }
  return bands;
}

function buildClipSpans(
  clips: readonly DirectorClip[],
  shotIndexById: ReadonlyMap<number, number>,
  shotOrderIndexById: ReadonlyMap<number, number>,
): { spans: ClipSpan[]; occupiedByShotId: Map<number, number> } {
  const occupiedByShotId = new Map<number, number>();
  const spans: ClipSpan[] = [];

  for (const clip of clips) {
    if (clip.shot_ids.length === 0) {
      throw new DirectorProjectionError(
        "empty-clip",
        `Clip ${clip.id} has no shots and cannot be projected`,
      );
    }

    const indices: number[] = [];
    const orderIndexes: number[] = [];
    const seenInClip = new Set<number>();
    for (const shotId of clip.shot_ids) {
      if (seenInClip.has(shotId)) {
        throw new DirectorProjectionError(
          "duplicate-clip-shot",
          `Clip ${clip.id} references Shot ${shotId} more than once`,
        );
      }
      seenInClip.add(shotId);

      const index = shotIndexById.get(shotId);
      if (index === undefined) {
        throw new DirectorProjectionError(
          "unknown-clip-shot",
          `Clip ${clip.id} references unknown Shot ${shotId}`,
        );
      }
      indices.push(index);
      orderIndexes.push(shotOrderIndexById.get(shotId)!);
    }

    for (let offset = 1; offset < indices.length; offset += 1) {
      if (
        indices[offset] !== indices[0] + offset ||
        orderIndexes[offset] !== orderIndexes[0] + offset
      ) {
        throw new DirectorProjectionError(
          "noncontiguous-clip",
          `Clip ${clip.id} spans non-contiguous Shots ${clip.shot_ids.join(", ")}`,
        );
      }
    }

    for (const shotId of clip.shot_ids) {
      const existingClipId = occupiedByShotId.get(shotId);
      if (existingClipId !== undefined) {
        throw new DirectorProjectionError(
          "overlapping-clips",
          `Clip ${clip.id} overlaps Clip ${existingClipId} at Shot ${shotId}`,
        );
      }
      occupiedByShotId.set(shotId, clip.id);
    }

    spans.push({
      clip,
      startIndex: indices[0],
      endIndex: indices[indices.length - 1],
      shotIds: [...clip.shot_ids],
      status: getClipStatusToken(clip),
    });
  }

  return { spans, occupiedByShotId };
}

function buildGaps(
  shots: readonly ProjectedShot[],
  occupiedByShotId: ReadonlyMap<number, number>,
): ShotGap[] {
  const gaps: ShotGap[] = [];
  for (const shot of shots) {
    if (occupiedByShotId.has(shot.shot.id)) {
      continue;
    }

    const previous = gaps[gaps.length - 1];
    if (previous?.endIndex === shot.index - 1) {
      previous.endIndex = shot.index;
      previous.shotIds.push(shot.shot.id);
      continue;
    }

    gaps.push({
      startIndex: shot.index,
      endIndex: shot.index,
      shotIds: [shot.shot.id],
    });
  }
  return gaps;
}

export function getClipStatusToken(
  clip: Pick<Clip, "generation_state" | "freshness">,
): ClipStatusToken {
  return {
    generationState: clip.generation_state,
    freshness: clip.freshness,
    generationLabel: clip.generation_state,
    freshnessLabel: clip.freshness,
    generationClassName: `director-generation-${clip.generation_state}`,
    freshnessClassName: `director-freshness-${clip.freshness}`,
  };
}

export function buildDirectorProjection(
  input: DirectorProjectionInput,
): DirectorProjection {
  const sceneAssets = new Map<number, DirectorAsset>();
  for (const asset of input.assets) {
    if (asset.type === "scene") {
      sceneAssets.set(asset.id, asset);
    }
  }

  const seenShotIds = new Set<number>();
  const seenOrderIndexes = new Set<number>();
  const canonicalShots = [...input.shots].sort(
    (left, right) => left.order_index - right.order_index,
  );

  for (const shot of canonicalShots) {
    if (!Number.isFinite(shot.order_index)) {
      throw new DirectorProjectionError(
        "invalid-shot-order",
        `Shot ${shot.id} has an invalid order_index`,
      );
    }
    if (seenShotIds.has(shot.id)) {
      throw new DirectorProjectionError(
        "duplicate-shot-id",
        `Shot ${shot.id} appears more than once`,
      );
    }
    if (seenOrderIndexes.has(shot.order_index)) {
      throw new DirectorProjectionError(
        "duplicate-order-index",
        `Shot order_index ${shot.order_index} appears more than once`,
      );
    }
    if (!Number.isFinite(shot.duration_est) || shot.duration_est <= 0) {
      throw new DirectorProjectionError(
        "invalid-shot-duration",
        `Shot ${shot.id} has invalid duration_est ${String(shot.duration_est)}`,
      );
    }
    seenShotIds.add(shot.id);
    seenOrderIndexes.add(shot.order_index);
  }

  const shotIndexById = new Map<number, number>();
  const shotOrderIndexById = new Map<number, number>();
  const baseShots = canonicalShots.map((shot, index) => {
    shotIndexById.set(shot.id, index);
    shotOrderIndexById.set(shot.id, shot.order_index);
    const column: DirectorGridColumn = {
      index,
      shotId: shot.id,
      durationEst: shot.duration_est,
      template: `${shot.duration_est}fr`,
    };
    return {
      shot,
      index,
      column,
      scene: classifyShot(shot, sceneAssets),
    };
  });

  const { spans, occupiedByShotId } = buildClipSpans(
    input.clips,
    shotIndexById,
    shotOrderIndexById,
  );
  const projectedShots: ProjectedShot[] = baseShots.map((shot) => ({
    ...shot,
    occupiedByClipId: occupiedByShotId.get(shot.shot.id) ?? null,
  }));
  const gridColumns = projectedShots.map((shot) => shot.column);

  return {
    shots: projectedShots,
    gridColumns,
    gridTemplateColumns: gridColumns.map((column) => column.template).join(" "),
    sceneBands: buildSceneBands(projectedShots),
    clipSpans: spans,
    gaps: buildGaps(projectedShots, occupiedByShotId),
  };
}

export interface ShotSelectionEligibility {
  shotId: number;
  selected: boolean;
  disabled: boolean;
  canSelect: boolean;
  canDeselect: boolean;
  reason: string | null;
}

export interface ShotSelectionProjection {
  selectedShotIds: number[];
  selectedSceneIds: number[];
  eligibility: ShotSelectionEligibility[];
}

export function projectShotSelection(
  projection: DirectorProjection,
  selectedShotIds: readonly number[],
): ShotSelectionProjection {
  const knownShotIds = new Set(projection.shots.map(({ shot }) => shot.id));
  const selected = new Set<number>();
  for (const shotId of selectedShotIds) {
    if (!knownShotIds.has(shotId)) {
      throw new DirectorProjectionError(
        "unknown-selected-shot",
        `Selected Shot ${shotId} is not in the current projection`,
      );
    }
    if (selected.has(shotId)) {
      throw new DirectorProjectionError(
        "duplicate-selected-shot",
        `Selected Shot ${shotId} appears more than once`,
      );
    }
    selected.add(shotId);
  }

  const selectedSceneIds = [
    ...new Set(
      projection.shots
        .filter(({ shot }) => selected.has(shot.id))
        .flatMap(({ scene }) => (scene.kind === "scene" ? scene.sceneIds : [])),
    ),
  ].sort((left, right) => left - right);
  const singleSelectedSceneId =
    selectedSceneIds.length === 1 ? selectedSceneIds[0] : null;

  const eligibility = projection.shots.map(({ shot, scene, occupiedByClipId }) => {
    const isSelected = selected.has(shot.id);
    if (isSelected) {
      return {
        shotId: shot.id,
        selected: true,
        disabled: false,
        canSelect: false,
        canDeselect: true,
        reason: null,
      };
    }

    let reason: string | null = null;
    if (occupiedByClipId !== null) {
      reason = "已被 Clip 占用";
    } else if (scene.kind === "multiple") {
      reason = "绑定多个场景，需先到分镜页修正";
    } else if (selectedSceneIds.length > 1) {
      reason = "当前选择包含多个场景";
    } else if (
      singleSelectedSceneId !== null &&
      scene.kind === "scene" &&
      scene.sceneIds[0] !== singleSelectedSceneId
    ) {
      reason = `当前选择属于场景 ${singleSelectedSceneId}，不能选择其他场景`;
    }

    return {
      shotId: shot.id,
      selected: false,
      disabled: reason !== null,
      canSelect: reason === null,
      canDeselect: false,
      reason,
    };
  });

  return {
    selectedShotIds: [...selectedShotIds],
    selectedSceneIds,
    eligibility,
  };
}

export interface ReferenceSelectionProjection {
  candidateIds: number[];
  selectedReferenceAssetIds: number[];
  maxSelectableReferenceAssets: number;
  validationMessage: string | null;
}

export function projectReferenceSelection(
  preview: ClipPreviewResponse,
  selectedReferenceAssetIds: readonly number[] = preview.default_reference_asset_ids,
): ReferenceSelectionProjection {
  const candidateIds = preview.reference_candidates.map(
    (candidate) => candidate.asset_id,
  );
  const candidateIdSet = new Set(candidateIds);
  const selectedIdSet = new Set(selectedReferenceAssetIds);
  const selected = candidateIds.filter((assetId) => selectedIdSet.has(assetId));
  const hasUnknownSelection = selectedReferenceAssetIds.some(
    (assetId) => !candidateIdSet.has(assetId),
  );
  const maxSelectableReferenceAssets =
    candidateIds.length > preview.default_reference_asset_ids.length
      ? preview.default_reference_asset_ids.length
      : candidateIds.length;

  let validationMessage: string | null = null;
  if (hasUnknownSelection) {
    validationMessage = "只能选择预检返回的参考资产";
  } else if (selected.length === 0) {
    validationMessage = "至少选择 1 个参考资产";
  } else if (selected.length > maxSelectableReferenceAssets) {
    validationMessage = `参考资产最多选择 ${maxSelectableReferenceAssets} 个`;
  }

  return {
    candidateIds,
    selectedReferenceAssetIds: selected,
    maxSelectableReferenceAssets,
    validationMessage,
  };
}

export type DirectorPreviewPhase =
  | "idle"
  | "previewing"
  | "ready"
  | "error"
  | "creating";

export interface DirectorPreviewState {
  phase: DirectorPreviewPhase;
  selectedShotIds: number[];
  response: ClipPreviewResponse | null;
  selectedReferenceAssetIds: number[];
  requestedDuration: string;
  error: unknown | null;
}

export function createDirectorPreviewState(
  selectedShotIds: readonly number[] = [],
): DirectorPreviewState {
  return {
    phase: "idle",
    selectedShotIds: [...selectedShotIds],
    response: null,
    selectedReferenceAssetIds: [],
    requestedDuration: "",
    error: null,
  };
}

export function invalidateDirectorPreview(
  selectedShotIds: readonly number[],
): DirectorPreviewState {
  return createDirectorPreviewState(selectedShotIds);
}

export function startDirectorPreview(
  selectedShotIds: readonly number[],
): DirectorPreviewState {
  return {
    ...createDirectorPreviewState(selectedShotIds),
    phase: "previewing",
  };
}

export function applyDirectorPreview(
  state: DirectorPreviewState,
  response: ClipPreviewResponse,
): DirectorPreviewState {
  const referenceSelection = projectReferenceSelection(response);
  return {
    ...state,
    phase: "ready",
    response,
    selectedReferenceAssetIds: referenceSelection.selectedReferenceAssetIds,
    requestedDuration: String(response.suggested_requested_duration),
    error: null,
  };
}

export function failDirectorPreview(
  state: DirectorPreviewState,
  error: unknown,
): DirectorPreviewState {
  return {
    ...state,
    phase: "error",
    response: null,
    selectedReferenceAssetIds: [],
    requestedDuration: "",
    error,
  };
}

export function preserveDirectorPreviewAfterCreateError(
  state: DirectorPreviewState,
  error: unknown,
): DirectorPreviewState {
  return {
    ...state,
    phase: "ready",
    error,
  };
}

export function clearDirectorPreview(): DirectorPreviewState {
  return createDirectorPreviewState();
}

export function parseDirectorRequestedDuration(
  requestedDuration: string,
): number | null {
  if (!/^-?\d+$/.test(requestedDuration)) {
    return null;
  }
  const parsed = Number(requestedDuration);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export interface DirectorClipCreateProjection {
  input: ClipCreateRequest | null;
  validationMessage: string | null;
}

export function projectClipCreateRequest(
  state: DirectorPreviewState,
  userNote: string | null = null,
): DirectorClipCreateProjection {
  if (state.response === null) {
    return {
      input: null,
      validationMessage: "请先完成预检",
    };
  }
  if (state.response.violations.length > 0) {
    return {
      input: null,
      validationMessage: "存在服务端违规，暂不能创建",
    };
  }

  const referenceSelection = projectReferenceSelection(
    state.response,
    state.selectedReferenceAssetIds,
  );
  if (referenceSelection.validationMessage !== null) {
    return {
      input: null,
      validationMessage: referenceSelection.validationMessage,
    };
  }

  const requestedDuration = parseDirectorRequestedDuration(
    state.requestedDuration,
  );
  if (requestedDuration === null) {
    return {
      input: null,
      validationMessage: "请求时长必须是十进制整数",
    };
  }

  return {
    input: {
      shot_ids: [...state.response.shot_ids],
      reference_asset_ids: referenceSelection.selectedReferenceAssetIds,
      requested_duration: requestedDuration,
      user_note: userNote,
    },
    validationMessage: null,
  };
}
