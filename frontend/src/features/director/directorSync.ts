import type { Asset } from "../../api/assets";
import { generateClipVideo } from "../../api/clips";
import type {
  Clip,
  ClipSlotsResponse,
  ClipVideo,
  GenerateClipVideoRequest,
  GenerateClipVideoResponse,
} from "../../api/clips";
import { getTask } from "../../api/tasks";
import type { Task, TaskEvent } from "../../api/tasks";
import { openTaskWebSocket, parseTaskEvent } from "../../api/ws";
import type { Shot } from "../../api/shots";

export interface DirectorPageSnapshot {
  assets: Asset[];
  shots: Shot[];
  clips: Clip[];
}

export interface DirectorClipDetailSnapshot {
  clip: Clip;
  slots: ClipSlotsResponse;
  videos: ClipVideo[];
}

export interface DirectorClipDraft {
  baseUserNote: string | null;
  baseRequestedDuration: number;
  userNote: string | null;
  requestedDuration: string;
  dirtyUserNote: boolean;
  dirtyRequestedDuration: boolean;
}

export interface DirectorTaskSocket {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  close(): void;
}

export interface DirectorSyncNotice {
  kind: "mutation-success" | "task-terminal";
  message: string;
  taskId?: number;
}

export type DirectorPagePhase = "connecting" | "snapshot-loading" | "ready" | "error";
export type DirectorDetailPhase = "idle" | "loading" | "ready" | "error";

export interface DirectorSyncState {
  pagePhase: DirectorPagePhase;
  pageSnapshot: DirectorPageSnapshot | null;
  selectedClipId: number | null;
  detailPhase: DirectorDetailPhase;
  clipDetail: DirectorClipDetailSnapshot | null;
  clipDraft: DirectorClipDraft | null;
  pageError: unknown | null;
  detailError: unknown | null;
  taskError: unknown | null;
  taskDetails: Task[];
  taskEvents: TaskEvent[];
  socketError: unknown | null;
  error: unknown | null;
  notices: DirectorSyncNotice[];
}

export interface DirectorSyncOptions {
  readPageSnapshot: () => Promise<DirectorPageSnapshot>;
  readClipDetail?: (clipId: number) => Promise<DirectorClipDetailSnapshot>;
  readTask?: (taskId: number) => Promise<Task>;
  openSocket?: () => DirectorTaskSocket;
}

export interface DirectorRefreshOptions {
  notice?: DirectorSyncNotice;
  refreshSelectedClip?: boolean;
  resetSelectedClipDraft?: boolean;
}

export interface DirectorSyncController {
  start(): void;
  dispose(): void;
  subscribe(listener: (state: DirectorSyncState) => void): () => void;
  getState(): DirectorSyncState;
  selectClip(clipId: number | null): void;
  trackTask(taskId: number): void;
  updateClipDraft(patch: {
    userNote?: string | null;
    requestedDuration?: string;
  }): void;
  refreshPage(options?: DirectorRefreshOptions): void;
  refreshSelectedClip(options?: { resetDraft?: boolean }): void;
}

export interface DirectorGenerationRequester {
  isInFlight(): boolean;
  submit(
    clipId: number,
    input: GenerateClipVideoRequest,
  ): Promise<GenerateClipVideoResponse> | null;
}

const RECONNECT_DELAYS_MS = [1000, 2000, 5000] as const;

interface PageRequest {
  generation: number;
  socketEpoch: number;
  initial: boolean;
  startEventSequence: number;
  invalidated: boolean;
}

interface TaskEventRecord {
  sequence: number;
  event: TaskEvent;
  detail: Promise<Task>;
  consumed: boolean;
}

interface PendingTaskNotice {
  taskId: number;
  targetClipId: number;
  message: string;
  requiresDetail: boolean;
  baselineVideoIds: Set<number>;
  pageApplied: boolean;
  detailApplied: boolean;
}

function isTerminalTask(task: Task): boolean {
  return (
    task.status === "done" ||
    task.status === "failed" ||
    task.status === "canceled"
  );
}

function defaultSocket(): DirectorTaskSocket {
  return openTaskWebSocket();
}

