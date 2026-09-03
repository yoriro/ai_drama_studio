import { ApiProtocolError, requestJson, requestNoContent } from "./client";

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
  return requestJson<Clip[]>(`/episodes/${episodeId}/clips`);
}

export function previewClips(
  episodeId: number,
  input: ClipPreviewRequest,
): Promise<ClipPreviewResponse> {
  return requestJson<ClipPreviewResponse>(
    `/episodes/${episodeId}/clips/preview`,
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
  return requestJson<Clip>(`/episodes/${episodeId}/clips`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function getClip(clipId: number): Promise<Clip> {
  return requestJson<Clip>(`/clips/${clipId}`);
}

export function updateClip(
  clipId: number,
  input: ClipPatchRequest,
): Promise<Clip> {
  return requestJson<Clip>(`/clips/${clipId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteClip(clipId: number): Promise<void> {
  return requestNoContent(`/clips/${clipId}`, { method: "DELETE" });
}

export function listClipSlots(clipId: number): Promise<ClipSlotsResponse> {
  return requestJson<ClipSlotsResponse>(`/clips/${clipId}/slots`);
}

export function updateClipSlotEnabled(
  clipId: number,
  slotNo: number,
  enabled: boolean,
): Promise<ClipSlotMutationResponse> {
  const input: ClipSlotEnabledPatch = { enabled };
  return requestJson<ClipSlotMutationResponse>(
    `/clips/${clipId}/slots/${slotNo}`,
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
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<ClipSlotMutationResponse>(
    `/clips/${clipId}/slots/${slotNo}`,
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
  const formData = new FormData();
  formData.append("clear_override", "true");
  return requestJson<ClipSlotMutationResponse>(
    `/clips/${clipId}/slots/${slotNo}`,
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
  const payload = await requestJson<unknown>(
    `/clips/${clipId}/generate-video`,
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
  return requestJson<ClipVideo[]>(`/clips/${clipId}/videos`);
}

export function setCurrentClipVideo(
  clipId: number,
  videoId: number,
): Promise<ClipVideo> {
  const input: CurrentClipVideoRequest = { video_id: videoId };
  return requestJson<ClipVideo>(`/clips/${clipId}/current-video`, {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteClipVideo(videoId: number): Promise<void> {
  return requestNoContent(`/clip-videos/${videoId}`, { method: "DELETE" });
}
