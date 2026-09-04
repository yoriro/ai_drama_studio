import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Clip } from "../../api/clips";
import type { Task, TaskEvent } from "../../api/tasks";
import {
  createDirectorSync,
  projectDirectorVisibleSyncErrors,
  type DirectorPageSnapshot,
  type DirectorSyncController,
  type DirectorTaskSocket,
} from "./directorSync";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function flushPromises(): Promise<void> {
  for (let index = 0; index < 16; index += 1) {
    await Promise.resolve();
  }
}

class FakeSocket implements DirectorTaskSocket {
  onopen: DirectorTaskSocket["onopen"] = null;
  onmessage: DirectorTaskSocket["onmessage"] = null;
  onerror: DirectorTaskSocket["onerror"] = null;
  onclose: DirectorTaskSocket["onclose"] = null;
  closed = false;

  open(): void {
    this.onopen?.({} as Event);
  }

  message(event: TaskEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.onclose?.({} as CloseEvent);
  }
}

function makeClip(id = 7, revision = 1): Clip {
  return {
    id,
    episode_id: 1,
    generation_mode: "ref2v",
    user_note: null,
    requested_duration: 5,
    generation_state: "ready",
    freshness: "fresh",
    revision,
    shot_ids: [1],
    start_order_index: 1,
    end_order_index: 1,
    enabled_slot_count: 1,
    warnings: [],
    created_at: "2026-09-04T00:00:00Z",
    updated_at: "2026-09-04T00:00:00Z",
  };
}

function makeSnapshot(revision = 1): DirectorPageSnapshot {
  return { assets: [], shots: [], clips: [makeClip(7, revision)] };
}

function makeTask(
  id: number,
  overrides: Partial<Task> = {},
): Task {
  return {
    id,
    type: "gen_clip_video",
    target_id: 7,
    request_id: null,
    status: "done",
    progress: 1,
    error_msg: null,
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: "2026-09-04T00:00:00Z",
    started_at: "2026-09-04T00:00:01Z",
    finished_at: "2026-09-04T00:00:02Z",
    ...overrides,
  };
}

function makeEvent(
  taskId: number,
  status: TaskEvent["status"],
): TaskEvent {
  return {
    task_id: taskId,
    type: "gen_clip_video",
    status,
    progress: status === "done" ? 1 : 0.5,
    message: status === "failed" ? "任务失败" : "任务已完成",
  };
}

function createHarness(options: {
  readPageSnapshot: () => Promise<DirectorPageSnapshot>;
  readTask: (taskId: number) => Promise<Task>;
}) {
  const sockets: FakeSocket[] = [];
  const controller = createDirectorSync({
    ...options,
    openSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  const states = [] as ReturnType<DirectorSyncController["getState"]>[];
  const unsubscribe = controller.subscribe((state) => {
    states.push(state);
  });
  return { controller, sockets, states, unsubscribe };
}

function visibleMessages(
  state: ReturnType<DirectorSyncController["getState"]>,
): Array<{ kind: string; message: string }> {
  return projectDirectorVisibleSyncErrors(state).map(({ kind, error }) => ({
    kind,
    message: error instanceof Error ? error.message : String(error),
  }));
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Director ready error visibility", () => {
  it("projects a Task detail transport failure while retaining the ready page", async () => {
    const taskDetail = deferred<Task>();
    const readTask = vi.fn(() => taskDetail.promise);
    const harness = createHarness({
      readPageSnapshot: () => Promise.resolve(makeSnapshot()),
      readTask,
    });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    expect(harness.controller.getState().pagePhase).toBe("ready");

    harness.controller.trackTask(41);
    harness.sockets[0].message(makeEvent(41, "done"));
    await flushPromises();
    expect(readTask).toHaveBeenCalledTimes(1);

    taskDetail.reject(new Error("Task detail transport failed"));
    await flushPromises();

    const state = harness.controller.getState();
    expect(state.pagePhase).toBe("ready");
    expect(state.pageSnapshot?.clips.map((clip) => clip.id)).toEqual([7]);
    expect(state.notices).toEqual([]);
    expect(visibleMessages(state)).toEqual([
      { kind: "task", message: "Task detail transport failed" },
    ]);

    harness.unsubscribe();
    harness.controller.dispose();
  });

  it("keeps a socket error visible until a recovered page snapshot succeeds", async () => {
    vi.useFakeTimers();
    const recoveredSnapshot = deferred<DirectorPageSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockResolvedValueOnce(makeSnapshot(1))
      .mockReturnValueOnce(recoveredSnapshot.promise);
    const harness = createHarness({
      readPageSnapshot,
      readTask: vi.fn(),
    });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    expect(harness.controller.getState().pagePhase).toBe("ready");

    harness.sockets[0].onerror?.({} as Event);
    const failedState = harness.controller.getState();
    expect(failedState.pagePhase).toBe("ready");
    expect(failedState.pageSnapshot?.clips.map((clip) => clip.id)).toEqual([7]);
    expect(visibleMessages(failedState)).toEqual([
      { kind: "socket", message: "Task WebSocket connection failed" },
    ]);

    await vi.advanceTimersByTimeAsync(1000);
    expect(harness.sockets).toHaveLength(2);
    harness.sockets[1].open();
    await flushPromises();
    expect(harness.controller.getState().pagePhase).toBe("snapshot-loading");
    expect(visibleMessages(harness.controller.getState())).toEqual([
      { kind: "socket", message: "Task WebSocket connection failed" },
    ]);

    recoveredSnapshot.resolve(makeSnapshot(2));
    await flushPromises();
    const recoveredState = harness.controller.getState();
    expect(recoveredState.pagePhase).toBe("ready");
    expect(recoveredState.pageSnapshot?.clips[0]?.revision).toBe(2);
    expect(recoveredState.socketError).toBeNull();
    expect(visibleMessages(recoveredState)).toEqual([]);

    harness.unsubscribe();
    harness.controller.dispose();
  });

  it("keeps the complete server error_msg visible for a legitimate failed Task", async () => {
    const failedTask = makeTask(42, {
      status: "failed",
      error_msg: "R10：参考槽位缺少可用图片，任务已终止",
    });
    const harness = createHarness({
      readPageSnapshot: () => Promise.resolve(makeSnapshot()),
      readTask: vi.fn(() => Promise.resolve(failedTask)),
    });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    harness.controller.trackTask(42);
    harness.sockets[0].message(makeEvent(42, "failed"));
    await flushPromises();

    const state = harness.controller.getState();
    expect(state.pagePhase).toBe("ready");
    expect(state.taskDetails).toEqual([failedTask]);
    expect(state.taskError).toMatchObject({ message: failedTask.error_msg });
    expect(visibleMessages(state)).toEqual([
      { kind: "task", message: failedTask.error_msg! },
    ]);
    expect(state.notices).toEqual([]);

    harness.unsubscribe();
    harness.controller.dispose();
  });
});
