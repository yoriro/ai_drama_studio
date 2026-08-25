import { useEffect, useState } from "react";

import { listTasks } from "../api/tasks";
import type { Task, TaskEvent, TaskStatus, TaskType } from "../api/tasks";
import {
  closeWebSocket,
  openTaskWebSocket,
  parseTaskEvent,
} from "../api/ws";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

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

function applyTaskEvent(
  current: TaskListItem[],
  event: TaskEvent,
): TaskListItem[] {
  const index = current.findIndex((task) => task.id === event.task_id);
  if (index === -1) {
    return sortTasks([
      ...current,
      {
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
      },
    ]);
  }

  const existing = current[index];
  const next = [...current];
  next[index] = {
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
  return sortTasks(next);
}

function formatTaskTime(value: string | null): string {
  return value === null ? "—" : new Date(value).toLocaleString();
}

export function TasksPage() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [restState, setRestState] = useState<RestState>("loading");
  const [restError, setRestError] = useState<unknown>(null);
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("connecting");

  useEffect(() => {
    let disposed = false;
    let activeSocket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;

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

      async function synchronize(): Promise<void> {
        try {
          const snapshot = await listTasks();
          if (!isActive(socket)) {
            return;
          }

          const events = bufferedEvents.splice(0);
          const synchronizedTasks = events.reduce(
            (current, event) => applyTaskEvent(current, event),
            snapshot.map(toTaskListItem),
          );
          synchronized = true;
          reconnectAttempt = 0;
          setTasks(synchronizedTasks);
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
        setTasks((current) => applyTaskEvent(current, event));
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
  }, []);

  return (
    <>
      <PageTitle>任务中心</PageTitle>
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
          <EmptyState message="暂无任务" />
        </div>
      )}
      {restState !== "loading" && tasks.length > 0 && (
        <section
          aria-label="任务列表"
          className="task-list"
          data-task-state={restState === "ready" ? "ready" : "rest-error-list"}
        >
          {tasks.map((task) => (
            <article className="entity-card task-card" key={task.id}>
              <div className="task-heading">
                <h2>任务 #{task.id}</h2>
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
          ))}
        </section>
      )}
    </>
  );
}
