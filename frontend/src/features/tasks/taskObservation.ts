import type { Task, TaskEvent, TaskListQuery } from "../../api/tasks";
import { getTask, listTasks } from "../../api/tasks";
import { openTaskWebSocket, parseTaskEvent } from "../../api/ws";
import { ApiProtocolError } from "../../api/client";

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000] as const;

export interface TaskObservationSocket {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  close(): void;
}

export type TaskListPhase = "loading" | "updating" | "ready" | "error";
export type TaskConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting";

export interface TaskObservationDetailError {
  taskId: number;
  error: unknown;
}

export interface TaskObservationState {
  tasks: Task[];
  listPhase: TaskListPhase;
  listError: unknown | null;
  detailError: TaskObservationDetailError | null;
  socketError: unknown | null;
  connectionState: TaskConnectionState;
}

export interface TaskObservationOptions {
  query: TaskListQuery;
  readTasks?: (query: TaskListQuery) => Promise<Task[]>;
  readTask?: (taskId: number) => Promise<Task>;
  openSocket?: () => TaskObservationSocket;
}

export interface TaskObservationController {
  start(): void;
  dispose(): void;
  subscribe(listener: (state: TaskObservationState) => void): () => void;
  getState(): TaskObservationState;
}

interface ListRequest {
  epoch: number;
  eventRevision: number;
  initial: boolean;
  invalidated: boolean;
}

interface DetailRequest {
  epoch: number;
  terminalRefreshRequested: boolean;
}

function defaultSocket(): TaskObservationSocket {
  return openTaskWebSocket();
}

function isTerminalStatus(status: Task["status"]): boolean {
  return status === "done" || status === "failed" || status === "canceled";
}

function errorMessageFromEvent(event: TaskEvent): string {
  const prefix = "任务失败：";
  return event.message.startsWith(prefix)
    ? event.message.slice(prefix.length)
    : event.message;
}

function applyEventToTask(task: Task, event: TaskEvent): Task {
  return {
    ...task,
    type: event.type,
    status: event.status,
    progress: event.progress,
    error_msg:
      event.status === "failed"
        ? errorMessageFromEvent(event)
        : event.status === "done" || event.status === "canceled"
          ? null
          : task.error_msg,
  };
}

function mergeTaskWithEvent(task: Task, event: TaskEvent | undefined): Task {
  return event === undefined ? task : applyEventToTask(task, event);
}

function sortTasks(tasks: readonly Task[]): Task[] {
  return [...tasks].sort((left, right) => right.id - left.id);
}

function matchesQuery(task: Task, query: TaskListQuery): boolean {
  return (
    (query.status === undefined || task.status === query.status) &&
    (query.type === undefined || task.type === query.type)
  );
}

function limitTasks(tasks: readonly Task[], query: TaskListQuery): Task[] {
  const limit = query.limit ?? 50;
  return sortTasks(tasks.filter((task) => matchesQuery(task, query))).slice(
    0,
    limit,
  );
}

function eventKeepsTaskInQuery(
  task: Task,
  event: TaskEvent,
  query: TaskListQuery,
): boolean {
  return matchesQuery(applyEventToTask(task, event), query);
}

function createInitialState(): TaskObservationState {
  return {
    tasks: [],
    listPhase: "loading",
    listError: null,
    detailError: null,
    socketError: null,
    connectionState: "connecting",
  };
}

class TaskObservation implements TaskObservationController {
  private readonly query: TaskListQuery;
  private readonly readTasks: (
    query: TaskListQuery,
  ) => Promise<Task[]>;
  private readonly readTask: (taskId: number) => Promise<Task>;
  private readonly openSocket: () => TaskObservationSocket;
  private readonly listeners = new Set<
    (state: TaskObservationState) => void
  >();
  private state = createInitialState();
  private started = false;
  private disposed = false;
  private socket: TaskObservationSocket | null = null;
  private socketEpoch = 0;
  private synchronized = false;
  private synchronizationFailed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private listRequest: ListRequest | null = null;
  private eventRevision = 0;
  private knownTaskIds = new Set<number>();
  private bufferedEvents: TaskEvent[] = [];
  private latestEvents = new Map<number, TaskEvent>();
  private readonly detailRequests = new Map<number, DetailRequest>();
  private readonly detailLoaded = new Set<number>();
  private refreshScheduled = false;

  constructor(options: TaskObservationOptions) {
    this.query = options.query;
    this.readTasks = options.readTasks ?? listTasks;
    this.readTask = options.readTask ?? getTask;
    this.openSocket = options.openSocket ?? defaultSocket;
  }

  start(): void {
    if (this.started || this.disposed) {
      return;
    }
    this.started = true;
    this.connect();
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.started = false;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.listRequest = null;
    this.socketEpoch += 1;
    const socket = this.socket;
    this.socket = null;
    if (socket !== null) {
      socket.close();
    }
    this.listeners.clear();
  }

  subscribe(listener: (state: TaskObservationState) => void): () => void {
    this.listeners.add(listener);
    listener(this.getState());
    return () => {
      this.listeners.delete(listener);
    };
  }

