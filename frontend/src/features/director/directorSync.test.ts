import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Clip,
  ClipSlotsResponse,
  ClipVideo,
} from "../../api/clips";
import type { Task, TaskEvent } from "../../api/tasks";
import {
  createDirectorSync,
  type DirectorClipDetailSnapshot,
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
  for (let index = 0; index < 8; index += 1) {
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

  message(data: unknown): void {
    this.onmessage?.({ data } as MessageEvent);
  }

  close(): void {
    this.closed = true;
    this.onclose?.({} as CloseEvent);
  }
}

function makeClip(
  id: number,
  overrides: Partial<Clip> = {},
): Clip {
  return {
    id,
    episode_id: 1,
    generation_mode: "ref2v",
    user_note: null,
    requested_duration: 5,
    generation_state: "ready",
    freshness: "fresh",
    revision: 1,
    shot_ids: [1],
    start_order_index: 1,
    end_order_index: 1,
    enabled_slot_count: 1,
    warnings: [],
    created_at: "2026-09-03T00:00:00Z",
    updated_at: "2026-09-03T00:00:00Z",
    ...overrides,
  };
}

function makeSnapshot(
  revision: number,
  clips: Clip[] = [makeClip(7)],
): DirectorPageSnapshot {
  return {
    assets: [],
    shots: [],
    clips: clips.map((clip) => ({ ...clip, revision })),
  };
}

function makeTask(
  id: number,
  targetId: number,
  overrides: Partial<Task> = {},
): Task {
  return {
    id,
    type: "gen_clip_video",
    target_id: targetId,
    request_id: null,
    status: "done",
    progress: 1,
    error_msg: null,
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: "2026-09-03T00:00:00Z",
    started_at: "2026-09-03T00:00:01Z",
    finished_at: "2026-09-03T00:00:02Z",
    ...overrides,
  };
}

function makeEvent(
  taskId: number,
  status: TaskEvent["status"] = "done",
): TaskEvent {
  return {
    task_id: taskId,
    type: "gen_clip_video",
    status,
    progress: status === "done" ? 1 : 0.5,
    message: "最新任务已完成",
  };
}

function makeDetail(clip: Clip): DirectorClipDetailSnapshot {
  const slots: ClipSlotsResponse = {
    clip_id: clip.id,
    items: [],
    warnings: [],
  };
  const videos: ClipVideo[] = [];
  return { clip, slots, videos };
}

function createHarness(options: {
  readPageSnapshot: () => Promise<DirectorPageSnapshot>;
  readClipDetail?: (clipId: number) => Promise<DirectorClipDetailSnapshot>;
  readTask?: (taskId: number) => Promise<Task>;
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

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Director sync", () => {
  it("opens the socket before REST and drops the initial snapshot invalidated by buffered events", async () => {
    const first = deferred<DirectorPageSnapshot>();
    const replacement = deferred<DirectorPageSnapshot>();
    const snapshots = [first.promise, replacement.promise];
    const readPageSnapshot = vi.fn(() => snapshots.shift()!);
    const readTask = vi.fn(async () => makeTask(41, 7));
    const harness = createHarness({ readPageSnapshot, readTask });

    harness.controller.start();
    expect(harness.sockets).toHaveLength(1);
    expect(readPageSnapshot).not.toHaveBeenCalled();

    harness.sockets[0].open();
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(1);

    harness.sockets[0].message(JSON.stringify(makeEvent(41, "running")));
    await flushPromises();
    expect(readTask).toHaveBeenCalledTimes(1);

    const oldSnapshot = makeSnapshot(1);
    first.resolve(oldSnapshot);
    await flushPromises();
    expect(
      harness.states.filter((state) => state.pageSnapshot === oldSnapshot),
    ).toHaveLength(0);
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);

    const latestSnapshot = makeSnapshot(2);
    replacement.resolve(latestSnapshot);
    await flushPromises();
    expect(harness.states.at(-1)?.pageSnapshot).toBe(latestSnapshot);
    expect(harness.states.at(-1)?.pagePhase).toBe("ready");

    harness.unsubscribe();
    harness.controller.dispose();
  });

  it("reconnects after an initial snapshot failure and does not create a polling timer", async () => {
    vi.useFakeTimers();
    const failure = deferred<DirectorPageSnapshot>();
    const second = deferred<DirectorPageSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(failure.promise)
      .mockReturnValueOnce(second.promise);
    const harness = createHarness({ readPageSnapshot });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    failure.reject(new Error("initial snapshot failed"));
    await flushPromises();

    expect(harness.sockets[0].closed).toBe(true);
    expect(harness.states.at(-1)?.pagePhase).toBe("error");
    expect(harness.states.at(-1)?.error).toMatchObject({
      message: "initial snapshot failed",
    });
    expect(vi.getTimerCount()).toBe(1);

    await vi.advanceTimersByTimeAsync(1000);
    expect(harness.sockets).toHaveLength(2);
    expect(readPageSnapshot).toHaveBeenCalledTimes(1);
    harness.sockets[1].open();
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);
    const latestSnapshot = makeSnapshot(2);
    second.resolve(latestSnapshot);
    await flushPromises();
    expect(harness.states.at(-1)?.pagePhase).toBe("ready");
    expect(vi.getTimerCount()).toBe(0);

    harness.controller.dispose();
  });

  it("replaces an in-flight refresh and publishes the terminal notice only after the replacement applies", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const staleRefresh = deferred<DirectorPageSnapshot>();
    const latest = deferred<DirectorPageSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(staleRefresh.promise)
      .mockReturnValueOnce(latest.promise);
    const readTask = vi.fn(async () => makeTask(51, 7));
    const harness = createHarness({ readPageSnapshot, readTask });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    initial.resolve(makeSnapshot(1));
    await flushPromises();

    harness.controller.refreshPage({
      notice: {
        kind: "mutation-success",
        message: "保存已完成",
      },
    });
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);

    harness.sockets[0].message(JSON.stringify(makeEvent(51)));
    await flushPromises();
    staleRefresh.resolve(makeSnapshot(2));
    await flushPromises();
    expect(
      harness.states.some((state) => state.pageSnapshot?.clips[0]?.revision === 2),
    ).toBe(false);
    expect(harness.states.at(-1)?.notices).toEqual([]);
    expect(readPageSnapshot).toHaveBeenCalledTimes(3);

    latest.resolve(makeSnapshot(3));
    await flushPromises();
    expect(harness.states.at(-1)?.notices).toEqual([
      { kind: "mutation-success", message: "保存已完成" },
      { kind: "task-terminal", taskId: 51, message: "最新任务已完成" },
    ]);

    harness.controller.dispose();
  });

  it("allows a repeated terminal event to invalidate the replacement and reuses one task detail request", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const firstReplacement = deferred<DirectorPageSnapshot>();
    const secondReplacement = deferred<DirectorPageSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(firstReplacement.promise)
      .mockReturnValueOnce(secondReplacement.promise);
    const readTask = vi.fn(async () => makeTask(61, 7));
    const harness = createHarness({ readPageSnapshot, readTask });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    initial.resolve(makeSnapshot(1));
    await flushPromises();

    harness.sockets[0].message(JSON.stringify(makeEvent(61)));
    await flushPromises();
    firstReplacement.resolve(makeSnapshot(2));
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);

    harness.sockets[0].message(JSON.stringify(makeEvent(61, "running")));
    await flushPromises();
    secondReplacement.resolve(makeSnapshot(3));
    await flushPromises();

    expect(readTask).toHaveBeenCalledTimes(1);
    expect(readPageSnapshot).toHaveBeenCalledTimes(3);
    expect(harness.states.at(-1)?.pagePhase).toBe("ready");

    harness.controller.dispose();
  });

  it("merges a same-Clip refresh into clean and dirty draft fields", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const firstDetail = deferred<DirectorClipDetailSnapshot>();
    const refreshedDetail = deferred<DirectorClipDetailSnapshot>();
    const readPageSnapshot = vi.fn(() => initial.promise);
    const readClipDetail = vi.fn()
      .mockReturnValueOnce(firstDetail.promise)
      .mockReturnValueOnce(refreshedDetail.promise);
    const harness = createHarness({ readPageSnapshot, readClipDetail });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    initial.resolve(makeSnapshot(1));
    await flushPromises();

    harness.controller.selectClip(7);
    await flushPromises();
    firstDetail.resolve(
      makeDetail(makeClip(7, { user_note: "旧意见", requested_duration: 5 })),
    );
    await flushPromises();
    harness.controller.updateClipDraft({ userNote: "本地意见" });
    harness.controller.refreshSelectedClip();
    await flushPromises();
    refreshedDetail.resolve(
      makeDetail(makeClip(7, { user_note: "服务端新意见", requested_duration: 6 })),
    );
    await flushPromises();

    expect(harness.states.at(-1)?.clipDraft).toEqual({
      baseUserNote: "服务端新意见",
      baseRequestedDuration: 6,
      userNote: "本地意见",
      requestedDuration: "6",
      dirtyUserNote: true,
      dirtyRequestedDuration: false,
    });
    expect(readClipDetail).toHaveBeenCalledTimes(2);

    harness.controller.dispose();
  });

  it("drops an old detail response after switching the selected Clip", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const oldDetail = deferred<DirectorClipDetailSnapshot>();
    const newDetail = deferred<DirectorClipDetailSnapshot>();
    const readPageSnapshot = vi.fn(() => initial.promise);
    const readClipDetail = vi.fn()
      .mockReturnValueOnce(oldDetail.promise)
      .mockReturnValueOnce(newDetail.promise);
    const harness = createHarness({ readPageSnapshot, readClipDetail });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    initial.resolve(makeSnapshot(1, [makeClip(7), makeClip(8)]));
    await flushPromises();

    harness.controller.selectClip(7);
    await flushPromises();
    harness.controller.selectClip(8);
    await flushPromises();
    oldDetail.resolve(makeDetail(makeClip(7, { user_note: "旧" })));
    await flushPromises();
    expect(harness.states.at(-1)?.selectedClipId).toBe(8);
    expect(harness.states.at(-1)?.clipDetail).toBeNull();
    expect(harness.states.at(-1)?.clipDraft).toBeNull();

    newDetail.resolve(makeDetail(makeClip(8, { user_note: "新" })));
    await flushPromises();
    expect(harness.states.at(-1)?.clipDetail?.clip.id).toBe(8);
    expect(
      harness.states.some((state) => state.clipDetail?.clip.id === 7),
    ).toBe(false);

    harness.controller.dispose();
  });

  it("keeps task detail and socket protocol failures visible", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const readPageSnapshot = vi.fn(() => initial.promise);
    const readTask = vi.fn(async () => {
      throw new Error("task detail unavailable");
    });
    const harness = createHarness({ readPageSnapshot, readTask });

    harness.controller.start();
    harness.sockets[0].open();
    await flushPromises();
    initial.resolve(makeSnapshot(1));
    await flushPromises();
    harness.sockets[0].message(JSON.stringify(makeEvent(71)));
    await flushPromises();
    expect(harness.states.at(-1)?.error).toMatchObject({
      message: "task detail unavailable",
    });

    harness.sockets[0].message("{");
    await flushPromises();
    expect(harness.sockets[0].closed).toBe(true);
    expect(harness.states.at(-1)?.error).toBeInstanceOf(SyntaxError);

    harness.controller.dispose();
  });
});
