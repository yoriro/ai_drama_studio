import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  listClipSlots,
  listClipVideos,
  parseClipSlotResponse,
  parseClipVideoResponse,
  type ClipSlot,
  type ClipVideo,
} from "../../api/clips";
import { projectDirectorSlots, projectDirectorTakes } from "./directorModel";
import { DirectorSlotMedia, DirectorTakeMedia } from "../../pages/DirectorPage";

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
    seed: "9223372036854775807",
    requested_duration: 5,
    actual_duration: 5,
    is_current: true,
    media_url: "/media/clip-videos/7",
    created_at: "2026-09-04T00:00:00Z",
    ...overrides,
  };
}

function renderSlotResponse(raw: unknown) {
  const parsed = parseClipSlotResponse(raw);
  const projected = projectDirectorSlots({
    clip_id: parsed.clip_id,
    items: [parsed],
    warnings: [],
  }).slots[0]!;
  if (projected.imageUrl === null) {
    throw new Error("expected a media URL after parsing");
  }
  return DirectorSlotMedia({
    alt: `槽位 ${projected.slotNo} 参考图`,
    className: "director-slot-image",
    imageUrl: projected.imageUrl,
  });
}

function renderVideoResponse(raw: unknown) {
  const parsed = parseClipVideoResponse(raw);
  const projected = projectDirectorTakes([parsed])[0]!;
  return DirectorTakeMedia({
    mediaUrl: projected.mediaUrl,
    onError: () => undefined,
  });
}

function expectProtocolError(operation: () => unknown, context: string): void {
  expect(operation).toThrowError(
    expect.objectContaining({
      code: "protocol_error",
      message: expect.stringContaining(context),
    }),
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Director production media consumption", () => {
  it("passes legal asset-current, override, and video URLs from REST through model to page consumers", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          clip_id: 33,
          items: [
            slot(),
            slot({
              id: 10,
              slot_no: 2,
              image_source: "override",
              image_url: "/media/slot-overrides/10",
            }),
          ],
          warnings: [],
        }),
      )
      .mockResolvedValueOnce(jsonResponse([video()]));

    const slotsResponse = await listClipSlots(33);
    const videos = await listClipVideos(33);
    const slots = projectDirectorSlots(slotsResponse).slots;
    const takes = projectDirectorTakes(videos);

    const assetCurrent = slots.find((item) => item.imageSource === "asset_current");
    const override = slots.find((item) => item.imageSource === "override");
    const take = takes[0];
    expect(assetCurrent?.imageUrl).toBe("/media/asset-images/101");
    expect(override?.imageUrl).toBe("/media/slot-overrides/10");
    expect(take?.mediaUrl).toBe("/media/clip-videos/7");

    const assetElement = DirectorSlotMedia({
      alt: "asset-current",
      className: "director-slot-image",
      imageUrl: assetCurrent!.imageUrl!,
    });
    const overrideElement = DirectorSlotMedia({
      alt: "override",
      className: "director-slot-image",
      imageUrl: override!.imageUrl!,
    });
    const videoElement = DirectorTakeMedia({
      mediaUrl: take!.mediaUrl,
      onError: () => undefined,
    });

    expect(assetElement).toEqual(
      expect.objectContaining({
        type: "img",
        props: expect.objectContaining({ src: "/media/asset-images/101" }),
      }),
    );
    expect(overrideElement).toEqual(
      expect.objectContaining({
        type: "img",
        props: expect.objectContaining({ src: "/media/slot-overrides/10" }),
      }),
    );
    expect(videoElement).toEqual(
      expect.objectContaining({
        type: "video",
        props: expect.objectContaining({ src: "/media/clip-videos/7" }),
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("rejects hostile slot media before the production consumer or any foreign fetch", () => {
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

    for (const imageUrl of hostileUrls) {
      let mediaElement: unknown = null;
      expectProtocolError(
        () => {
          mediaElement = renderSlotResponse(slot({ image_url: imageUrl }));
        },
        "ClipSlot.image_url",
      );
      expect(mediaElement).toBeNull();
    }
    expectProtocolError(
      () => {
        let mediaElement: unknown = null;
        try {
          mediaElement = renderSlotResponse(
            slot({
              image_source: "override",
              image_url: "/media/asset-images/101",
            }),
          );
        } finally {
          expect(mediaElement).toBeNull();
        }
      },
      "ClipSlot.image_url",
    );
    expectProtocolError(
      () => {
        let mediaElement: unknown = null;
        try {
          mediaElement = renderSlotResponse(
            slot({ image_url: 101 as unknown as string }),
          );
        } finally {
          expect(mediaElement).toBeNull();
        }
      },
      "ClipSlot.image_url",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects hostile video media before the production consumer or any foreign fetch", () => {
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
      let mediaElement: unknown = null;
      expectProtocolError(
        () => {
          mediaElement = renderVideoResponse(video({ media_url: mediaUrl }));
        },
        "ClipVideo.media_url",
      );
      expect(mediaElement).toBeNull();
    }
    for (const mediaUrl of [101, null, ["/media/clip-videos/7"]]) {
      let mediaElement: unknown = null;
      expectProtocolError(
        () => {
          mediaElement = renderVideoResponse(
            video({ media_url: mediaUrl as unknown as string }),
          );
        },
        "ClipVideo.media_url",
      );
      expect(mediaElement).toBeNull();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
