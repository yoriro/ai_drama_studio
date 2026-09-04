import {
  ApiProtocolError,
  protocolError,
  requestJson,
  requestNoContent,
  requireArray,
  requireBoolean,
  requireDecimalSeed,
  requireEnum,
  requireFiniteNumber,
  requireNullableObject,
  requireNullableString,
  requireObjectWithKeys,
  requirePositiveSafeInteger,
  requirePositiveSafeIntegerText,
  requireString,
} from "./client";

export type ClipGenerationState =
  | "empty"
  | "queued"
  | "generating"
  | "ready"
  | "failed";
export type ClipFreshness = "fresh" | "stale";

export interface ClipRuleMessage {
  code: string;
  message: string;
}

export interface ClipPreviewRequest {
  shot_ids: number[];
}

export interface ClipReferenceCandidate {
  asset_id: number;
  asset_type: string;
  asset_name: string;
  first_shot_id: number;
  first_order_index: number;
  selected_by_default: boolean;
}

export interface ClipPreviewResponse {
  episode_id: number;
  shot_ids: number[];
  duration_est_total: number;
  suggested_requested_duration: number;
  reference_candidates: ClipReferenceCandidate[];
  default_reference_asset_ids: number[];
  violations: ClipRuleMessage[];
  warnings: ClipRuleMessage[];
}

export interface ClipCreateRequest {
  shot_ids: number[];
  reference_asset_ids: number[];
  requested_duration?: number;
  user_note?: string | null;
}

export interface ClipPatchRequest {
  user_note?: string | null;
  requested_duration?: number;
}

export interface Clip {
  id: number;
  episode_id: number;
  generation_mode: "ref2v";
  user_note: string | null;
  requested_duration: number;
  generation_state: ClipGenerationState;
  freshness: ClipFreshness;
  revision: number;
  shot_ids: number[];
  start_order_index: number;
  end_order_index: number;
  enabled_slot_count: number;
  warnings: ClipRuleMessage[];
  created_at: string;
  updated_at: string;
}

export interface ClipSlot {
  id: number;
  clip_id: number;
  slot_no: number;
  asset_id: number | null;
  asset_name_snapshot: string;
  asset_type_snapshot: string;
  asset_deleted: boolean;
  enabled: boolean;
  image_source: "override" | "asset_current" | null;
  image_url: string | null;
}

export interface ClipSlotsResponse {
  clip_id: number;
  items: ClipSlot[];
  warnings: ClipRuleMessage[];
}

export interface ClipSlotMutationResponse {
  slot: ClipSlot;
  warnings: ClipRuleMessage[];
}

export interface ClipVideo {
  id: number;
  clip_id: number;
  sha256: string;
  seed: string;
  requested_duration: number;
  actual_duration: number | null;
  is_current: boolean;
  media_url: string;
  created_at: string;
  built_prompt?: string | null;
  input_snapshot?: Record<string, unknown> | null;
}

export interface GenerateClipVideoRequest {
  user_note?: string | null;
}

export interface GenerateClipVideoResponse {
  task_id: number;
}

interface ClipSlotEnabledPatch {
  enabled: boolean;
}

interface CurrentClipVideoRequest {
  video_id: number;
}

const jsonHeaders = { "Content-Type": "application/json" };

const CLIP_GENERATION_STATES = [
  "empty",
  "queued",
  "generating",
  "ready",
  "failed",
] as const;
const CLIP_FRESHNESS_VALUES = ["fresh", "stale"] as const;
const IMAGE_SOURCES = ["override", "asset_current"] as const;

function parsePositiveIntegerArray(
  value: unknown,
  context: string,
  status: number,
): number[] {
  return requireArray(value, status, context).map((item, index) =>
    requirePositiveSafeInteger(item, `${context}[${index}]`, status),
  );
}

function parseRuleMessage(
  value: unknown,
  context: string,
  status: number,
): ClipRuleMessage {
  const record = requireObjectWithKeys(
    value,
    ["code", "message"],
    [],
    status,
    context,
  );
  requireString(record.code, status, `${context}.code`);
  requireString(record.message, status, `${context}.message`);
  return record as unknown as ClipRuleMessage;
}