export function createDirectorGenerationRequester(
  request: (
    clipId: number,
    input: GenerateClipVideoRequest,
  ) => Promise<GenerateClipVideoResponse> = generateClipVideo,
): DirectorGenerationRequester {
  let inFlight = false;

  return {
    isInFlight(): boolean {
      return inFlight;
    },
    submit(
      clipId: number,
      input: GenerateClipVideoRequest,
    ): Promise<GenerateClipVideoResponse> | null {
      if (inFlight) {
        return null;
      }
      inFlight = true;
      let pending: Promise<GenerateClipVideoResponse>;
      try {
        pending = request(clipId, input);
      } catch (error: unknown) {
        inFlight = false;
        throw error;
      }
      return pending.finally(() => {
        inFlight = false;
      });
    },
  };
}

function errorForFailedTask(task: Task): Error {
  return new Error(
    task.error_msg === null
      ? `Task #${task.id} failed without error_msg`
      : task.error_msg,
  );
}

function initializeDraft(clip: Clip): DirectorClipDraft {
  return {
    baseUserNote: clip.user_note,
    baseRequestedDuration: clip.requested_duration,
    userNote: clip.user_note,
    requestedDuration: String(clip.requested_duration),
    dirtyUserNote: false,
    dirtyRequestedDuration: false,
  };
}

class DirectorSync implements DirectorSyncController {
  private readonly readPageSnapshot: () => Promise<DirectorPageSnapshot>;
  private readonly readClipDetail?: (
    clipId: number,
  ) => Promise<DirectorClipDetailSnapshot>;
  private readonly readTask: (taskId: number) => Promise<Task>;
  private readonly openSocket: () => DirectorTaskSocket;
  private readonly listeners = new Set<
    (state: DirectorSyncState) => void
  >();
  private readonly taskDetails = new Map<number, Task>();
  private readonly taskDetailRequests = new Map<number, Promise<Task>>();
  private readonly trackedTaskIds = new Set<number>();
  private readonly taskEvents = new Map<number, TaskEvent>();
  private readonly eventRecords: TaskEventRecord[] = [];
  private readonly pendingNotices: DirectorSyncNotice[] = [];
  private readonly pendingTaskNotices: PendingTaskNotice[] = [];
  private readonly resetDraftOnNextDetail = new Set<number>();

  private state: DirectorSyncState = {
    pagePhase: "connecting",
    pageSnapshot: null,
    selectedClipId: null,
    detailPhase: "idle",
    clipDetail: null,
    clipDraft: null,
    pageError: null,
    detailError: null,
    taskError: null,
    taskDetails: [],
    taskEvents: [],
    socketError: null,
    error: null,
    notices: [],
  };
  private started = false;
  private disposed = false;
  private socket: DirectorTaskSocket | null = null;
  private socketEpoch = 0;
  private synchronized = false;
  private synchronizationFailed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private pageGeneration = 0;
  private pageRequest: PageRequest | null = null;
  private detailGeneration = 0;
  private eventSequence = 0;
  private eventWork: Promise<void> = Promise.resolve();

  constructor(options: DirectorSyncOptions) {
    this.readPageSnapshot = options.readPageSnapshot;
    this.readClipDetail = options.readClipDetail;
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
    const socket = this.socket;
    this.socket = null;
    this.invalidatePageRequest();
    if (socket !== null) {
      socket.close();
    }
    this.listeners.clear();
  }

  subscribe(listener: (state: DirectorSyncState) => void): () => void {
    this.listeners.add(listener);
    listener(this.getState());
    return () => {
      this.listeners.delete(listener);
    };
  }

  getState(): DirectorSyncState {
    return {
      ...this.state,
      taskDetails: [...this.taskDetails.values()].filter((task) =>
        this.trackedTaskIds.has(task.id),
      ),
      taskEvents: [...this.taskEvents.values()].filter((event) =>
        this.trackedTaskIds.has(event.task_id),
      ),
      notices: [...this.state.notices],
    };
  }

  selectClip(clipId: number | null): void {
    if (clipId === this.state.selectedClipId) {
      return;
    }

    this.resetDraftOnNextDetail.clear();
    this.detailGeneration += 1;
    this.state.selectedClipId = clipId;
    this.state.clipDetail = null;
    this.state.clipDraft = null;
    this.state.detailError = null;
    this.state.detailPhase =
      clipId === null || this.readClipDetail === undefined ? "idle" : "loading";
    this.emit();

    if (clipId !== null && this.readClipDetail !== undefined) {
      this.startDetailRequest(clipId, this.detailGeneration);
    }
  }

