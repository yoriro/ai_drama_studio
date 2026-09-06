import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  listAssets,
  type Asset,
  parseAssetListResponse,
} from "../../api/assets";
import { ApiError } from "../../api/client";
import {
  getClip,
  listClipSlots,
  listClipVideos,
  listClips,
  type Clip,
  type ClipSlot,
  type ClipVideo,
  parseClipResponse,
  parseClipSlotsResponse,
  parseClipVideosResponse,
} from "../../api/clips";
import { listShots, parseShotListResponse, type Shot } from "../../api/shots";
import {
  createDirectorMutationAdapter,
  createDirectorSync,
  type DirectorMutationAction,
  type DirectorMutationRefreshScope,
  type DirectorPageSnapshot,
  type DirectorRefreshOptions,
  type DirectorTaskSocket,
} from "./directorSync";

interface MutationCase {
  name: string;
  action: DirectorMutationAction;
  method: string;
  path: string;
  scope: DirectorMutationRefreshScope;
}

const mutationCases: MutationCase[] = [
  {
    name: "save",
    action: { kind: "save", clipId: 7, input: { user_note: "updated" } },
    method: "PATCH",
    path: "/api/clips/7",
    scope: "page-and-detail",
  },
  {
    name: "delete",
    action: { kind: "delete", clipId: 7 },
    method: "DELETE",
    path: "/api/clips/7",
    scope: "page",
  },
  {
    name: "slot",
    action: { kind: "slot-enabled", clipId: 7, slotNo: 1, enabled: false },
    method: "PATCH",
    path: "/api/clips/7/slots/1",
    scope: "page-and-detail",
  },
  {
    name: "take",
    action: { kind: "take-current", clipId: 7, videoId: 8 },
    method: "PUT",
    path: "/api/clips/7/current-video",
    scope: "detail",
  },
  {
    name: "generate",
    action: { kind: "generate", clipId: 7, input: {} },
    method: "POST",
    path: "/api/clips/7/generate-video",
    scope: "page-and-detail",
  },
];

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function asset(): Asset {
  return {
    id: 101,
    project_id: 1,
    type: "character",
    name: "角色",
    description: "描述",
    source: "manual",
    revision: 1,
    created_at: "2026-09-04T00:00:00Z",
    updated_at: "2026-09-04T00:00:00Z",
  };
}

function shot(): Shot {
  return {
    id: 1,
    episode_id: 1,
    order_index: 1,
    duration_est: 1,
    shot_type: "中景",
    camera: "固定",
    description: "描述",
    dialogue: "",
    asset_ids: [101],
    status: "normal",
    revision: 1,
    created_at: "2026-09-04T00:00:00Z",
    updated_at: "2026-09-04T00:00:00Z",
  };
}

