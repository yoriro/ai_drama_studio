import { requestJson } from "./client";

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

export function listShots(episodeId: number): Promise<Shot[]> {
  return requestJson<Shot[]>(`/episodes/${episodeId}/shots`);
}

export function updateShot(id: number, input: ShotPatch): Promise<Shot> {
  return requestJson<Shot>(`/shots/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}
