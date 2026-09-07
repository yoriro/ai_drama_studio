import { useEffect, useState } from "react";

import { getTask, listTasks } from "../api/tasks";
import type { Task, TaskEvent, TaskStatus, TaskType } from "../api/tasks";
import {
  closeWebSocket,
  openTaskWebSocket,
  parseTaskEvent,
} from "../api/ws";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { AuxiliaryPageReturn } from "../components/AuxiliaryPageReturn";
import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";
import {
  buildTaskListQuery,
  groupTasksByStatus,
  TASK_LIMIT_OPTIONS,
  TASK_STATUS_FILTER_OPTIONS,
  TASK_TYPE_FILTER_OPTIONS,
  type TaskListLimit,
  type TaskStatusFilter,
  type TaskTypeFilter,
} from "../features/tasks/taskList";

const RECONNECT_DELAYS_MS = [1000, 2000, 5000] as const;

interface TaskListItem {
  id: number;
  type: TaskType;
  target_id: number | null;
  request_id: string | null;
  status: TaskStatus;
  progress: number;
  error_msg: string | null;
  heartbeat_at: string | null;
  cancel_requested_at: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

type RestState = "loading" | "ready" | "error";
type ConnectionState = "connecting" | "connected" | "reconnecting";

function toTaskListItem(task: Task): TaskListItem {
  return { ...task };
}

function errorMessageFromEvent(event: TaskEvent): string {
  const prefix = "任务失败：";
  return event.message.startsWith(prefix)
    ? event.message.slice(prefix.length)
    : event.message;
}

function sortTasks(tasks: TaskListItem[]): TaskListItem[] {
  return [...tasks].sort((left, right) => right.id - left.id);
}

function taskFromEvent(event: TaskEvent): TaskListItem {
  return {
    id: event.task_id,
    type: event.type,
    target_id: null,
    request_id: null,
    status: event.status,
    progress: event.progress,
    error_msg:
      event.status === "failed" ? errorMessageFromEvent(event) : null,
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: null,
    started_at: null,
    finished_at: null,
  };
}

function applyEventToTask(
  existing: TaskListItem,
  event: TaskEvent,
): TaskListItem {
  return {
    ...existing,
    type: event.type,
    status: event.status,
    progress: event.progress,
    error_msg:
      event.status === "failed"
        ? errorMessageFromEvent(event)
        : event.status === "done" || event.status === "canceled"
          ? null
          : existing.error_msg,
  };
}

function mergeTaskDetails(
  existing: TaskListItem,
  task: Task,
  latestEvent: TaskEvent | undefined,
): TaskListItem {
  const merged: TaskListItem = {
    ...existing,
    target_id: existing.target_id ?? task.target_id,
    request_id: existing.request_id ?? task.request_id,
    heartbeat_at: existing.heartbeat_at ?? task.heartbeat_at,
    cancel_requested_at:
      existing.cancel_requested_at ?? task.cancel_requested_at,
    created_at: existing.created_at ?? task.created_at,
    started_at: existing.started_at ?? task.started_at,
    finished_at: existing.finished_at ?? task.finished_at,
    error_msg: existing.error_msg ?? task.error_msg,
  };

  return latestEvent === undefined
    ? merged
    : applyEventToTask(merged, latestEvent);
}

function applyTaskEvent(
  current: TaskListItem[],
  event: TaskEvent,
): TaskListItem[] {
  const index = current.findIndex((task) => task.id === event.task_id);
  if (index === -1) {
    return sortTasks([...current, taskFromEvent(event)]);
  }

  const existing = current[index];
  const next = [...current];
  next[index] = applyEventToTask(existing, event);
  return sortTasks(next);
}

function formatTaskTime(value: string | null): string {
  return value === null ? "—" : new Date(value).toLocaleString();
}

function isTerminalTaskEvent(event: TaskEvent): boolean {
  return (
    event.status === "done" ||
    event.status === "failed" ||
    event.status === "canceled"
  );
}

export function TasksPage() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [restState, setRestState] = useState<RestState>("loading");
  const [restError, setRestError] = useState<unknown>(null);
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("connecting");
  const [statusFilter, setStatusFilter] =
    useState<TaskStatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>("all");
  const [taskLimit, setTaskLimit] = useState<TaskListLimit>(50);

  const taskGroups = groupTasksByStatus(tasks);

