import type { Task, TaskEvent, TaskListQuery } from "../../api/tasks";
import { cancelTask as requestCancelTask, getTask, listTasks } from "../../api/tasks";
import { openTaskWebSocket, parseTaskEvent } from "../../api/ws";
import { ApiError, ApiProtocolError } from "../../api/client";

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

export type TaskDetailPhase = "idle" | "loading" | "ready" | "error";

export interface TaskDetailState {
  phase: TaskDetailPhase;
  task: Task | null;
  error: unknown | null;
}

export type TaskCancelPhase =
  | "posting"
  | "confirming"
  | "error"
  | "unknown";

export interface TaskCancelState {
  phase: TaskCancelPhase;
  error: unknown | null;
  authorityPending: boolean;
}

export interface TaskObservationDetailError {
  taskId: number;
  error: unknown;
  protocol: boolean;
}

export interface TaskObservationState {
  tasks: Task[];
  listPhase: TaskListPhase;
  listError: unknown | null;
  detailError: TaskObservationDetailError | null;
  taskDetails: Record<number, TaskDetailState>;
  cancelStates: Record<number, TaskCancelState>;
  socketError: unknown | null;
  connectionState: TaskConnectionState;
}

export interface TaskObservationOptions {
  query: TaskListQuery;
  readTasks?: (query: TaskListQuery) => Promise<Task[]>;
  readTask?: (taskId: number) => Promise<Task>;
  submitCancel?: (taskId: number) => Promise<Task>;
  openSocket?: () => TaskObservationSocket;
}

export interface TaskObservationController {
  start(): void;
  dispose(): void;
  subscribe(listener: (state: TaskObservationState) => void): () => void;
  getState(): TaskObservationState;
  setQuery(query: TaskListQuery): void;
  loadTaskDetail(taskId: number): void;
  cancelTask(taskId: number): void;
}

interface ListRequest {
  epoch: number;
  eventRevision: number;
  query: TaskListQuery;
  initial: boolean;
  invalidated: boolean;
}

interface DetailRequest {
  epoch: number;
  explicitRequested: boolean;
  listRefreshRequested: boolean;
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
    taskDetails: {},
    cancelStates: {},
    socketError: null,
    connectionState: "connecting",
  };
}

class TaskObservation implements TaskObservationController {
  private query: TaskListQuery;
  private readonly readTasks: (
    query: TaskListQuery,
  ) => Promise<Task[]>;
  private readonly readTask: (taskId: number) => Promise<Task>;
  private readonly submitCancel: (taskId: number) => Promise<Task>;
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
  private readonly cancelRequests = new Map<number, object>();
  private readonly cancelConfirmations = new Set<number>();
  private readonly cancelReconciliations = new Map<number, object>();
  private refreshScheduled = false;

  constructor(options: TaskObservationOptions) {
    this.query = options.query;
    this.readTasks = options.readTasks ?? listTasks;
    this.readTask = options.readTask ?? getTask;
    this.submitCancel = options.submitCancel ?? requestCancelTask;
    this.openSocket = options.openSocket ?? defaultSocket;
  }

  start(): void {
    if (this.started || this.disposed) {
      return;
    }
    this.started = true;
    this.connect();
  }