function parseRuleMessages(
  value: unknown,
  context: string,
  status: number,
): ClipRuleMessage[] {
  return requireArray(value, status, context).map((item, index) =>
    parseRuleMessage(item, `${context}[${index}]`, status),
  );
}

export function parseClipPreviewResponse(
  value: unknown,
  status = 200,
): ClipPreviewResponse {
  const record = requireObjectWithKeys(
    value,
    [
      "episode_id",
      "shot_ids",
      "duration_est_total",
      "suggested_requested_duration",
      "reference_candidates",
      "default_reference_asset_ids",
      "violations",
      "warnings",
    ],
    [],
    status,
    "Clip preview response",
  );
  requirePositiveSafeInteger(record.episode_id, "ClipPreview.episode_id", status);
  parsePositiveIntegerArray(record.shot_ids, "ClipPreview.shot_ids", status);
  const duration = requireFiniteNumber(
    record.duration_est_total,
    "ClipPreview.duration_est_total",
    status,
  );
  if (duration < 0) {
    return protocolError(status, "ClipPreview.duration_est_total must be non-negative");
  }
  requirePositiveSafeInteger(
    record.suggested_requested_duration,
    "ClipPreview.suggested_requested_duration",
    status,
  );
  const candidates = requireArray(
    record.reference_candidates,
    status,
    "ClipPreview.reference_candidates",
  ).map((item, index) => {
    const context = `ClipPreview.reference_candidates[${index}]`;
    const candidate = requireObjectWithKeys(
      item,
      [
        "asset_id",
        "asset_type",
        "asset_name",
        "first_shot_id",
        "first_order_index",
        "selected_by_default",
      ],
      [],
      status,
      context,
    );
    requirePositiveSafeInteger(candidate.asset_id, `${context}.asset_id`, status);
    requireString(candidate.asset_type, status, `${context}.asset_type`);
    requireString(candidate.asset_name, status, `${context}.asset_name`);
    requirePositiveSafeInteger(
      candidate.first_shot_id,
      `${context}.first_shot_id`,
      status,
    );
    requirePositiveSafeInteger(
      candidate.first_order_index,
      `${context}.first_order_index`,
      status,
    );
    requireBoolean(
      candidate.selected_by_default,
      status,
      `${context}.selected_by_default`,
    );
    return candidate as unknown as ClipReferenceCandidate;
  });
  const defaultReferenceAssetIds = parsePositiveIntegerArray(
    record.default_reference_asset_ids,
    "ClipPreview.default_reference_asset_ids",
    status,
  );
  const violations = parseRuleMessages(record.violations, "ClipPreview.violations", status);
  const warnings = parseRuleMessages(record.warnings, "ClipPreview.warnings", status);
  return {
    ...(record as unknown as ClipPreviewResponse),
    shot_ids: parsePositiveIntegerArray(record.shot_ids, "ClipPreview.shot_ids", status),
    reference_candidates: candidates,
    default_reference_asset_ids: defaultReferenceAssetIds,
    violations,
    warnings,
  };
}