  trackTask(taskId: number): void {
    if (this.trackedTaskIds.has(taskId)) {
      return;
    }
    this.trackedTaskIds.add(taskId);
    for (const record of this.eventRecords) {
      if (record.event.task_id === taskId) {
        this.taskEvents.set(taskId, record.event);
      }
    }
    this.emit();
  }

  updateClipDraft(patch: {
    userNote?: string | null;
    requestedDuration?: string;
  }): void {
    const current = this.state.clipDraft;
    if (current === null) {
      throw new Error("Cannot edit a Clip draft before its detail is loaded");
    }

    const nextUserNote =
      Object.prototype.hasOwnProperty.call(patch, "userNote")
        ? patch.userNote!
        : current.userNote;
    const nextRequestedDuration =
      Object.prototype.hasOwnProperty.call(patch, "requestedDuration")
        ? patch.requestedDuration!
        : current.requestedDuration;
    this.state.clipDraft = {
      ...current,
      userNote: nextUserNote,
      requestedDuration: nextRequestedDuration,
      dirtyUserNote: nextUserNote !== current.baseUserNote,
      dirtyRequestedDuration:
        nextRequestedDuration !== String(current.baseRequestedDuration),
    };
    this.emit();
  }

  refreshPage(options: DirectorRefreshOptions = {}): void {
    if (options.notice !== undefined) {
      this.pendingNotices.push(options.notice);
    }
    if (options.refreshSelectedClip) {
      this.refreshSelectedClip({
        resetDraft: options.resetSelectedClipDraft === true,
      });
    }

    if (this.pageRequest !== null) {
      this.invalidatePageRequest();
      return;
    }
    if (
      this.socket !== null &&
      !this.synchronizationFailed &&
      !this.disposed
    ) {
      this.startPageRequest(this.socket, false);
    }
  }