  useEffect(() => {
    let disposed = false;
    let activeSocket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    const listQuery = buildTaskListQuery({
      status: statusFilter,
      type: typeFilter,
      limit: taskLimit,
    });
    setTasks([]);
    setRestState("loading");
    setRestError(null);
    setConnectionState("connecting");

    function isActive(socket: WebSocket): boolean {
      return !disposed && activeSocket === socket;
    }

    function scheduleReconnect(): void {
      if (disposed || reconnectTimer !== null) {
        return;
      }

      const delay =
        reconnectAttempt < RECONNECT_DELAYS_MS.length
          ? RECONNECT_DELAYS_MS[reconnectAttempt]
          : 10000;
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    }

    function connect(): void {
      if (disposed) {
        return;
      }

      setConnectionState("connecting");
      const socket = openTaskWebSocket();
      activeSocket = socket;
      let synchronized = false;
      let synchronizationFailed = false;
      const bufferedEvents: TaskEvent[] = [];
      const knownTaskIds = new Set<number>();
      const latestEvents = new Map<number, TaskEvent>();
      const detailRequests = new Map<number, Promise<void>>();
      const detailRequestStates = new Map<number, "succeeded" | "failed">();
      const terminalDetailRequests = new Set<number>();

      function hydrateTaskDetails(
        taskId: number,
        terminalRefresh = false,
      ): void {
        if (detailRequests.has(taskId)) {
          if (terminalRefresh) {
            terminalDetailRequests.add(taskId);
          }
          return;
        }
        if (detailRequestStates.get(taskId) === "failed") {
          return;
        }
        if (terminalRefresh) {
          if (terminalDetailRequests.has(taskId)) {
            return;
          }
          terminalDetailRequests.add(taskId);
        } else if (detailRequestStates.has(taskId)) {
          return;
        }

        const isTerminalRefresh = terminalRefresh;
        let detailRequest: Promise<void>;
        detailRequest = getTask(taskId)
          .then((task) => {
            detailRequestStates.set(taskId, "succeeded");
            if (!isActive(socket)) {
              return;
            }

            setTasks((current) => {
              const index = current.findIndex((item) => item.id === taskId);
              const existing =
                index === -1 ? toTaskListItem(task) : current[index];
              const mergedTask = mergeTaskDetails(
                existing,
                task,
                latestEvents.get(taskId),
              );
              if (index === -1) {
                return sortTasks([...current, mergedTask]);
              }

              const next = [...current];
              next[index] = mergedTask;
              return sortTasks(next);
            });
          })
          .catch((error: unknown) => {
            detailRequestStates.set(taskId, "failed");
            if (!isActive(socket)) {
              return;
            }
            setRestError(error);
            setRestState("error");
          })
          .finally(() => {
            if (detailRequests.get(taskId) === detailRequest) {
              detailRequests.delete(taskId);
            }
            if (
              !isTerminalRefresh &&
              detailRequestStates.get(taskId) === "succeeded" &&
              terminalDetailRequests.has(taskId) &&
              isActive(socket)
            ) {
              terminalDetailRequests.delete(taskId);
              hydrateTaskDetails(taskId, true);
            }
          });
        detailRequests.set(taskId, detailRequest);
      }

      function processEvent(event: TaskEvent): void {
        latestEvents.set(event.task_id, event);
        const isUnknownTask = !knownTaskIds.has(event.task_id);
        if (isUnknownTask) {
          knownTaskIds.add(event.task_id);
          hydrateTaskDetails(event.task_id, isTerminalTaskEvent(event));
        } else if (isTerminalTaskEvent(event)) {
          hydrateTaskDetails(event.task_id, true);
        }
        setTasks((current) => applyTaskEvent(current, event));
      }

      async function synchronize(): Promise<void> {
        try {
          const snapshot = await listTasks(listQuery);
          if (!isActive(socket)) {
            return;
          }

          const events = bufferedEvents.splice(0);
          snapshot.forEach((task) => knownTaskIds.add(task.id));
          synchronized = true;
          reconnectAttempt = 0;
          setTasks(snapshot.map(toTaskListItem));
          events.forEach(processEvent);
          setRestError(null);
          setRestState("ready");
          setConnectionState("connected");
        } catch (error: unknown) {
          if (!isActive(socket)) {
            return;
          }

          synchronizationFailed = true;
          bufferedEvents.length = 0;
          setRestError(error);
          setRestState("error");
          setConnectionState("connected");
        }
      }

      socket.onopen = () => {
        if (!isActive(socket)) {
          return;
        }
        void synchronize();
      };

      socket.onmessage = (message: MessageEvent) => {
        if (!isActive(socket) || synchronizationFailed) {
          return;
        }
        if (typeof message.data !== "string") {
          throw new TypeError("Task WebSocket messages must be text");
        }

        const event = parseTaskEvent(message.data);
        if (!synchronized) {
          bufferedEvents.push(event);
          return;
        }
        processEvent(event);
      };

      socket.onerror = () => {
        if (isActive(socket)) {
          closeWebSocket(socket);
        }
      };

      socket.onclose = () => {
        if (!isActive(socket)) {
          return;
        }
        activeSocket = null;
        setConnectionState("reconnecting");
        scheduleReconnect();
      };
    }

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (activeSocket !== null) {
        const socket = activeSocket;
        activeSocket = null;
        closeWebSocket(socket);
      }
    };
  }, [statusFilter, taskLimit, typeFilter]);

  function renderTaskCard(task: TaskListItem) {
    return (
      <article className="entity-card task-card" key={task.id}>
        <div className="task-heading">
          <h3>任务 #{task.id}</h3>
          <span className="task-status">{task.status}</span>
        </div>
        <p>
          类型：{task.type}；目标 ID：{task.target_id ?? "—"}
        </p>
        <div className="task-progress-row">
          <progress
            aria-label={`任务 ${task.id} 进度`}
            max={1}
            value={task.progress}
          />
          <span>{Math.round(task.progress * 100)}%</span>
        </div>
        {task.error_msg !== null && (
          <p className="error-message">{task.error_msg}</p>
        )}
        <dl className="task-times">
          <div>
            <dt>创建时间</dt>
            <dd>{formatTaskTime(task.created_at)}</dd>
          </div>
          <div>
            <dt>开始时间</dt>
            <dd>{formatTaskTime(task.started_at)}</dd>
          </div>
          <div>
            <dt>完成时间</dt>
            <dd>{formatTaskTime(task.finished_at)}</dd>
          </div>
        </dl>
      </article>
    );
  }

  return (
    <>
      <AuxiliaryPageReturn />
      <PageTitle>任务中心</PageTitle>
      <section aria-label="任务筛选" className="panel task-filters">
        <h2>任务筛选</h2>
        <div className="task-filter-grid">
          <label>
            状态
            <select
              aria-label="状态筛选"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value as TaskStatusFilter)
              }
            >
              {TASK_STATUS_FILTER_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status === "all" ? "全部" : status}
                </option>
              ))}
            </select>
          </label>
          <label>
            类型
            <select
              aria-label="类型筛选"
              value={typeFilter}
              onChange={(event) =>
                setTypeFilter(event.target.value as TaskTypeFilter)
              }
            >
              {TASK_TYPE_FILTER_OPTIONS.map((type) => (
                <option key={type} value={type}>
                  {type === "all" ? "全部" : type}
                </option>
              ))}
            </select>
          </label>
          <label>
            数量
            <select
              aria-label="任务数量"
              value={taskLimit}
              onChange={(event) =>
                setTaskLimit(Number(event.target.value) as TaskListLimit)
              }
            >
              {TASK_LIMIT_OPTIONS.map((limit) => (
                <option key={limit} value={limit}>
                  {limit}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="field-hint">
          最多显示匹配条件的最近 {taskLimit} 条，本次已加载 {tasks.length} 条
        </p>
      </section>
      {connectionState === "reconnecting" && (
        <p
          aria-live="polite"
          className="connection-message"
          data-task-state="reconnecting"
          role="status"
        >
          实时连接已断开，正在重连
        </p>
      )}
      {restState === "loading" && (
        <section
          aria-live="polite"
          className="panel"
          data-task-state="loading"
        >
          <p>正在加载任务…</p>
        </section>
      )}
      {restState === "error" && (
        <section data-task-state="rest-error">
          <ApiErrorMessage error={restError} />
        </section>
      )}
      {restState === "ready" && tasks.length === 0 && (
        <div data-task-state="empty">
          <EmptyState message="当前条件下暂无任务" />
        </div>
      )}
      {restState !== "loading" && tasks.length > 0 && (
        <>
          {taskGroups.inProgress.length > 0 && (
            <section aria-label="进行中任务" className="task-group">
              <h2>进行中</h2>
              <div className="task-list" data-task-state="ready">
                {taskGroups.inProgress.map(renderTaskCard)}
              </div>
            </section>
          )}
          {taskGroups.history.length > 0 && (
            <section aria-label="历史任务" className="task-group">
              <h2>历史</h2>
              <div className="task-list" data-task-state="ready">
                {taskGroups.history.map(renderTaskCard)}
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}
