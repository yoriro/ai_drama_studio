import { requestJson } from "./client";

export type TaskType =
  | "gen_assets"
  | "gen_shots"
  | "gen_asset_image"
  | "gen_clip_video";

export type TaskStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "canceled";

export interface Task {
  id: number;
  type: TaskType;
  target_id: number;
  request_id: string | null;
  status: TaskStatus;
  progress: number;
  error_msg: string | null;
  heartbeat_at: string | null;
  cancel_requested_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskEvent {
  task_id: number;
  type: TaskType;
  status: TaskStatus;
  progress: number;
  message: string;
}

export function listTasks(): Promise<Task[]> {
  return requestJson<Task[]>("/tasks");
}