export function parseClipResponse(value: unknown, status = 200): Clip {
  const record = requireObjectWithKeys(
    value,
    [
      "id",
      "episode_id",
      "generation_mode",
      "user_note",
      "requested_duration",
      "generation_state",
      "freshness",
      "revision",
      "shot_ids",
      "start_order_index",
      "end_order_index",
      "enabled_slot_count",
      "warnings",
      "created_at",
      "updated_at",
    ],
    [],
    status,
    "Clip response",
  );
  requirePositiveSafeInteger(record.id, "Clip.id", status);
  requirePositiveSafeInteger(record.episode_id, "Clip.episode_id", status);
  requireEnum(record.generation_mode, ["ref2v"] as const, "Clip.generation_mode", status);
  requireNullableString(record.user_note, status, "Clip.user_note");
  requirePositiveSafeInteger(record.requested_duration, "Clip.requested_duration", status);
  requireEnum(
    record.generation_state,
    CLIP_GENERATION_STATES,
    "Clip.generation_state",
    status,
  );
  requireEnum(record.freshness, CLIP_FRESHNESS_VALUES, "Clip.freshness", status);
  requirePositiveSafeInteger(record.revision, "Clip.revision", status);
  const shotIds = parsePositiveIntegerArray(record.shot_ids, "Clip.shot_ids", status);
  requirePositiveSafeInteger(record.start_order_index, "Clip.start_order_index", status);
  requirePositiveSafeInteger(record.end_order_index, "Clip.end_order_index", status);
  if (
    typeof record.enabled_slot_count !== "number" ||
    !Number.isSafeInteger(record.enabled_slot_count) ||
    record.enabled_slot_count < 0
  ) {
    return protocolError(
      status,
      "Clip.enabled_slot_count must be a non-negative JavaScript safe integer",
    );
  }
  const warnings = parseRuleMessages(record.warnings, "Clip.warnings", status);
  requireString(record.created_at, status, "Clip.created_at");
  requireString(record.updated_at, status, "Clip.updated_at");
  return {
    ...(record as unknown as Clip),
    shot_ids: shotIds,
    warnings,
  };
}

function parseMediaPath(
  value: unknown,
  prefix: "/media/asset-images" | "/media/slot-overrides" | "/media/clip-videos",
  context: string,
  expectedId: number | null,
  status: number,
): string {
  if (typeof value !== "string") {
    return protocolError(status, `${context} must be a same-origin media path`);
  }
  const match = new RegExp(`^${prefix}/([1-9]\\d*)$`).exec(value);
  if (match === null) {
    return protocolError(status, `${context} must be a same-origin media path`);
  }
  const idText = requirePositiveSafeIntegerText(match[1]!, `${context} id`, status);
  if (expectedId !== null && idText !== String(expectedId)) {
    return protocolError(status, `${context} id does not match its resource`);
  }
  return value;
}

export function parseClipSlotResponse(value: unknown, status = 200): ClipSlot {
  const record = requireObjectWithKeys(
    value,
    [
      "id",
      "clip_id",
      "slot_no",
      "asset_id",
      "asset_name_snapshot",
      "asset_type_snapshot",
      "asset_deleted",
      "enabled",
      "image_source",
      "image_url",
    ],
    [],
    status,
    "Clip slot response",
  );
  const slotId = requirePositiveSafeInteger(record.id, "ClipSlot.id", status);
  requirePositiveSafeInteger(record.clip_id, "ClipSlot.clip_id", status);
  requirePositiveSafeInteger(record.slot_no, "ClipSlot.slot_no", status);
  if (record.asset_id !== null) {
    requirePositiveSafeInteger(record.asset_id, "ClipSlot.asset_id", status);
  }
  requireString(record.asset_name_snapshot, status, "ClipSlot.asset_name_snapshot");
  requireString(record.asset_type_snapshot, status, "ClipSlot.asset_type_snapshot");
  requireBoolean(record.asset_deleted, status, "ClipSlot.asset_deleted");
  requireBoolean(record.enabled, status, "ClipSlot.enabled");
  const imageSource =
    record.image_source === null
      ? null
      : requireEnum(record.image_source, IMAGE_SOURCES, "ClipSlot.image_source", status);
  const imageUrl = requireNullableString(record.image_url, status, "ClipSlot.image_url");
  if (imageSource === null) {
    if (imageUrl !== null) {
      return protocolError(status, "ClipSlot.image_url must be null when image_source is null");
    }
  } else if (imageUrl === null) {
    return protocolError(status, "ClipSlot.image_url is required for an image source");
  } else if (imageSource === "asset_current") {
    parseMediaPath(
      imageUrl,
      "/media/asset-images",
      "ClipSlot.image_url",
      null,
      status,
    );
  } else {
    parseMediaPath(
      imageUrl,
      "/media/slot-overrides",
      "ClipSlot.image_url",
      slotId,
      status,
    );
  }
  return {
    ...(record as unknown as ClipSlot),
    id: slotId,
    image_source: imageSource,
    image_url: imageUrl,
  };
}

