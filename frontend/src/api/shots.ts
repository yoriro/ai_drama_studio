import {
  protocolError,
  requestJson,
  requireArray,
  requireEnum,
  requireFiniteNumber,
  requireObjectWithKeys,
  requirePositiveSafeInteger,
  requireString,
} from "./client";

export type ShotType = "远景" | "全景" | "中景" | "近景" | "特写";
export type CameraType = "固定" | "推" | "拉" | "摇" | "移" | "跟" | "手持";
export type ShotStatus = "normal" | "changed";

export interface Shot {
  id: number;
  episode_id: number;
  order_index: number;
  duration_est: number;
  shot_type: ShotType;
  camera: CameraType;
  description: string;
  dialogue: string;
  asset_ids: number[];
  status: ShotStatus;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface ShotPatch {
  shot_type?: ShotType;
  camera?: CameraType;
  description?: string;
  dialogue?: string;
  asset_ids?: number[];
}

const jsonHeaders = { "Content-Type": "application/json" };

export function parseShotResponse(value: unknown, status = 200): Shot {
  const record = requireObjectWithKeys(
    value,
    [
      "id",
      "episode_id",
      "order_index",
      "duration_est",
      "shot_type",
      "camera",
      "description",
      "dialogue",
      "asset_ids",
      "status",
      "revision",
      "created_at",
      "updated_at",
    ],
    [],
    status,
    "Shot response",
  );
  requirePositiveSafeInteger(record.id, "Shot.id", status);
  requirePositiveSafeInteger(record.episode_id, "Shot.episode_id", status);
  requirePositiveSafeInteger(record.order_index, "Shot.order_index", status);
  const duration = requireFiniteNumber(record.duration_est, "Shot.duration_est", status);
  if (duration <= 0) {
    return protocolError(status, "Shot.duration_est must be positive");
  }
  requireEnum(
    record.shot_type,
    ["远景", "全景", "中景", "近景", "特写"] as const,
    "Shot.shot_type",
    status,
  );
  requireEnum(
    record.camera,
    ["固定", "推", "拉", "摇", "移", "跟", "手持"] as const,
    "Shot.camera",
    status,
  );
  requireString(record.description, status, "Shot.description");
  requireString(record.dialogue, status, "Shot.dialogue");
  const assetIds = requireArray(record.asset_ids, status, "Shot.asset_ids");
  assetIds.forEach((assetId, index) => {
    requirePositiveSafeInteger(assetId, `Shot.asset_ids[${index}]`, status);
  });
  requireEnum(record.status, ["normal", "changed"] as const, "Shot.status", status);
  requirePositiveSafeInteger(record.revision, "Shot.revision", status);
  requireString(record.created_at, status, "Shot.created_at");
  requireString(record.updated_at, status, "Shot.updated_at");
  return record as unknown as Shot;
}

export function parseShotListResponse(
  value: unknown,
  status = 200,
): Shot[] {
  if (!Array.isArray(value)) {
    return protocolError(status, "Shot list response must be an array");
  }
  return value.map((item) => parseShotResponse(item, status));
}

export function listShots(episodeId: number): Promise<Shot[]> {
  const id = requirePositiveSafeInteger(episodeId, "episodeId");
  return requestJson<Shot[]>(
    `/episodes/${id}/shots`,
    undefined,
    parseShotListResponse,
  );
}

export function updateShot(id: number, input: ShotPatch): Promise<Shot> {
  return requestJson<Shot>(`/shots/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}
