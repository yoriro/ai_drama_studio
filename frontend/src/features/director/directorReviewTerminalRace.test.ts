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
  for (let index = 0; index < 12; index += 1) {
    await Promise.resolve();
  }
}

function makeClip(
  revision: number,
  overrides: Partial<Clip> = {},
): Clip {
  return {
    id: 7,
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
    ...overrides,
  };
}

function makeSnapshot(revision: number): DirectorPageSnapshot {
  return { assets: [], shots: [], clips: [makeClip(revision)] };
}

function makeDetail(videoIds: number[] = []): DirectorClipDetailSnapshot {
  const slots: ClipSlotsResponse = {
    clip_id: 7,
    items: [],
    warnings: [],
  };
  const videos: ClipVideo[] = videoIds.map((id) => ({
    id,
    clip_id: 7,
    sha256: `hash-${id}`,
    seed: String(id),
    requested_duration: 5,
    actual_duration: 5,
    is_current: true,
    media_url: `/media/clip-videos/${id}`,
    created_at: "2026-09-04T00:00:03Z",
  }));
  return { clip: makeClip(2), slots, videos };
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

class FakeSocket implements DirectorTaskSocket {
  onopen: DirectorTaskSocket["onopen"] = null;
  onmessage: DirectorTaskSocket["onmessage"] = null;
  onerror: DirectorTaskSocket["onerror"] = null;
  onclose: DirectorTaskSocket["onclose"] = null;
  closed = false;

  open(): void {
    this.onopen?.({} as Event);
  }

  message(data: string): void {
    this.onmessage?.({ data } as MessageEvent);
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.onclose?.({} as CloseEvent);
  }
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Director terminal refresh races", () => {
  it("binds an event recorded before refresh to that refresh and consumes it once", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const afterEvent = deferred<DirectorPageSnapshot>();
    const taskDetail = deferred<Task>();
    const firstDetail = deferred<DirectorClipDetailSnapshot>();
    const refreshedDetail = deferred<DirectorClipDetailSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(afterEvent.promise);
    const readTask = vi.fn(() => taskDetail.promise);
    const readClipDetail = vi.fn()
      .mockReturnValueOnce(firstDetail.promise)
      .mockReturnValueOnce(refreshedDetail.promise);
    const socket = new FakeSocket();
    const states: ReturnType<ReturnType<typeof createDirectorSync>["getState"]>[] = [];
    const controller = createDirectorSync({
      readPageSnapshot,
      readClipDetail,
      readTask,
      openSocket: () => socket,
    });
    const unsubscribe = controller.subscribe((state) => {
      states.push(state);
    });

    controller.start();
    socket.open();
    await flushPromises();
    initial.resolve(makeSnapshot(1));
    await flushPromises();
    controller.selectClip(7);
    await flushPromises();
    firstDetail.resolve(makeDetail());
    await flushPromises();

    socket.message(JSON.stringify(makeEvent(51)));
    await flushPromises();
    controller.refreshPage();
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);

    taskDetail.resolve(makeTask(51));
    await flushPromises();
    afterEvent.resolve(makeSnapshot(2));
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);
    expect(readClipDetail).toHaveBeenCalledTimes(2);
    refreshedDetail.resolve(makeDetail([901]));
    await flushPromises();

    const finalState = states.at(-1);
    expect(finalState?.pagePhase).toBe("ready");
    expect(finalState?.pageSnapshot?.clips[0]?.revision).toBe(2);
    expect(finalState?.clipDetail?.videos.map((video) => video.id)).toEqual([
      901,
    ]);
    expect(finalState?.notices).toEqual([
      { kind: "task-terminal", taskId: 51, message: "最新任务已完成" },
    ]);
    expect(readTask).toHaveBeenCalledTimes(1);
    const pageAppliedIndex = states.findIndex(
      (state) => state.pageSnapshot?.clips[0]?.revision === 2,
    );
    const detailAppliedIndex = states.findIndex(
      (state) => state.clipDetail?.videos.some((video) => video.id === 901),
    );
    const noticeIndex = states.findIndex((state) => state.notices.length > 0);
    expect(noticeIndex).toBeGreaterThan(pageAppliedIndex);
    expect(noticeIndex).toBeGreaterThanOrEqual(detailAppliedIndex);

    unsubscribe();
    controller.dispose();
  });

  it("invalidates a refresh started before the event and applies one replacement", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const staleRefresh = deferred<DirectorPageSnapshot>();
    const replacement = deferred<DirectorPageSnapshot>();
    const firstDetail = deferred<DirectorClipDetailSnapshot>();
    const refreshedDetail = deferred<DirectorClipDetailSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(staleRefresh.promise)
      .mockReturnValueOnce(replacement.promise);
    const readClipDetail = vi.fn()
      .mockReturnValueOnce(firstDetail.promise)
      .mockReturnValueOnce(refreshedDetail.promise);
    const readTask = vi.fn(async () => makeTask(52));
    const socket = new FakeSocket();
    const states: ReturnType<ReturnType<typeof createDirectorSync>["getState"]>[] = [];
    const controller = createDirectorSync({
      readPageSnapshot,
      readClipDetail,
      readTask,
      openSocket: () => socket,
    });
    const unsubscribe = controller.subscribe((state) => {
      states.push(state);
    });

    controller.start();
    socket.open();
    await flushPromises();
    initial.resolve(makeSnapshot(1));
    await flushPromises();
    controller.selectClip(7);
    await flushPromises();
    firstDetail.resolve(makeDetail());
    await flushPromises();

    controller.refreshPage();
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);
    socket.message(JSON.stringify(makeEvent(52)));
    await flushPromises();
    staleRefresh.resolve(makeSnapshot(2));
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(3);
    expect(
      states.some((state) => state.pageSnapshot?.clips[0]?.revision === 2),
    ).toBe(false);

    replacement.resolve(makeSnapshot(3));
    await flushPromises();
    refreshedDetail.resolve(makeDetail([902]));
    await flushPromises();

    const finalState = states.at(-1);
    expect(finalState?.pagePhase).toBe("ready");
    expect(finalState?.pageSnapshot?.clips[0]?.revision).toBe(3);
    expect(finalState?.notices).toEqual([
      { kind: "task-terminal", taskId: 52, message: "最新任务已完成" },
    ]);
    expect(readTask).toHaveBeenCalledTimes(1);
    expect(readClipDetail).toHaveBeenCalledTimes(2);

    unsubscribe();
    controller.dispose();
  });

  it("shows the latest task detail error instead of leaving refresh loading", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const refresh = deferred<DirectorPageSnapshot>();
    const taskDetail = deferred<Task>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(refresh.promise);
    const readTask = vi.fn(() => taskDetail.promise);
    const socket = new FakeSocket();
    const states: ReturnType<ReturnType<typeof createDirectorSync>["getState"]>[] = [];
    const controller = createDirectorSync({
      readPageSnapshot,
      readTask,
      openSocket: () => socket,
    });
    const unsubscribe = controller.subscribe((state) => {
      states.push(state);
    });

    controller.start();
    socket.open();
    await flushPromises();
    initial.resolve(makeSnapshot(1));
    await flushPromises();
    socket.message(JSON.stringify(makeEvent(53)));
    await flushPromises();
    controller.refreshPage();
    await flushPromises();
    refresh.resolve(makeSnapshot(2));
    taskDetail.reject(new Error("terminal detail unavailable"));
    await flushPromises();

    const finalState = states.at(-1);
    expect(finalState?.pagePhase).toBe("error");
    expect(finalState?.error).toMatchObject({
      message: "terminal detail unavailable",
    });
    expect(finalState?.pageSnapshot?.clips[0]?.revision).toBe(1);
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);

    unsubscribe();
    controller.dispose();
  });
});