export function parseClipSlotsResponse(
  value: unknown,
  status = 200,
): ClipSlotsResponse {
  const record = requireObjectWithKeys(
    value,
    ["clip_id", "items", "warnings"],
    [],
    status,
    "Clip slots response",
  );
  requirePositiveSafeInteger(record.clip_id, "ClipSlots.clip_id", status);
  const items = requireArray(record.items, status, "ClipSlots.items").map(
    (item) => parseClipSlotResponse(item, status),
  );
  const warnings = parseRuleMessages(record.warnings, "ClipSlots.warnings", status);
  return {
    ...(record as unknown as ClipSlotsResponse),
    items,
    warnings,
  };
}

export function parseClipSlotMutationResponse(
  value: unknown,
  status = 200,
): ClipSlotMutationResponse {
  const record = requireObjectWithKeys(
    value,
    ["slot", "warnings"],
    [],
    status,
    "Clip slot mutation response",
  );
  const slot = parseClipSlotResponse(record.slot, status);
  const warnings = parseRuleMessages(
    record.warnings,
    "ClipSlotMutation.warnings",
    status,
  );
  return { ...(record as unknown as ClipSlotMutationResponse), slot, warnings };
}

export function parseClipVideoResponse(value: unknown, status = 200): ClipVideo {
  const record = requireObjectWithKeys(
    value,
    [
      "id",
      "clip_id",
      "sha256",
      "seed",
      "requested_duration",
      "actual_duration",
      "is_current",
      "media_url",
      "created_at",
    ],
    ["built_prompt", "input_snapshot", "input_hash"],
    status,
    "ClipVideo response",
  );
  if (Object.prototype.hasOwnProperty.call(record, "input_hash")) {
    return protocolError(
      status,
      "ClipVideo response must not contain input_hash",
    );
  }
  const videoId = requirePositiveSafeInteger(record.id, "ClipVideo.id", status);
  requirePositiveSafeInteger(record.clip_id, "ClipVideo.clip_id", status);
  requireString(record.sha256, status, "ClipVideo.sha256");
  const seed = requireDecimalSeed(record.seed, "ClipVideo.seed", status);
  requirePositiveSafeInteger(
    record.requested_duration,
    "ClipVideo.requested_duration",
    status,
  );
  if (record.actual_duration !== null) {
    const actualDuration = requireFiniteNumber(
      record.actual_duration,
      "ClipVideo.actual_duration",
      status,
    );
    if (actualDuration < 0) {
      return protocolError(status, "ClipVideo.actual_duration must be non-negative");
    }
  }
  requireBoolean(record.is_current, status, "ClipVideo.is_current");
  const mediaUrl = parseMediaPath(
    record.media_url,
    "/media/clip-videos",
    "ClipVideo.media_url",
    videoId,
    status,
  );
  requireString(record.created_at, status, "ClipVideo.created_at");
  if (Object.prototype.hasOwnProperty.call(record, "built_prompt")) {
    requireNullableString(record.built_prompt, status, "ClipVideo.built_prompt");
  }
  if (Object.prototype.hasOwnProperty.call(record, "input_snapshot")) {
    requireNullableObject(record.input_snapshot, status, "ClipVideo.input_snapshot");
  }
  return {
    ...(record as unknown as ClipVideo),
    id: videoId,
    seed,
    media_url: mediaUrl,
  };
}

export function parseClipVideosResponse(
  value: unknown,
  status = 200,
): ClipVideo[] {
  return requireArray(value, status, "Clip videos response").map((item) =>
    parseClipVideoResponse(item, status),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actualKeys = Object.keys(value);
  return (
    actualKeys.length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function isGenerateClipVideoResponse(
  value: unknown,
): value is GenerateClipVideoResponse {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["task_id"]) &&
    typeof value.task_id === "number" &&
    Number.isInteger(value.task_id) &&
    value.task_id > 0
  );
}

export function listClips(episodeId: number): Promise<Clip[]> {
  const id = requirePositiveSafeInteger(episodeId, "episodeId");
  return requestJson<Clip[]>(
    `/episodes/${id}/clips`,
    undefined,
    (value, status) =>
      requireArray(value, status, "Clip list response").map((item) =>
        parseClipResponse(item, status),
      ),
  );
}

export function previewClips(
  episodeId: number,
  input: ClipPreviewRequest,
): Promise<ClipPreviewResponse> {
  const id = requirePositiveSafeInteger(episodeId, "episodeId");
  input.shot_ids.forEach((shotId, index) =>
    requirePositiveSafeInteger(shotId, `shot_ids[${index}]`),
  );
  return requestJson<ClipPreviewResponse>(
    `/episodes/${id}/clips/preview`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(input),
    },
  );
}

