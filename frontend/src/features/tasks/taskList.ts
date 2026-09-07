import {
  TASK_STATUSES,
  TASK_TYPES,
  type TaskListQuery,
  type TaskStatus,
} from "../../api/tasks";

export const TASK_STATUS_FILTER_OPTIONS = [
  "all",
  ...TASK_STATUSES,
] as const;
export type TaskStatusFilter = (typeof TASK_STATUS_FILTER_OPTIONS)[number];

export const TASK_TYPE_FILTER_OPTIONS = ["all", ...TASK_TYPES] as const;
export type TaskTypeFilter = (typeof TASK_TYPE_FILTER_OPTIONS)[number];

export const TASK_LIMIT_OPTIONS = [20, 50, 100] as const;
export type TaskListLimit = (typeof TASK_LIMIT_OPTIONS)[number];

export interface TaskListFilters {
  status: TaskStatusFilter;
  type: TaskTypeFilter;
  limit: TaskListLimit;
}

export function buildTaskListQuery(filters: TaskListFilters): TaskListQuery {
  return {
    ...(filters.status === "all" ? {} : { status: filters.status }),
    ...(filters.type === "all" ? {} : { type: filters.type }),
    limit: filters.limit,
  };
}

export interface GroupedTasks<T> {
  inProgress: T[];
  history: T[];
}

interface IdentifiedTask {
  id: number;
  status: TaskStatus;
}

export function groupTasksByStatus<T extends IdentifiedTask>(
  tasks: readonly T[],
): GroupedTasks<T> {
  const sorted = [...tasks].sort((left, right) => right.id - left.id);
  return {
    inProgress: sorted.filter(
      (task) => task.status === "queued" || task.status === "running",
    ),
    history: sorted.filter(
      (task) =>
        task.status === "done" ||
        task.status === "failed" ||
        task.status === "canceled",
    ),
  };
}
