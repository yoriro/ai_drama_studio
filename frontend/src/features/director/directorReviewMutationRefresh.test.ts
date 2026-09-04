import { describe, expect, it, vi } from "vitest";

import { ApiError, ApiProtocolError } from "../../api/client";
import type { Clip } from "../../api/clips";
import type { Task } from "../../api/tasks";
import {
  createDirectorSync,
  handleDirectorMutationError,
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
  for (let index = 0; index < 16; index += 1) {
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

  close(): void {
    this.onclose?.({} as CloseEvent);
  }
}

function makeClip(id = 7): Clip {
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
    created_at: "2026-09-04T00:00:00Z",
    updated_at: "2026-09-04T00:00:00Z",
  };
}

function makeSnapshot(clips: Clip[]): DirectorPageSnapshot {
  return { assets: [], shots: [], clips };
}

async function rejectMutation(
  error: unknown,
  scope: Parameters<typeof handleDirectorMutationError>[1],
  handlers: Parameters<typeof handleDirectorMutationError>[2],
): Promise<void> {
  const mutation = vi.fn(async () => {
    throw error;
  });
  await mutation().then(
    () => {
      throw new Error("mutation unexpectedly succeeded");
    },
    (caught: unknown) => {
      handleDirectorMutationError(caught, scope, handlers);
    },
  );
  expect(mutation).toHaveBeenCalledTimes(1);
}

describe("Director mutation authority refresh", () => {
  it.each([
    ["save", "page-and-detail"],
    ["delete", "page"],
    ["slot", "page-and-detail"],
    ["take", "detail"],
    ["generate", "page-and-detail"],
  ] as const)(
    "refreshes the %s impact after a structured 404/409 without replaying it",
    async (_action, scope) => {
      for (const status of [404, 409]) {
        const error = new ApiError(
          status,
          `${_action}_conflict`,
          `${_action} authority message ${status}`,
        );
        const setError = vi.fn();
        const authorityGets: string[] = [];
        const pageGets = [
          "/api/projects/1/assets",
          "/api/episodes/1/shots",
          "/api/episodes/1/clips",
        ];
        const detailGets = [
          "/api/clips/7",
          "/api/clips/7/slots",
          "/api/clips/7/videos",
        ];
        const refreshPage = vi.fn((options?: { refreshSelectedClip?: boolean }) => {
          authorityGets.push(...pageGets);
          if (options?.refreshSelectedClip === true) {
            authorityGets.push(...detailGets);
          }
        });
        const refreshSelectedClip = vi.fn(() => {
          authorityGets.push(...detailGets);
        });
        await rejectMutation(error, scope, {
          setError,
          refreshPage,
          refreshSelectedClip,
        });

        expect(setError).toHaveBeenCalledTimes(1);
        expect(setError).toHaveBeenCalledWith(error);
        if (scope === "page") {
          expect(refreshPage).toHaveBeenCalledTimes(1);
          expect(refreshPage).toHaveBeenCalledWith();
          expect(refreshSelectedClip).not.toHaveBeenCalled();
        } else if (scope === "page-and-detail") {
          expect(refreshPage).toHaveBeenCalledTimes(1);
          expect(refreshPage).toHaveBeenCalledWith({
            refreshSelectedClip: true,
          });
          expect(refreshSelectedClip).not.toHaveBeenCalled();
        } else {
          expect(refreshPage).not.toHaveBeenCalled();
          expect(refreshSelectedClip).toHaveBeenCalledTimes(1);
        }
        expect(authorityGets).toEqual(
          scope === "page"
            ? pageGets
            : scope === "page-and-detail"
              ? [...pageGets, ...detailGets]
              : detailGets,
        );
        const successNotices: string[] = [];
        expect(successNotices).toEqual([]);
      }
    },
  );

  it("uses the latest page list to clear a deleted Clip selection and detail", async () => {
    const first = deferred<DirectorPageSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(makeSnapshot([]));
    const readTask = vi.fn<(_: number) => Promise<Task>>();
    const socket = new FakeSocket();
    const controller = createDirectorSync({
      readPageSnapshot,
      readClipDetail: vi.fn(async (clipId) => ({
        clip: makeClip(clipId),
        slots: { clip_id: clipId, items: [], warnings: [] },
        videos: [],
      })),
      readTask,
      openSocket: () => socket,
    });

    controller.start();
    socket.open();
    first.resolve(makeSnapshot([makeClip()]));
    await flushPromises();
    controller.selectClip(7);
    await flushPromises();
    expect(controller.getState().selectedClipId).toBe(7);
    expect(controller.getState().detailPhase).toBe("ready");

    const error = new ApiError(404, "clip_not_found", "Clip 已被删除");
    const setError = vi.fn();
    await rejectMutation(error, "page", {
      setError,
      refreshPage: (options) => controller.refreshPage(options),
      refreshSelectedClip: () => controller.refreshSelectedClip(),
    });
    await flushPromises();

    const state = controller.getState();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);
    expect(setError).toHaveBeenCalledWith(error);
    expect(state.pageSnapshot?.clips).toEqual([]);
    expect(state.selectedClipId).toBeNull();
    expect(state.clipDetail).toBeNull();
    expect(state.detailPhase).toBe("idle");
    expect(state.notices).toEqual([]);
    controller.dispose();
  });

  it("leaves 422, 500, transport, and protocol failures visible without refresh", async () => {
    for (const error of [
      new ApiError(422, "validation_error", "请求内容无效"),
      new ApiError(500, "internal_error", "服务端暂时不可用"),
      new TypeError("网络连接失败"),
      new ApiProtocolError(404, "错误体不是结构化协议"),
    ]) {
      const setError = vi.fn();
      const refreshPage = vi.fn();
      const refreshSelectedClip = vi.fn();
      await rejectMutation(error, "page-and-detail", {
        setError,
        refreshPage,
        refreshSelectedClip,
      });
      expect(setError).toHaveBeenCalledWith(error);
      expect(refreshPage).not.toHaveBeenCalled();
      expect(refreshSelectedClip).not.toHaveBeenCalled();
    }
  });

  it("keeps the latest refresh failure as the visible authority error", async () => {
    const initial = deferred<DirectorPageSnapshot>();
    const refreshFailure = new Error("权威页面刷新失败");
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initial.promise)
      .mockRejectedValueOnce(refreshFailure);
    const socket = new FakeSocket();
    const controller = createDirectorSync({
      readPageSnapshot,
      readTask: vi.fn(),
      openSocket: () => socket,
    });
    controller.start();
    socket.open();
    initial.resolve(makeSnapshot([makeClip()]));
    await flushPromises();
    expect(controller.getState().pagePhase).toBe("ready");

    await rejectMutation(new ApiError(409, "conflict", "资源状态已变化"), "page", {
      setError: vi.fn(),
      refreshPage: (options) => controller.refreshPage(options),
      refreshSelectedClip: () => controller.refreshSelectedClip(),
    });
    await flushPromises();

    expect(controller.getState().pagePhase).toBe("error");
    expect(controller.getState().pageError).toBe(refreshFailure);
    expect(controller.getState().notices).toEqual([]);
    controller.dispose();
  });
});