export function createClip(
  episodeId: number,
  input: ClipCreateRequest,
): Promise<Clip> {
  const id = requirePositiveSafeInteger(episodeId, "episodeId");
  input.shot_ids.forEach((shotId, index) =>
    requirePositiveSafeInteger(shotId, `shot_ids[${index}]`),
  );
  input.reference_asset_ids.forEach((assetId, index) =>
    requirePositiveSafeInteger(assetId, `reference_asset_ids[${index}]`),
  );
  return requestJson<Clip>(`/episodes/${id}/clips`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function getClip(clipId: number): Promise<Clip> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  return requestJson<Clip>(`/clips/${id}`);
}

export function updateClip(
  clipId: number,
  input: ClipPatchRequest,
): Promise<Clip> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  return requestJson<Clip>(`/clips/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteClip(clipId: number): Promise<void> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  return requestNoContent(`/clips/${id}`, { method: "DELETE" });
}

export function listClipSlots(clipId: number): Promise<ClipSlotsResponse> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  return requestJson<ClipSlotsResponse>(`/clips/${id}/slots`);
}

export function updateClipSlotEnabled(
  clipId: number,
  slotNo: number,
  enabled: boolean,
): Promise<ClipSlotMutationResponse> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  const slot = requirePositiveSafeInteger(slotNo, "slotNo");
  const input: ClipSlotEnabledPatch = { enabled };
  return requestJson<ClipSlotMutationResponse>(
    `/clips/${id}/slots/${slot}`,
    {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify(input),
    },
  );
}

export function uploadClipSlotOverride(
  clipId: number,
  slotNo: number,
  file: File,
): Promise<ClipSlotMutationResponse> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  const slot = requirePositiveSafeInteger(slotNo, "slotNo");
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<ClipSlotMutationResponse>(
    `/clips/${id}/slots/${slot}`,
    {
      method: "PATCH",
      body: formData,
    },
  );
}

export function clearClipSlotOverride(
  clipId: number,
  slotNo: number,
): Promise<ClipSlotMutationResponse> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  const slot = requirePositiveSafeInteger(slotNo, "slotNo");
  const formData = new FormData();
  formData.append("clear_override", "true");
  return requestJson<ClipSlotMutationResponse>(
    `/clips/${id}/slots/${slot}`,
    {
      method: "PATCH",
      body: formData,
    },
  );
}

export async function generateClipVideo(
  clipId: number,
  input: GenerateClipVideoRequest = {},
): Promise<GenerateClipVideoResponse> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  const payload = await requestJson<unknown>(
    `/clips/${id}/generate-video`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(input),
    },
  );
  if (!isGenerateClipVideoResponse(payload)) {
    throw new ApiProtocolError(
      202,
      "Generate-video response did not match its schema",
    );
  }
  return payload;
}

export function listClipVideos(clipId: number): Promise<ClipVideo[]> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  return requestJson<ClipVideo[]>(
    `/clips/${id}/videos`,
    undefined,
    parseClipVideosResponse,
  );
}

export function setCurrentClipVideo(
  clipId: number,
  videoId: number,
): Promise<ClipVideo> {
  const id = requirePositiveSafeInteger(clipId, "clipId");
  const video = requirePositiveSafeInteger(videoId, "videoId");
  const input: CurrentClipVideoRequest = { video_id: video };
  return requestJson<ClipVideo>(`/clips/${id}/current-video`, {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteClipVideo(videoId: number): Promise<void> {
  const id = requirePositiveSafeInteger(videoId, "videoId");
  return requestNoContent(`/clip-videos/${id}`, { method: "DELETE" });
}
