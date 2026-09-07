import {
  protocolError,
  requestJson,
  requireArray,
  requireEnum,
  requireFiniteNumber,
  requireNullableString,
  requireObjectWithKeys,
  requirePositiveSafeInteger,
  requireString,
} from "./client";

export const TASK_TYPES = [
  "gen_assets",
  "gen_shots",
  "gen_asset_image",
  "gen_clip_video",
] as const;

export type TaskType = (typeof TASK_TYPES)[number];

export const TASK_STATUSES = [
  "queued",
  "running",
  "done",
  "failed",
  "canceled",
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number];

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

export interface TaskListQuery {
  status?: TaskStatus;
  type?: TaskType;
  limit?: number;
}

function requireTaskProgress(
  value: unknown,
  context: string,
  status: number,
): number {
  const progress = requireFiniteNumber(value, context, status);
  if (progress < 0 || progress > 1) {
    return protocolError(status, `${context} must be between 0 and 1`);
  }
  return progress;
}

export function parseTaskResponse(value: unknown, status: number): Task {
  const object = requireObjectWithKeys(
    value,
    [
      "id",
      "type",
      "target_id",
      "request_id",
      "status",
      "progress",
      "error_msg",
      "heartbeat_at",
      "cancel_requested_at",
      "created_at",
      "started_at",
      "finished_at",
    ],
    [],
    status,
    "Task response",
  );
  return {
    id: requirePositiveSafeInteger(object.id, "Task.id", status),
    type: requireEnum(object.type, TASK_TYPES, "Task.type", status),
    target_id: requirePositiveSafeInteger(
      object.target_id,
      "Task.target_id",
      status,
    ),
    request_id: requireNullableString(
      object.request_id,
      status,
      "Task.request_id",
    ),
    status: requireEnum(object.status, TASK_STATUSES, "Task.status", status),
    progress: requireTaskProgress(object.progress, "Task.progress", status),
    error_msg: requireNullableString(
      object.error_msg,
      status,
      "Task.error_msg",
    ),
    heartbeat_at: requireNullableString(
      object.heartbeat_at,
      status,
      "Task.heartbeat_at",
    ),
    cancel_requested_at: requireNullableString(
      object.cancel_requested_at,
      status,
      "Task.cancel_requested_at",
    ),
    created_at: requireString(object.created_at, status, "Task.created_at"),
    started_at: requireNullableString(
      object.started_at,
      status,
      "Task.started_at",
    ),
    finished_at: requireNullableString(
      object.finished_at,
      status,
      "Task.finished_at",
    ),
  };
}

export function parseTaskListResponse(
  value: unknown,
  status: number,
): Task[] {
  return requireArray(value, status, "Task list response").map((item) =>
    parseTaskResponse(item, status),
  );
}

export function parseTaskEventResponse(
  value: unknown,
  status: number,
): TaskEvent {
  const object = requireObjectWithKeys(
    value,
    ["task_id", "type", "status", "progress", "message"],
    [],
    status,
    "Task event",
  );
  return {
    task_id: requirePositiveSafeInteger(
      object.task_id,
      "Task event.task_id",
      status,
    ),
    type: requireEnum(object.type, TASK_TYPES, "Task event.type", status),
    status: requireEnum(
      object.status,
      TASK_STATUSES,
      "Task event.status",
      status,
    ),
    progress: requireTaskProgress(
      object.progress,
      "Task event.progress",
      status,
    ),
    message: requireString(object.message, status, "Task event.message"),
  };
}

export function listTasks(query: TaskListQuery = {}): Promise<Task[]> {
  const search = new URLSearchParams();
  if (query.status !== undefined) {
    search.set("status", query.status);
  }
  if (query.type !== undefined) {
    search.set("type", query.type);
  }
  if (query.limit !== undefined) {
    search.set("limit", String(query.limit));
  }
  const suffix = search.toString();
  return requestJson<Task[]>(
    suffix.length === 0 ? "/tasks" : `/tasks?${suffix}`,
    undefined,
    parseTaskListResponse,
  );
}

export function getTask(taskId: number): Promise<Task> {
  const safeTaskId = requirePositiveSafeInteger(taskId, "task_id");
  return requestJson<Task>(
    `/tasks/${safeTaskId}`,
    undefined,
    parseTaskResponse,
  );
}