  refreshSelectedClip(options: { resetDraft?: boolean } = {}): void {
    if (
      this.state.selectedClipId === null ||
      this.readClipDetail === undefined
    ) {
      return;
    }
    if (options.resetDraft === true) {
      this.resetDraftOnNextDetail.add(this.state.selectedClipId);
    }
    this.detailGeneration += 1;
    this.state.detailPhase = "loading";
    this.state.detailError = null;
    this.emit();
    this.startDetailRequest(
      this.state.selectedClipId,
      this.detailGeneration,
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
    this.invalidatePageRequest();
    this.state.pagePhase = "connecting";
    this.state.socketError = null;
    this.emit();

    socket.onopen = () => {
      if (!this.isActiveSocket(socket)) {
        return;
      }
      this.synchronized = false;
      this.synchronizationFailed = false;
      this.state.pagePhase = "snapshot-loading";
      this.startPageRequest(socket, true);
    };
    socket.onmessage = (message) => {
      this.handleMessage(socket, message);
    };
    socket.onerror = () => {
      if (!this.isActiveSocket(socket)) {
        return;
      }
      const error = new Error("Task WebSocket connection failed");
      this.state.socketError = error;
      this.state.error = error;
      this.emit();
      socket.close();
    };
    socket.onclose = () => {
      if (!this.isActiveSocket(socket)) {
        return;
      }
      this.socket = null;
      this.synchronized = false;
      this.invalidatePageRequest();
      this.scheduleReconnect();
    };
  }

  private handleMessage(
    socket: DirectorTaskSocket,
    message: MessageEvent,
  ): void {
    if (!this.isActiveSocket(socket) || this.synchronizationFailed) {
      return;
    }
    if (typeof message.data !== "string") {
      this.handleSocketProtocolError(socket, new TypeError("Task WebSocket messages must be text"));
      return;
    }

    let event: TaskEvent;
    try {
      event = parseTaskEvent(message.data);
    } catch (error: unknown) {
      if (error instanceof SyntaxError) {
        this.handleSocketProtocolError(socket, error);
        return;
      }
      throw error;
    }
    if (event.type !== "gen_clip_video") {
      return;
    }
    if (this.trackedTaskIds.has(event.task_id)) {
      this.taskEvents.set(event.task_id, event);
      this.emit();
    }

    const record: TaskEventRecord = {
      sequence: ++this.eventSequence,
      event,
      detail: this.getTaskOnce(event.task_id),
      consumed: false,
    };
    this.eventRecords.push(record);
    if (!this.synchronized) {
      return;
    }
    this.enqueueEvent(record);
  }

  private handleSocketProtocolError(
    socket: DirectorTaskSocket,
    error: unknown,
  ): void {
    if (!this.isActiveSocket(socket)) {
      return;
    }
    this.synchronizationFailed = true;
    this.synchronized = false;
    this.state.socketError = error;
    this.state.error = error;
    this.state.pagePhase = "error";
    this.invalidatePageRequest();
    this.emit();
    socket.close();
    this.scheduleReconnect();
  }

  private enqueueEvent(record: TaskEventRecord): void {
    this.eventWork = this.eventWork
      .then(async () => {
        if (record.consumed || this.disposed) {
          return;
        }
        const task = await record.detail;
        if (record.consumed || this.disposed) {
          return;
        }
        if (this.pageRequest !== null) {
          return;
        }
        if (this.isRelevantTask(task, this.state.pageSnapshot)) {
          this.consumeRelevantEvent(record, task);
        } else {
          record.consumed = true;
        }
      })
      .then(
        () => undefined,
        (error: unknown) => {
          if (!this.disposed) {
            this.state.taskError = error;
            this.state.error = error;
            this.emit();
          }
        },
      );
  }

  private getTaskOnce(taskId: number): Promise<Task> {
    const cached = this.taskDetails.get(taskId);
    if (cached !== undefined && isTerminalTask(cached)) {
      return Promise.resolve(cached);
    }
    const pending = this.taskDetailRequests.get(taskId);
    if (pending !== undefined) {
      return pending;
    }

    const request = this.readTask(taskId).then(
      (task) => {
        this.taskDetailRequests.delete(taskId);
        this.taskDetails.set(taskId, task);
        return task;
      },
      (error: unknown) => {
        this.taskDetailRequests.delete(taskId);
        throw error;
      },
    );
    this.taskDetailRequests.set(taskId, request);
    return request;
  }

  private startPageRequest(
    socket: DirectorTaskSocket,
    initial: boolean,
  ): void {
    if (!this.isActiveSocket(socket) || this.disposed) {
      return;
    }

    const request: PageRequest = {
      generation: ++this.pageGeneration,
      socketEpoch: this.socketEpoch,
      initial,
      startEventSequence: this.eventSequence,
      invalidated: false,
    };
    this.pageRequest = request;
    this.state.pagePhase = "snapshot-loading";
    const previousPageError = this.state.pageError;
    this.state.pageError = null;
    if (this.state.error === previousPageError) {
      this.state.error = null;
    }
    this.emit();

    void Promise.resolve()
      .then(() => this.readPageSnapshot())
      .then((snapshot) => this.applyPageSnapshot(request, snapshot))
      .then(
        () => {
          this.finishPageRequest(request);
        },
        (error: unknown) => {
          this.failPageRequest(request, error);
          this.finishPageRequest(request);
        },
      );
  }

  private async applyPageSnapshot(
    request: PageRequest,
    snapshot: DirectorPageSnapshot,
  ): Promise<void> {
    if (!this.isCurrentPageRequest(request)) {
      return;
    }

    await this.waitForEventsAfter(request.startEventSequence);
    if (!this.isCurrentPageRequest(request)) {
      return;
    }

    const records = this.eventRecords.filter(
      (record) =>
        record.sequence > request.startEventSequence && !record.consumed,
    );
    for (const record of records) {
      const task = await record.detail;
      if (!this.isCurrentPageRequest(request)) {
        return;
      }
      if (this.isRelevantTask(task, snapshot)) {
        this.consumeRelevantEvent(record, task);
      } else {
        record.consumed = true;
      }
    }

    if (!this.isCurrentPageRequest(request)) {
      return;
    }

    const previousPageError = this.state.pageError;
    const previousSocketError = this.state.socketError;
    this.state.pageSnapshot = snapshot;
    this.state.pageError = null;
    this.state.socketError = null;
    if (
      this.state.error === previousPageError ||
      this.state.error === previousSocketError
    ) {
      this.state.error = this.state.taskError ?? this.state.detailError;
    }
    this.state.pagePhase = "ready";
    this.synchronized = true;
    this.reconnectAttempt = 0;

    this.markTaskNoticesPageApplied(snapshot);

    if (
      this.state.selectedClipId !== null &&
      !snapshot.clips.some((clip) => clip.id === this.state.selectedClipId)
    ) {
      this.clearSelectedClip();
    }

    if (this.pendingNotices.length > 0) {
      this.state.notices = [
        ...this.state.notices,
        ...this.pendingNotices.splice(0),
      ];
    }
    this.publishReadyTaskNotices();
    this.emit();
  }

  private async waitForEventsAfter(sequence: number): Promise<void> {
    while (true) {
      const observedSequence = this.eventSequence;
      const records = this.eventRecords.filter(
        (record) => record.sequence > sequence && !record.consumed,
      );
      if (records.length > 0) {
        await Promise.all(records.map((record) => record.detail));
      }
      if (observedSequence === this.eventSequence) {
        return;
      }
    }
  }

  private failPageRequest(request: PageRequest, error: unknown): void {
    if (!this.isCurrentPageRequest(request)) {
      return;
    }

    this.state.pageError = error;
    this.state.error = error;
    this.state.pagePhase = "error";
    if (request.initial) {
      this.synchronizationFailed = true;
      this.synchronized = false;
      const socket = this.socket;
      if (socket !== null) {
        socket.close();
      }
      this.scheduleReconnect();
    }
    this.emit();
  }

  private finishPageRequest(request: PageRequest): void {
    if (this.pageRequest !== request) {
      return;
    }
    this.pageRequest = null;
    if (
      request.invalidated &&
      this.socket !== null &&
      !this.synchronizationFailed &&
      !this.disposed
    ) {
      this.startPageRequest(this.socket, false);
    }
  }

  private invalidatePageRequest(): void {
    if (this.pageRequest !== null) {
      if (!this.pageRequest.invalidated) {
        this.pageRequest.invalidated = true;
        this.pageGeneration += 1;
      }
      return;
    }
    if (
      this.socket !== null &&
      this.synchronized &&
      !this.synchronizationFailed &&
      !this.disposed
    ) {
      this.startPageRequest(this.socket, false);
    }
  }

  private consumeRelevantEvent(record: TaskEventRecord, task: Task): void {
    record.consumed = true;
    if (task.status === "failed") {
      this.state.taskError = errorForFailedTask(task);
      this.state.error = this.state.taskError;
    } else if (isTerminalTask(task)) {
      this.state.taskError = null;
    }
    if (task.status === "done") {
      const selectedDetail =
        this.state.selectedClipId === task.target_id
          ? this.state.clipDetail
          : null;
      const requiresDetail = selectedDetail !== null;
      this.pendingTaskNotices.push({
        taskId: task.id,
        targetClipId: task.target_id,
        message:
          record.event.message.length > 0
            ? record.event.message
            : `Task #${task.id} 已完成`,
        requiresDetail,
        baselineVideoIds: new Set(
          selectedDetail?.videos.map((video) => video.id) ?? [],
        ),
        pageApplied: false,
        detailApplied: !requiresDetail,
      });
    }
    this.invalidatePageRequest();
    if (this.state.selectedClipId === task.target_id) {
      this.refreshSelectedClip();
    }
    this.publishReadyTaskNotices();
    this.emit();
  }

  private markTaskNoticesPageApplied(snapshot: DirectorPageSnapshot): void {
    for (const notice of this.pendingTaskNotices) {
      if (notice.pageApplied) {
        continue;
      }
      const clip = snapshot.clips.find(
        (candidate) => candidate.id === notice.targetClipId,
      );
      if (clip !== undefined && clip.generation_state === "ready") {
        notice.pageApplied = true;
      }
    }
  }

  private markTaskNoticesDetailApplied(
    detail: DirectorClipDetailSnapshot,
  ): void {
    for (const notice of this.pendingTaskNotices) {
      if (
        !notice.requiresDetail ||
        notice.detailApplied ||
        notice.targetClipId !== detail.clip.id
      ) {
        continue;
      }
      const hasNewTake = detail.videos.some(
        (video) => !notice.baselineVideoIds.has(video.id),
      );
      if (detail.clip.generation_state === "ready" && hasNewTake) {
        notice.detailApplied = true;
      }
    }
  }

  private publishReadyTaskNotices(): void {
    const ready = this.pendingTaskNotices.filter(
      (notice) => notice.pageApplied && notice.detailApplied,
    );
    if (ready.length === 0) {
      return;
    }
    this.state.notices = [
      ...this.state.notices,
      ...ready.map((notice) => ({
        kind: "task-terminal" as const,
        taskId: notice.taskId,
        message: notice.message,
      })),
    ];
    for (const notice of ready) {
      const index = this.pendingTaskNotices.indexOf(notice);
      this.pendingTaskNotices.splice(index, 1);
    }
  }

  private isRelevantTask(
    task: Task,
    snapshot: DirectorPageSnapshot | null,
  ): boolean {
    return (
      task.type === "gen_clip_video" &&
      snapshot !== null &&
      snapshot.clips.some((clip) => clip.id === task.target_id)
    );
  }

  private startDetailRequest(clipId: number, generation: number): void {
    if (this.readClipDetail === undefined || this.disposed) {
      return;
    }
    void Promise.resolve()
      .then(() => this.readClipDetail!(clipId))
      .then(
        (detail) => {
          if (
            this.disposed ||
            this.state.selectedClipId !== clipId ||
            this.detailGeneration !== generation
          ) {
            return;
          }
          if (detail.clip.id !== clipId) {
            const error = new Error(
              `Clip detail response targeted Clip ${detail.clip.id}, expected ${clipId}`,
            );
            this.state.detailError = error;
            this.state.error = error;
            this.state.detailPhase = "error";
            this.emit();
            return;
          }
          this.state.clipDetail = detail;
          if (this.resetDraftOnNextDetail.has(clipId)) {
            this.state.clipDraft = initializeDraft(detail.clip);
            this.resetDraftOnNextDetail.delete(clipId);
          } else {
            this.state.clipDraft = this.mergeDraft(
              this.state.clipDraft,
              detail.clip,
            );
          }
          const previousDetailError = this.state.detailError;
          this.state.detailError = null;
          if (this.state.error === previousDetailError) {
            this.state.error = this.state.taskError ?? this.state.pageError;
          }
          this.state.detailPhase = "ready";
          this.markTaskNoticesDetailApplied(detail);
          this.publishReadyTaskNotices();
          this.emit();
        },
        (error: unknown) => {
          if (
            this.disposed ||
            this.state.selectedClipId !== clipId ||
            this.detailGeneration !== generation
          ) {
            return;
          }
          this.state.detailError = error;
          this.state.error = error;
          this.state.detailPhase = "error";
          this.emit();
        },
      );
  }

  private mergeDraft(
    current: DirectorClipDraft | null,
    clip: Clip,
  ): DirectorClipDraft {
    if (current === null) {
      return initializeDraft(clip);
    }
    const userNote = current.dirtyUserNote ? current.userNote : clip.user_note;
    const requestedDuration = current.dirtyRequestedDuration
      ? current.requestedDuration
      : String(clip.requested_duration);
    return {
      baseUserNote: clip.user_note,
      baseRequestedDuration: clip.requested_duration,
      userNote,
      requestedDuration,
      dirtyUserNote: userNote !== clip.user_note,
      dirtyRequestedDuration:
        requestedDuration !== String(clip.requested_duration),
    };
  }

  private clearSelectedClip(): void {
    this.detailGeneration += 1;
    this.resetDraftOnNextDetail.clear();
    this.state.selectedClipId = null;
    this.state.clipDetail = null;
    this.state.clipDraft = null;
    this.state.detailPhase = "idle";
    this.state.detailError = null;
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectTimer !== null) {
      return;
    }
    const delay =
      this.reconnectAttempt < RECONNECT_DELAYS_MS.length
        ? RECONNECT_DELAYS_MS[this.reconnectAttempt]
        : 10000;
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private isActiveSocket(socket: DirectorTaskSocket): boolean {
    return !this.disposed && this.socket === socket;
  }

  private isCurrentPageRequest(request: PageRequest): boolean {
    return (
      !this.disposed &&
      this.pageRequest === request &&
      !request.invalidated &&
      request.generation === this.pageGeneration &&
      request.socketEpoch === this.socketEpoch &&
      this.socket !== null
    );
  }

  private emit(): void {
    const snapshot = this.getState();
    for (const listener of this.listeners) {
      listener(snapshot);
    }
  }
}

export function createDirectorSync(
  options: DirectorSyncOptions,
): DirectorSyncController {
  return new DirectorSync(options);
}