  setQuery(query: TaskListQuery): void {
    if (
      this.query.status === query.status &&
      this.query.type === query.type &&
      this.query.limit === query.limit
    ) {
      return;
    }
    this.query = { ...query };
    this.eventRevision += 1;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const socket = this.socket;
    this.socket = null;
    if (socket !== null) {
      socket.close();
    }
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
    this.cancelRequests.clear();
    this.cancelConfirmations.clear();
    this.cancelReconciliations.clear();
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
      taskDetails: { ...this.state.taskDetails },
      cancelStates: { ...this.state.cancelStates },
    };
  }

  loadTaskDetail(taskId: number): void {
    const existing = this.state.taskDetails[taskId];
    if (existing?.phase === "loading" || existing?.phase === "ready") {
      return;
    }
    this.state.taskDetails = {
      ...this.state.taskDetails,
      [taskId]: { phase: "loading", task: null, error: null },
    };
    this.emit();
    this.requestTaskDetail(taskId, false, true, false);
  }

  cancelTask(taskId: number): void {
    if (this.disposed || this.cancelRequests.has(taskId)) {
      return;
    }
    const task = this.state.tasks.find((candidate) => candidate.id === taskId);
    if (
      task === undefined ||
      isTerminalStatus(task.status) ||
      (task.status === "running" && task.cancel_requested_at !== null)
    ) {
      return;
    }

    const cancelStates = { ...this.state.cancelStates };
    delete cancelStates[taskId];
    this.state.cancelStates = cancelStates;
    this.cancelReconciliations.delete(taskId);
    const request = {};
    this.cancelRequests.set(taskId, request);
    this.state.cancelStates = {
      ...this.state.cancelStates,
      [taskId]: { phase: "posting", error: null, authorityPending: false },
    };
    this.emit();

    void Promise.resolve()
      .then(() => this.submitCancel(taskId))
      .then(
        () => {
          if (!this.isCurrentCancelRequest(taskId, request)) {
            return;
          }
          this.cancelConfirmations.add(taskId);
          this.state.cancelStates = {
            ...this.state.cancelStates,
            [taskId]: { phase: "confirming", error: null, authorityPending: true },
          };
          this.emit();
          if (this.state.tasks.some((task) => task.id === taskId)) {
            this.requestTaskDetail(taskId, false, true, true);
          }
        },
        (error: unknown) => {
          if (!this.isCurrentCancelRequest(taskId, request)) {
            return;
          }
          this.cancelReconciliations.set(taskId, request);
          const status = error instanceof ApiError ? error.status : null;
          const phase = status === 404 || status === 409 ? "error" : "unknown";
          this.state.cancelStates = {
            ...this.state.cancelStates,
            [taskId]: {
              phase,
              error,
              authorityPending: true,
            },
          };
          this.emit();
          if (status === 404) {
            this.requestListRefresh();
          } else {
            this.requestTaskDetail(taskId, false, true, true);
          }
        },
      );
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
    const resetDetails = { ...this.state.taskDetails };
    for (const [taskId, detail] of Object.entries(resetDetails)) {
      if (detail.phase === "loading") {
        resetDetails[Number(taskId)] = {
          phase: "idle",
          task: null,
          error: null,
        };
      }
    }
    this.state.taskDetails = resetDetails;
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
    this.handleSocketProtocolErrorForCurrentSocket(error);
  }

  private handleSocketProtocolErrorForCurrentSocket(error: unknown): void {
    const socket = this.socket;
    if (socket === null) {
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
        false,
        true,
      );
      this.requestListRefresh();
      return;
    }

    if (!eventKeepsTaskInQuery(current, event, this.query)) {
      this.requestListRefresh();
    }
    if (isTerminalStatus(event.status)) {
      this.requestTaskDetail(event.task_id, true, false, true);
      this.requestListRefresh();
    }
  }

  private requestTaskDetail(
    taskId: number,
    terminalRefresh: boolean,
    explicitRequested: boolean,
    listRefreshRequested: boolean,
  ): void {
    const pending = this.detailRequests.get(taskId);
    if (pending !== undefined) {
      pending.explicitRequested ||= explicitRequested;
      pending.listRefreshRequested ||= listRefreshRequested;
      if (terminalRefresh) {
        pending.terminalRefreshRequested = true;
      }
      return;
    }
    if (!terminalRefresh && !explicitRequested && this.detailLoaded.has(taskId)) {
      return;
    }

    const request: DetailRequest = {
      epoch: this.socketEpoch,
      explicitRequested,
      listRefreshRequested,
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
        if (this.cancelConfirmations.delete(taskId)) {
          this.cancelRequests.delete(taskId);
          const cancelStates = { ...this.state.cancelStates };
          delete cancelStates[taskId];
          this.state.cancelStates = cancelStates;
        } else if (this.cancelReconciliations.delete(taskId)) {
          this.cancelRequests.delete(taskId);
          const cancelState = this.state.cancelStates[taskId];
          if (cancelState !== undefined) {
            this.state.cancelStates = {
              ...this.state.cancelStates,
              [taskId]: { ...cancelState, authorityPending: false },
            };
          }
        }
        const event = this.latestEvents.get(taskId);
        const merged = mergeTaskWithEvent(task, event);
        this.state.taskDetails = {
          ...this.state.taskDetails,
          [taskId]: { phase: "ready", task: merged, error: null },
        };
        const index = this.state.tasks.findIndex(
          (candidate) => candidate.id === taskId,
        );
        if (index !== -1) {
          const next = [...this.state.tasks];
          next[index] = merged;
          this.state.tasks = limitTasks(next, this.query);
        }
        this.emit();
        if (request.listRefreshRequested) {
          this.requestListRefresh();
        }
      },
      (error: unknown) => {
        if (!this.isCurrentDetailRequest(taskId, request)) {
          return;
        }
        const protocol = error instanceof ApiProtocolError;
        this.state.detailError = { taskId, error, protocol };
        this.state.taskDetails = {
          ...this.state.taskDetails,
          [taskId]: { phase: "error", task: null, error },
        };
        if (this.cancelConfirmations.delete(taskId)) {
          this.cancelRequests.delete(taskId);
          this.state.cancelStates = {
            ...this.state.cancelStates,
            [taskId]: {
              phase: "error",
              error,
              authorityPending: false,
            },
          };
        }
        this.emit();
        if (protocol) {
          this.handleSocketProtocolErrorForCurrentSocket(error);
        }
        if (request.listRefreshRequested) {
          this.requestListRefresh();
        }
      },
    )
      .finally(() => {
        if (!this.isCurrentDetailRequest(taskId, request)) {
          return;
        }
        this.detailRequests.delete(taskId);
        if (request.terminalRefreshRequested && !this.disposed) {
          this.requestTaskDetail(
            taskId,
            true,
            request.explicitRequested,
            request.listRefreshRequested,
          );
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
      query: { ...this.query },
      initial,
      invalidated: false,
    };
    this.listRequest = request;
    this.state.listPhase =
      initial && this.state.tasks.length === 0 ? "loading" : "updating";
    this.emit();

    void Promise.resolve()
      .then(() => this.readTasks(request.query))
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
        this.state.tasks = limitTasks(tasks, request.query);
        this.state.listError = null;
        this.state.socketError = null;
        if (this.state.detailError?.protocol) {
          this.state.detailError = null;
          const taskDetails = { ...this.state.taskDetails };
          for (const [taskId, detail] of Object.entries(taskDetails)) {
            if (detail.error instanceof ApiProtocolError) {
              taskDetails[Number(taskId)] = {
                phase: "idle",
                task: null,
                error: null,
              };
            }
          }
          this.state.taskDetails = taskDetails;
        }
        this.state.listPhase = "ready";
        this.state.connectionState = "connected";
        this.synchronized = true;
        this.synchronizationFailed = false;
        this.reconnectAttempt = 0;
        this.listRequest = null;
        const cancelStates = { ...this.state.cancelStates };
        const taskDetails = { ...this.state.taskDetails };
        for (const [taskId] of this.cancelReconciliations) {
          const cancelState = cancelStates[taskId];
          if (cancelState === undefined) {
            this.cancelRequests.delete(taskId);
            this.cancelReconciliations.delete(taskId);
            continue;
          }
          if (!tasks.some((task) => task.id === taskId)) {
            delete taskDetails[taskId];
            if (this.state.detailError?.taskId === taskId) {
              this.state.detailError = null;
            }
          }
          cancelStates[taskId] = {
            ...cancelState,
            authorityPending: false,
          };
          this.cancelRequests.delete(taskId);
          this.cancelReconciliations.delete(taskId);
        }
        this.state.cancelStates = cancelStates;
        this.state.taskDetails = taskDetails;
        const bufferedEvents = this.bufferedEvents.splice(0);
        this.emit();
        for (const taskId of this.cancelConfirmations) {
          if (!this.detailRequests.has(taskId)) {
            this.requestTaskDetail(taskId, false, true, true);
          }
        }
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
        if (request.initial || error instanceof ApiProtocolError) {
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
    if (this.socket !== null && !this.disposed) {
      this.startListRequest(this.socket, !this.synchronized);
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

  private isCurrentCancelRequest(
    taskId: number,
    request: object,
  ): boolean {
    return !this.disposed && this.cancelRequests.get(taskId) === request;
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
