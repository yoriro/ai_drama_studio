import { describe, expect, it, vi } from "vitest";

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
  for (let index = 0; index < 20; index += 1) {
    await Promise.resolve();
  }
}

class FakeSocket implements DirectorTaskSocket {
  onopen: DirectorTaskSocket["onopen"] = null;
  onmessage: DirectorTaskSocket["onmessage"] = null;
  onerror: DirectorTaskSocket["onerror"] = null;
  onclose: DirectorTaskSocket["onclose"] = null;

  open(): void {
    this.onopen?.({} as Event);
  }

  message(event: TaskEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  close(): void {
    this.onclose?.({} as CloseEvent);
  }
}

function makeClip(revision: number): Clip {
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
  };
}

function makeSnapshot(revision: number): DirectorPageSnapshot {
  return { assets: [], shots: [], clips: [makeClip(revision)] };
}

function makeDetail(revision: number): DirectorClipDetailSnapshot {
  const clip = makeClip(revision);
  const slots: ClipSlotsResponse = {
    clip_id: clip.id,
    items: [],
    warnings: [],
  };
  const videos: ClipVideo[] = [];
  return { clip, slots, videos };
}

function makeTask(id: number): Task {
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
  };
}

function makeEvent(taskId: number): TaskEvent {
  return {
    task_id: taskId,
    type: "gen_clip_video",
    status: "done",
    progress: 1,
    message: "更新事件",
  };
}

async function prepareNoticeRefresh(message: string) {
  const initialPage = deferred<DirectorPageSnapshot>();
  const actionPage = deferred<DirectorPageSnapshot>();
  const replacementPage = deferred<DirectorPageSnapshot>();
  const initialDetail = deferred<DirectorClipDetailSnapshot>();
  const actionDetail = deferred<DirectorClipDetailSnapshot>();
  const replacementDetail = deferred<DirectorClipDetailSnapshot>();
  const readPageSnapshot = vi.fn()
    .mockReturnValueOnce(initialPage.promise)
    .mockReturnValueOnce(actionPage.promise)
    .mockReturnValueOnce(replacementPage.promise);
  const readClipDetail = vi.fn()
    .mockReturnValueOnce(initialDetail.promise)
    .mockReturnValueOnce(actionDetail.promise)
    .mockReturnValueOnce(replacementDetail.promise);
  const readTask = vi.fn(async (taskId: number) => makeTask(taskId));
  const socket = new FakeSocket();
  const controller = createDirectorSync({
    readPageSnapshot,
    readClipDetail,
    readTask,
    openSocket: () => socket,
  });

  controller.start();
  socket.open();
  initialPage.resolve(makeSnapshot(1));
  await flushPromises();
  controller.selectClip(7);
  await flushPromises();
  initialDetail.resolve(makeDetail(1));
  await flushPromises();
  controller.refreshPage({
    notice: { kind: "mutation-success", message },
    noticeAfterDetail: true,
    refreshSelectedClip: true,
  });
  await flushPromises();

  return {
    actionDetail,
    actionPage,
    controller,
    readClipDetail,
    readPageSnapshot,
    readTask,
    replacementDetail,
    replacementPage,
    socket,
  };
}

describe("Director mutation notice ordering", () => {
  it.each([
    ["save", "Clip #7 设置已保存"],
    ["slot", "槽位已按最新快照更新"],
  ] as const)(
    "waits for both snapshots for %s across detail/page order and event replacement",
    async (_action, message) => {
      for (const detailFirst of [true, false]) {
        const harness = await prepareNoticeRefresh(message);
        if (detailFirst) {
          harness.actionDetail.resolve(makeDetail(2));
          await flushPromises();
          expect(harness.controller.getState().notices).toEqual([]);
        }

        harness.socket.message(makeEvent(91));
        await flushPromises();
        harness.actionPage.resolve(makeSnapshot(2));
        await flushPromises();
        expect(harness.readPageSnapshot).toHaveBeenCalledTimes(3);
        expect(harness.controller.getState().pageSnapshot?.clips[0]?.revision).toBe(1);
        expect(harness.controller.getState().notices).toEqual([]);

        if (!detailFirst) {
          harness.actionDetail.resolve(makeDetail(2));
          await flushPromises();
        }
        expect(harness.readClipDetail).toHaveBeenCalledTimes(3);
        expect(harness.controller.getState().notices).toEqual([]);

        if (detailFirst) {
          harness.replacementPage.resolve(makeSnapshot(3));
          await flushPromises();
          expect(harness.controller.getState().notices).toEqual([]);
          harness.replacementDetail.resolve(makeDetail(3));
        } else {
          harness.replacementDetail.resolve(makeDetail(3));
          await flushPromises();
          expect(harness.controller.getState().notices).toEqual([]);
          harness.replacementPage.resolve(makeSnapshot(3));
        }
        await flushPromises();

        const state = harness.controller.getState();
        expect(state.pageSnapshot?.clips[0]?.revision).toBe(3);
        expect(state.clipDetail?.clip.revision).toBe(3);
        expect(state.notices).toEqual([
          { kind: "mutation-success", message },
        ]);
        expect(state.notices).toHaveLength(1);
        expect(harness.readTask).toHaveBeenCalledTimes(1);
        harness.controller.dispose();
      }
    },
  );

  it("does not publish a save notice when either latest refresh fails", async () => {
    const initialPage = deferred<DirectorPageSnapshot>();
    const failedPage = deferred<DirectorPageSnapshot>();
    const detail = deferred<DirectorClipDetailSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initialPage.promise)
      .mockReturnValueOnce(failedPage.promise);
    const readClipDetail = vi.fn()
      .mockReturnValueOnce(detail.promise)
      .mockReturnValueOnce(Promise.resolve(makeDetail(2)));
    const socket = new FakeSocket();
    const controller = createDirectorSync({
      readPageSnapshot,
      readClipDetail,
      readTask: vi.fn(),
      openSocket: () => socket,
    });
    controller.start();
    socket.open();
    initialPage.resolve(makeSnapshot(1));
    await flushPromises();
    controller.selectClip(7);
    await flushPromises();
    detail.resolve(makeDetail(1));
    await flushPromises();

    controller.refreshPage({
      notice: { kind: "mutation-success", message: "Clip #7 设置已保存" },
      noticeAfterDetail: true,
      refreshSelectedClip: true,
    });
    await flushPromises();
    failedPage.reject(new Error("页面最新快照失败"));
    await flushPromises();

    expect(controller.getState().pagePhase).toBe("error");
    expect(controller.getState().pageError).toMatchObject({
      message: "页面最新快照失败",
    });
    expect(controller.getState().notices).toEqual([]);
    controller.dispose();
  });
});