  getState(): TaskObservationState {
    return {
      ...this.state,
      tasks: [...this.state.tasks],
    };
  }

  private connect(): void {
    if (this.disposed) {
      return;
    }

    const socket = this.openSocket();
    this.socket = socket;
    this.socketEpoch += 1;
    this.synchronized = false;
    this.synchronizationFailed = false;
    this.bufferedEvents = [];
    this.knownTaskIds = new Set(this.state.tasks.map((task) => task.id));
    this.latestEvents.clear();
    this.detailRequests.clear();
    this.detailLoaded.clear();
    this.refreshScheduled = false;
    this.state.connectionState = "connecting";
    this.emit();

    socket.onopen = () => {
      if (!this.isActiveSocket(socket)) {
        return;
      }
      this.synchronized = false;
      this.synchronizationFailed = false;
      this.startListRequest(socket, true);
    };
    socket.onmessage = (message) => {
      this.handleMessage(socket, message);
    };
    socket.onerror = () => {
      if (!this.isActiveSocket(socket)) {
        return;
      }
      this.state.socketError = new Error("Task WebSocket connection failed");
      this.emit();
      socket.close();
    };
    socket.onclose = () => {
      if (!this.isActiveSocket(socket)) {
        return;
      }
      this.socket = null;
      this.synchronized = false;
      this.synchronizationFailed = false;
      this.listRequest = null;
      this.state.connectionState = "reconnecting";
      this.emit();
      this.scheduleReconnect();
    };
  }

  private handleMessage(
    socket: TaskObservationSocket,
    message: MessageEvent,
  ): void {
    if (!this.isActiveSocket(socket) || this.synchronizationFailed) {
      return;
    }
    if (typeof message.data !== "string") {
      this.handleSocketProtocolError(
        socket,
        new TypeError("Task WebSocket messages must be text"),
      );
      return;
    }

    let event: TaskEvent;
    try {
      event = parseTaskEvent(message.data);
    } catch (error: unknown) {
      if (error instanceof SyntaxError || error instanceof ApiProtocolError) {
        this.handleSocketProtocolError(socket, error);
        return;
      }
      throw error;
    }

    if (!this.synchronized) {
      this.bufferedEvents.push(event);
      return;
    }
    this.processEvent(socket, event);
  }

  private handleSocketProtocolError(
    socket: TaskObservationSocket,
    error: unknown,
  ): void {
    if (!this.isActiveSocket(socket)) {
      return;
    }
    this.synchronizationFailed = true;
    this.synchronized = false;
    this.state.socketError = error;
    this.emit();
    socket.close();
    this.scheduleReconnect();
  }

  private processEvent(
    socket: TaskObservationSocket,
    event: TaskEvent,
  ): void {
    if (!this.isActiveSocket(socket)) {
      return;
    }
    const previousEvent = this.latestEvents.get(event.task_id);
    if (
      previousEvent !== undefined &&
      previousEvent.type === event.type &&
      previousEvent.status === event.status &&
      previousEvent.progress === event.progress &&
      previousEvent.message === event.message
    ) {
      return;
    }
    this.eventRevision += 1;
    this.latestEvents.set(event.task_id, event);
    const current = this.state.tasks.find((task) => task.id === event.task_id);
    const isKnown = this.knownTaskIds.has(event.task_id);
    if (current !== undefined) {
      if (eventKeepsTaskInQuery(current, event, this.query)) {
        this.state.tasks = limitTasks(
          this.state.tasks.map((task) =>
            task.id === event.task_id ? applyEventToTask(task, event) : task,
          ),
          this.query,
        );
      } else {
        this.state.tasks = this.state.tasks.filter(
          (task) => task.id !== event.task_id,
        );
      }
      this.emit();
    }

    if (!isKnown || current === undefined) {
      this.requestTaskDetail(
        event.task_id,
        isTerminalStatus(event.status),
      );
      this.requestListRefresh();
      return;
    }

    if (!eventKeepsTaskInQuery(current, event, this.query)) {
      this.requestListRefresh();
    }
    if (isTerminalStatus(event.status)) {
      this.requestTaskDetail(event.task_id, true);
      this.requestListRefresh();
    }
  }