function clip(): Clip {
  return {
    id: 7,
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

function slot(): ClipSlot {
  return {
    id: 9,
    clip_id: 7,
    slot_no: 1,
    asset_id: 101,
    asset_name_snapshot: "角色",
    asset_type_snapshot: "character",
    asset_deleted: false,
    enabled: true,
    image_source: "asset_current",
    image_url: "/media/asset-images/101",
  };
}

function video(): ClipVideo {
  return {
    id: 8,
    clip_id: 7,
    sha256: "a".repeat(64),
    seed: "1",
    requested_duration: 5,
    actual_duration: 5,
    is_current: false,
    media_url: "/media/clip-videos/8",
    created_at: "2026-09-04T00:00:00Z",
  };
}

async function readPageSnapshot(): Promise<DirectorPageSnapshot> {
  const [rawAssets, rawShots, rawClips] = await Promise.all([
    listAssets(1),
    listShots(1),
    listClips(1),
  ]);
  return {
    assets: parseAssetListResponse(rawAssets),
    shots: parseShotListResponse(rawShots),
    clips: rawClips.map((item) => parseClipResponse(item)),
  };
}

async function readClipDetail(): Promise<{
  clip: Clip;
  slots: ReturnType<typeof parseClipSlotsResponse>;
  videos: ClipVideo[];
}> {
  const [rawClip, rawSlots, rawVideos] = await Promise.all([
    getClip(7),
    listClipSlots(7),
    listClipVideos(7),
  ]);
  return {
    clip: parseClipResponse(rawClip),
    slots: parseClipSlotsResponse(rawSlots),
    videos: parseClipVideosResponse(rawVideos),
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Director production mutation wiring", () => {
  it.each(mutationCases)(
    "runs the $name action once and refreshes only its authority after a 404 or 409",
    async ({ action, method, name, path, scope }) => {
      for (const status of [404, 409]) {
        fetchMock.mockReset();
        fetchMock.mockImplementation(async (input, init) => {
          const requestPath = new URL(String(input), "http://localhost").pathname;
          const requestMethod = init?.method ?? "GET";
          if (requestMethod === method && requestPath === path) {
            return jsonResponse(
              {
                detail: {
                  code: `${name}_conflict`,
                  message: `${name} detail.message ${status}`,
                },
              },
              status,
            );
          }
          if (requestMethod === "GET" && requestPath === "/api/projects/1/assets") {
            return jsonResponse([asset()]);
          }
          if (requestMethod === "GET" && requestPath === "/api/episodes/1/shots") {
            return jsonResponse([shot()]);
          }
          if (requestMethod === "GET" && requestPath === "/api/episodes/1/clips") {
            return jsonResponse([clip()]);
          }
          if (requestMethod === "GET" && requestPath === "/api/clips/7") {
            return jsonResponse(clip());
          }
          if (requestMethod === "GET" && requestPath === "/api/clips/7/slots") {
            return jsonResponse({ clip_id: 7, items: [slot()], warnings: [] });
          }
          if (requestMethod === "GET" && requestPath === "/api/clips/7/videos") {
            return jsonResponse([video()]);
          }
          throw new Error(`unexpected request ${requestMethod} ${requestPath}`);
        });

        const authorityReads: Array<Promise<unknown>> = [];
        const refreshPage = vi.fn((options?: DirectorRefreshOptions) => {
          authorityReads.push(readPageSnapshot());
          if (options?.refreshSelectedClip === true) {
            authorityReads.push(readClipDetail());
          }
        });
        const refreshSelectedClip = vi.fn(() => {
          authorityReads.push(readClipDetail());
        });
        const setError = vi.fn();
        const onSuccess = vi.fn();
        const adapter = createDirectorMutationAdapter({
          refreshPage,
          refreshSelectedClip,
        });

        const pending = adapter.run(action, { setError, onSuccess });
        expect(pending).not.toBeNull();
        await pending;
        await Promise.all(authorityReads);

        const error = setError.mock.calls[0]?.[0];
        expect(error).toBeInstanceOf(ApiError);
        expect(error).toEqual(
          expect.objectContaining({
            status,
            message: `${name} detail.message ${status}`,
          }),
        );
        expect(onSuccess).not.toHaveBeenCalled();

        const requests = fetchMock.mock.calls.map(([input, init]) => ({
          method: init?.method ?? "GET",
          path: new URL(String(input), "http://localhost").pathname,
        }));
        expect(
          requests.filter(
            (request) => request.method === method && request.path === path,
          ),
        ).toHaveLength(1);
        if (scope === "page") {
          expect(refreshPage).toHaveBeenCalledTimes(1);
          expect(refreshPage).toHaveBeenCalledWith();
          expect(refreshSelectedClip).not.toHaveBeenCalled();
          expect(
            requests.filter((request) => request.method === "GET"),
          ).toHaveLength(3);
        } else if (scope === "page-and-detail") {
          expect(refreshPage).toHaveBeenCalledTimes(1);
          expect(refreshPage).toHaveBeenCalledWith({
            refreshSelectedClip: true,
          });
          expect(refreshSelectedClip).not.toHaveBeenCalled();
          expect(
            requests.filter((request) => request.method === "GET"),
          ).toHaveLength(6);
        } else {
          expect(refreshPage).not.toHaveBeenCalled();
          expect(refreshSelectedClip).toHaveBeenCalledTimes(1);
          expect(
            requests.filter((request) => request.method === "GET"),
          ).toHaveLength(3);
        }
      }
    },
  );

  it("clears selection and detail when a 404 refresh shows the Clip disappeared", async () => {
    let pageClipReads = 0;
    const lateDetail = {
      resolve: null as ((response: Response) => void) | null,
    };
    const socket: DirectorTaskSocket = {
      onopen: null,
      onmessage: null,
      onerror: null,
      onclose: null,
      close: vi.fn(),
    };

    fetchMock.mockImplementation((input, init) => {
      const requestPath = new URL(String(input), "http://localhost").pathname;
      const requestMethod = init?.method ?? "GET";
      if (requestMethod === "DELETE" && requestPath === "/api/clips/7") {
        return Promise.resolve(
          jsonResponse(
            {
              detail: {
                code: "not_found",
                message: "Clip disappeared",
              },
            },
            404,
          ),
        );
      }
      if (requestMethod === "GET" && requestPath === "/api/projects/1/assets") {
        return Promise.resolve(jsonResponse([asset()]));
      }
      if (requestMethod === "GET" && requestPath === "/api/episodes/1/shots") {
        return Promise.resolve(jsonResponse([shot()]));
      }
      if (requestMethod === "GET" && requestPath === "/api/episodes/1/clips") {
        pageClipReads += 1;
        return Promise.resolve(
          jsonResponse(pageClipReads === 1 ? [clip()] : []),
        );
      }
      if (requestMethod === "GET" && requestPath === "/api/clips/7") {
        return new Promise<Response>((resolve) => {
          lateDetail.resolve = resolve;
        });
      }
      if (requestMethod === "GET" && requestPath === "/api/clips/7/slots") {
        return Promise.resolve(
          jsonResponse({ clip_id: 7, items: [slot()], warnings: [] }),
        );
      }
      if (requestMethod === "GET" && requestPath === "/api/clips/7/videos") {
        return Promise.resolve(jsonResponse([video()]));
      }
      throw new Error(`unexpected request ${requestMethod} ${requestPath}`);
    });

    const sync = createDirectorSync({
      readPageSnapshot,
      readClipDetail,
      openSocket: () => socket,
    });
    const setError = vi.fn();
    const onSuccess = vi.fn();
    const adapter = createDirectorMutationAdapter({
      refreshPage: (options) => sync.refreshPage(options),
      refreshSelectedClip: () => sync.refreshSelectedClip(),
    });

    const flush = async (): Promise<void> => {
      for (let index = 0; index < 24; index += 1) {
        await Promise.resolve();
      }
    };

    try {
      sync.start();
      socket.onopen?.({} as Event);
      await flush();
      expect(sync.getState().pageSnapshot?.clips).toHaveLength(1);

      sync.selectClip(7);
      await flush();
      expect(sync.getState().selectedClipId).toBe(7);
      expect(lateDetail.resolve).not.toBeNull();

      const pending = adapter.run(
        { kind: "delete", clipId: 7 },
        { setError, onSuccess },
      );
      expect(pending).not.toBeNull();
      await pending;
      await flush();

      const error = setError.mock.calls[0]?.[0];
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toEqual(
        expect.objectContaining({
          status: 404,
          message: "Clip disappeared",
        }),
      );
      expect(onSuccess).not.toHaveBeenCalled();
      expect(
        fetchMock.mock.calls.filter(([input, requestInit]) => {
          const requestPath = new URL(String(input), "http://localhost").pathname;
          return (
            requestPath === "/api/clips/7" &&
            (requestInit?.method ?? "GET") === "DELETE"
          );
        }),
      ).toHaveLength(1);
      expect(
        fetchMock.mock.calls.filter(([input, requestInit]) => {
          const requestPath = new URL(String(input), "http://localhost").pathname;
          return (
            requestPath === "/api/episodes/1/clips" &&
            (requestInit?.method ?? "GET") === "GET"
          );
        }),
      ).toHaveLength(2);
      expect(sync.getState().selectedClipId).toBeNull();
      expect(sync.getState().clipDetail).toBeNull();

      lateDetail.resolve?.(jsonResponse(clip()));
      await flush();
      expect(sync.getState().selectedClipId).toBeNull();
      expect(sync.getState().clipDetail).toBeNull();
    } finally {
      lateDetail.resolve?.(jsonResponse(clip()));
      sync.dispose();
    }
  });
});
