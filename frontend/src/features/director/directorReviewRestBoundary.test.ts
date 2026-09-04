import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProtocolError } from "../../api/client";
import {
  listClipVideos,
  parseClipResponse,
  parseClipSlotResponse,
  parseClipVideoResponse,
  type Clip,
  type ClipSlot,
  type ClipVideo,
} from "../../api/clips";
import { parseAssetResponse as parseDirectorAssetResponse } from "../../api/assets";
import { parseShotResponse } from "../../api/shots";
import { projectDirectorSlots, projectDirectorTakes } from "./directorModel";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function slot(overrides: Partial<ClipSlot> = {}): ClipSlot {
  return {
    id: 9,
    clip_id: 33,
    slot_no: 1,
    asset_id: 101,
    asset_name_snapshot: "角色",
    asset_type_snapshot: "character",
    asset_deleted: false,
    enabled: true,
    image_source: "asset_current",
    image_url: "/media/asset-images/101",
    ...overrides,
  };
}

function video(overrides: Partial<ClipVideo> = {}): ClipVideo {
  return {
    id: 7,
    clip_id: 33,
    sha256: "a".repeat(64),
    seed: "1",
    requested_duration: 5,
    actual_duration: 5,
    is_current: true,
    media_url: "/media/clip-videos/7",
    created_at: "2026-09-04T00:00:00Z",
    ...overrides,
  };
}

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: 33,
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
    ...overrides,
  };
}

function expectProtocolError(operation: () => unknown, message: string): void {
  try {
    operation();
    throw new Error("expected a protocol error");
  } catch (error: unknown) {
    expect(error).toBeInstanceOf(ApiProtocolError);
    expect(error).toEqual(
      expect.objectContaining({
        code: "protocol_error",
        message: expect.stringContaining(message),
      }),
    );
  }
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Director REST success-body boundaries", () => {
  it("accepts legal media paths and preserves the maximum seed string", async () => {
    const maximumSeed = "9223372036854775807";
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        video({
          seed: maximumSeed,
          media_url: "/media/clip-videos/7",
        }),
      ]),
    );

    const videos = await listClipVideos(33);
    const projectedTake = projectDirectorTakes(videos)[0];
    const projectedAssetSlot = projectDirectorSlots({
      clip_id: 33,
      warnings: [],
      items: [slot()],
    }).slots[0];
    const projectedOverrideSlot = projectDirectorSlots({
      clip_id: 33,
      warnings: [],
      items: [
        slot({
          image_source: "override",
          image_url: "/media/slot-overrides/9",
        }),
      ],
    }).slots[0];

    expect(videos[0]?.seed).toBe(maximumSeed);
    expect(typeof videos[0]?.seed).toBe("string");
    expect(projectedTake?.mediaUrl).toBe("/media/clip-videos/7");
    expect(projectedAssetSlot?.imageUrl).toBe("/media/asset-images/101");
    expect(projectedOverrideSlot?.imageUrl).toBe("/media/slot-overrides/9");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects hostile slot URLs and mismatched sources before projection", () => {
    const hostileUrls = [
      "https://attacker.invalid/reference.png",
      "file:///C:/Windows/win.ini",
      "//attacker.invalid/reference.png",
      "\\\\attacker\\reference.png",
      "/media/asset-images/./101",
      "/media/asset-images/../101",
      "/media/asset-images/101?download=1",
      "/media/asset-images/101#fragment",
      "/media/slot-overrides/8",
    ];
    let mediaNodesConsumed = 0;

    for (const imageUrl of hostileUrls) {
      expectProtocolError(
        () => parseClipSlotResponse(slot({ image_url: imageUrl })),
        "ClipSlot.image_url",
      );
      expect(mediaNodesConsumed).toBe(0);
    }
    expectProtocolError(
      () =>
        parseClipSlotResponse(
          slot({ image_source: "override", image_url: "/media/asset-images/101" }),
        ),
      "ClipSlot.image_url",
    );
    expectProtocolError(
      () => parseClipSlotResponse(slot({ image_url: 101 as unknown as string })),
      "ClipSlot.image_url",
    );
    expect(mediaNodesConsumed).toBe(0);
  });

  it("rejects hostile video URLs, number seeds, and unauthorized debug fields", () => {
    const hostileUrls = [
      "https://attacker.invalid/video.mp4",
      "file:///C:/Windows/win.ini",
      "//attacker.invalid/video.mp4",
      "\\\\attacker\\video.mp4",
      "/media/clip-videos/./7",
      "/media/clip-videos/../7",
      "/media/clip-videos/7?download=1",
      "/media/clip-videos/7#fragment",
      "/media/clip-videos/8",
    ];

    for (const mediaUrl of hostileUrls) {
      expectProtocolError(
        () => parseClipVideoResponse(video({ media_url: mediaUrl })),
        "ClipVideo.media_url",
      );
    }
    expectProtocolError(
      () =>
        parseClipVideoResponse(
          video({ seed: 9223372036854775807 as unknown as string }),
        ),
      "ClipVideo.seed",
    );
    for (const seed of [
      "9223372036854775808",
      "-1",
      "1.0",
      "not-a-seed",
    ]) {
      expectProtocolError(
        () => parseClipVideoResponse(video({ seed })),
        "ClipVideo.seed",
      );
    }
    expectProtocolError(
      () =>
        parseClipVideoResponse({
          ...video(),
          input_hash: "must-not-be-public",
        }),
      "must not contain input_hash",
    );
  });

  it("rejects unsafe, string, boolean, and float IDs before a follow-up fetch", async () => {
    const hostileIds: unknown[] = [
      Number.MAX_SAFE_INTEGER + 1,
      "7",
      true,
      7.5,
    ];
    for (const id of hostileIds) {
      expectProtocolError(
        () => parseClipResponse(clip({ id: id as number })),
        "Clip.id",
      );
      expectProtocolError(
        () => parseClipSlotResponse(slot({ id: id as number })),
        "ClipSlot.id",
      );
      expectProtocolError(
        () => parseClipVideoResponse(video({ id: id as number })),
        "ClipVideo.id",
      );
    }

    expectProtocolError(
      () => parseDirectorAssetResponse({
        id: "1",
        project_id: 1,
        type: "character",
        name: "角色",
        description: "描述",
        source: "manual",
        revision: 1,
        created_at: "2026-09-04T00:00:00Z",
        updated_at: "2026-09-04T00:00:00Z",
      }),
      "Asset.id",
    );
    expectProtocolError(
      () => parseShotResponse({
        id: 1,
        episode_id: 1,
        order_index: 1.5,
        duration_est: 1,
        shot_type: "中景",
        camera: "固定",
        description: "描述",
        dialogue: "",
        asset_ids: [],
        status: "normal",
        revision: 1,
        created_at: "2026-09-04T00:00:00Z",
        updated_at: "2026-09-04T00:00:00Z",
      }),
      "Shot.order_index",
    );
    expectProtocolError(
      () => parseDirectorAssetResponse({}),
      "Asset response",
    );

    fetchMock.mockResolvedValueOnce(
      jsonResponse([video({ media_url: "https://attacker.invalid/video.mp4" })]),
    );
    let mediaNodesConsumed = 0;
    await expect(listClipVideos(33)).rejects.toEqual(
      expect.objectContaining({
        code: "protocol_error",
        message: expect.stringContaining("ClipVideo.media_url"),
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mediaNodesConsumed).toBe(0);

    expectProtocolError(
      () => listClipVideos(Number.MAX_SAFE_INTEGER + 1),
      "clipId",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