  private requestTaskDetail(taskId: number, terminalRefresh: boolean): void {
    const pending = this.detailRequests.get(taskId);
    if (pending !== undefined) {
      if (terminalRefresh) {
        pending.terminalRefreshRequested = true;
      }
      return;
    }
    if (!terminalRefresh && this.detailLoaded.has(taskId)) {
      return;
    }

    const request: DetailRequest = {
      epoch: this.socketEpoch,
      terminalRefreshRequested: false,
    };
    this.detailRequests.set(taskId, request);
    void Promise.resolve()
      .then(() => this.readTask(taskId))
      .then(
      (task) => {
        if (!this.isCurrentDetailRequest(taskId, request)) {
          return;
        }
        this.detailLoaded.add(taskId);
        if (this.state.detailError?.taskId === taskId) {
          this.state.detailError = null;
        }
        const event = this.latestEvents.get(taskId);
        const merged = mergeTaskWithEvent(task, event);
        const index = this.state.tasks.findIndex(
          (candidate) => candidate.id === taskId,
        );
        if (index !== -1) {
          const next = [...this.state.tasks];
          next[index] = merged;
          this.state.tasks = limitTasks(next, this.query);
          this.emit();
        }
        this.requestListRefresh();
      },
      (error: unknown) => {
        if (!this.isCurrentDetailRequest(taskId, request)) {
          return;
        }
        this.state.detailError = { taskId, error };
        this.emit();
        this.requestListRefresh();
      },
    )
      .finally(() => {
        if (!this.isCurrentDetailRequest(taskId, request)) {
          return;
        }
        this.detailRequests.delete(taskId);
        if (request.terminalRefreshRequested && !this.disposed) {
          this.requestTaskDetail(taskId, true);
        }
      });
  }

  private requestListRefresh(): void {
    if (this.disposed || this.socket === null || !this.synchronized) {
      return;
    }
    if (this.listRequest !== null) {
      this.listRequest.invalidated = true;
      return;
    }
    if (this.refreshScheduled) {
      return;
    }
    this.refreshScheduled = true;
    void Promise.resolve().then(() => {
      this.refreshScheduled = false;
      if (
        this.disposed ||
        this.socket === null ||
        !this.synchronized ||
        this.listRequest !== null
      ) {
        return;
      }
      this.startListRequest(this.socket, false);
    });
  }

  private startListRequest(
    socket: TaskObservationSocket,
    initial: boolean,
  ): void {
    if (!this.isActiveSocket(socket) || this.disposed) {
      return;
    }
    const request: ListRequest = {
      epoch: this.socketEpoch,
      eventRevision: this.eventRevision,
      initial,
      invalidated: false,
    };
    this.listRequest = request;
    this.state.listPhase =
      initial && this.state.tasks.length === 0 ? "loading" : "updating";
    this.emit();

    void Promise.resolve()
      .then(() => this.readTasks(this.query))
      .then(
      (tasks) => {
        if (!this.isCurrentListRequest(socket, request)) {
          return;
        }
        if (
          request.invalidated ||
          request.eventRevision !== this.eventRevision
        ) {
          this.finishInvalidatedListRequest(request);
          return;
        }
        this.knownTaskIds = new Set(tasks.map((task) => task.id));
        this.state.tasks = limitTasks(tasks, this.query);
        this.state.listError = null;
        this.state.socketError = null;
        this.state.listPhase = "ready";
        this.state.connectionState = "connected";
        this.synchronized = true;
        this.synchronizationFailed = false;
        this.reconnectAttempt = 0;
        this.listRequest = null;
        const bufferedEvents = this.bufferedEvents.splice(0);
        this.emit();
        bufferedEvents.forEach((event) => this.processEvent(socket, event));
      },
      (error: unknown) => {
        if (!this.isCurrentListRequest(socket, request)) {
          return;
        }
        if (
          request.invalidated ||
          request.eventRevision !== this.eventRevision
        ) {
          this.finishInvalidatedListRequest(request);
          return;
        }
        this.listRequest = null;
        this.state.listError = error;
        this.state.listPhase = "error";
        this.emit();
        if (request.initial) {
          this.synchronizationFailed = true;
          this.synchronized = false;
          socket.close();
          this.scheduleReconnect();
        }
      },
    );
  }

  private finishInvalidatedListRequest(request: ListRequest): void {
    if (this.listRequest !== request) {
      return;
    }
    this.listRequest = null;
    if (this.socket !== null && this.synchronized && !this.disposed) {
      this.startListRequest(this.socket, false);
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectTimer !== null) {
      return;
    }
    const delay =
      this.reconnectAttempt < RECONNECT_DELAYS_MS.length
        ? RECONNECT_DELAYS_MS[this.reconnectAttempt]
        : RECONNECT_DELAYS_MS[RECONNECT_DELAYS_MS.length - 1];
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private isActiveSocket(socket: TaskObservationSocket): boolean {
    return !this.disposed && this.socket === socket;
  }

  private isCurrentListRequest(
    socket: TaskObservationSocket,
    request: ListRequest,
  ): boolean {
    return (
      this.isActiveSocket(socket) &&
      this.listRequest === request &&
      request.epoch === this.socketEpoch
    );
  }

  private isCurrentDetailRequest(
    taskId: number,
    request: DetailRequest,
  ): boolean {
    return (
      !this.disposed &&
      this.detailRequests.get(taskId) === request &&
      request.epoch === this.socketEpoch
    );
  }

  private emit(): void {
    const snapshot = this.getState();
    for (const listener of this.listeners) {
      listener(snapshot);
    }
  }
}

export function createTaskObservation(
  options: TaskObservationOptions,
): TaskObservationController {
  return new TaskObservation(options);
}

export { createInitialState as createTaskObservationInitialState };
