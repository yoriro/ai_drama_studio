import { describe, expect, it, vi } from "vitest";

import type { Clip } from "../../api/clips";
import {
  createDirectorSync,
  resolveDirectorClipSave,
  type DirectorClipDetailSnapshot,
  type DirectorPageSnapshot,
  type DirectorTaskSocket,
} from "./directorSync";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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

function makeClip(id: number, userNote: string | null = null): Clip {
  return {
    id,
    episode_id: 1,
    generation_mode: "ref2v",
    user_note: userNote,
    requested_duration: 5,
    generation_state: "ready",
    freshness: "fresh",
    revision: 1,
    shot_ids: [id],
    start_order_index: id,
    end_order_index: id,
    enabled_slot_count: 1,
    warnings: [],
    created_at: "2026-09-06T00:00:00Z",
    updated_at: "2026-09-06T00:00:00Z",
  };
}

function makeDetail(clip: Clip): DirectorClipDetailSnapshot {
  return {
    clip,
    slots: { clip_id: clip.id, items: [], warnings: [] },
    videos: [],
  };
}

function makeSnapshot(clips: Clip[]): DirectorPageSnapshot {
  return { assets: [], shots: [], clips };
}

function createController(
  readPageSnapshot: () => Promise<DirectorPageSnapshot>,
  readClipDetail: (clipId: number) => Promise<DirectorClipDetailSnapshot>,
) {
  const socket = new FakeSocket();
  const controller = createDirectorSync({
    readPageSnapshot,
    readClipDetail,
    openSocket: () => socket,
  });
  controller.start();
  socket.open();
  return { controller, socket };
}

describe("Director old Clip save isolation", () => {
  it("keeps a late Clip A save out of selected Clip B and rereads A after reselection", async () => {
    const clipA = makeClip(7);
    const clipB = makeClip(8, "B base");
    const savedA = makeClip(7, "A saved");
    const initialPage = deferred<DirectorPageSnapshot>();
    const refreshedPage = deferred<DirectorPageSnapshot>();
    const pendingBDetail = deferred<DirectorClipDetailSnapshot>();
    const rereadADetail = deferred<DirectorClipDetailSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initialPage.promise)
      .mockReturnValueOnce(refreshedPage.promise);
    const readClipDetail = vi.fn()
      .mockResolvedValueOnce(makeDetail(clipA))
      .mockReturnValueOnce(pendingBDetail.promise)
      .mockReturnValueOnce(rereadADetail.promise);
    const { controller } = createController(readPageSnapshot, readClipDetail);
    await flushPromises();

    initialPage.resolve(makeSnapshot([clipA, clipB]));
    await flushPromises();
    controller.selectClip(7);
    await flushPromises();
    expect(controller.getState().clipDetail?.clip.id).toBe(7);

    const patch = deferred<Clip>();
    const save = vi.fn(
      (_clipId: number, _input: { user_note: string }) => patch.promise,
    );
    const savePromise = save(7, { user_note: "A saved" });
    expect(save).toHaveBeenCalledTimes(1);

    controller.selectClip(8);
    await flushPromises();
    expect(controller.getState().selectedClipId).toBe(8);

    const action = {
      clipId: 7,
      actionGeneration: 1,
      selectionGeneration: 1,
    };
    const pageRefresh = savePromise.then(() => {
      const resolution = resolveDirectorClipSave(action, {
        selectedClipId: controller.getState().selectedClipId,
        latestActionGeneration: 1,
        selectionGeneration: 2,
      });
      expect(resolution.notice).toBeNull();
      controller.refreshPage();
    });
    patch.resolve(savedA);
    await flushPromises();
    expect(readPageSnapshot).toHaveBeenCalledTimes(2);
    expect(readClipDetail).toHaveBeenCalledTimes(2);
    expect(controller.getState().selectedClipId).toBe(8);
    expect(controller.getState().notices).toEqual([]);

    refreshedPage.resolve(makeSnapshot([savedA, clipB]));
    await flushPromises();
    expect(readClipDetail).toHaveBeenCalledTimes(2);
    expect(controller.getState().selectedClipId).toBe(8);

    pendingBDetail.resolve(makeDetail(clipB));
    await flushPromises();
    controller.updateClipDraft({ userNote: "B draft" });
    expect(controller.getState().clipDraft?.userNote).toBe("B draft");
    expect(controller.getState().notices).toEqual([]);
    await pageRefresh;

    controller.selectClip(7);
    await flushPromises();
    rereadADetail.resolve(makeDetail(savedA));
    await flushPromises();

    expect(readClipDetail).toHaveBeenCalledTimes(3);
    expect(readClipDetail).toHaveBeenLastCalledWith(7);
    expect(controller.getState().selectedClipId).toBe(7);
    expect(controller.getState().clipDetail?.clip.user_note).toBe("A saved");
    expect(controller.getState().clipDraft?.userNote).toBe("A saved");
    controller.dispose();
  });

  it("publishes one A success notice only after A page and detail snapshots", async () => {
    const clipA = makeClip(7);
    const savedA = makeClip(7, "A saved");
    const initialPage = deferred<DirectorPageSnapshot>();
    const refreshedPage = deferred<DirectorPageSnapshot>();
    const refreshedDetail = deferred<DirectorClipDetailSnapshot>();
    const readPageSnapshot = vi.fn()
      .mockReturnValueOnce(initialPage.promise)
      .mockReturnValueOnce(refreshedPage.promise);
    const readClipDetail = vi.fn()
      .mockResolvedValueOnce(makeDetail(clipA))
      .mockReturnValueOnce(refreshedDetail.promise);
    const { controller } = createController(readPageSnapshot, readClipDetail);
    await flushPromises();
    initialPage.resolve(makeSnapshot([clipA]));
    await flushPromises();
    controller.selectClip(7);
    await flushPromises();

    const resolution = resolveDirectorClipSave(
      { clipId: 7, actionGeneration: 1, selectionGeneration: 1 },
      {
        selectedClipId: 7,
        latestActionGeneration: 1,
        selectionGeneration: 1,
      },
    );
    expect(resolution.notice).toEqual({
      kind: "mutation-success",
      message: "Clip #7 设置已保存",
    });
    controller.refreshPage({
      notice: resolution.notice!,
      noticeAfterDetail: true,
      refreshSelectedClip: resolution.refreshSelectedClip,
    });
    expect(controller.getState().notices).toEqual([]);

    refreshedDetail.resolve(makeDetail(savedA));
    await flushPromises();
    expect(controller.getState().notices).toEqual([]);
    refreshedPage.resolve(makeSnapshot([savedA]));
    await flushPromises();

    expect(readPageSnapshot).toHaveBeenCalledTimes(2);
    expect(readClipDetail).toHaveBeenCalledTimes(2);
    expect(controller.getState().notices).toEqual([
      { kind: "mutation-success", message: "Clip #7 设置已保存" },
    ]);
    controller.dispose();
  });
});
