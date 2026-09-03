import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearClipSlotOverride,
  createClip,
  deleteClip,
  deleteClipVideo,
  generateClipVideo,
  getClip,
  listClipSlots,
  listClipVideos,
  listClips,
  previewClips,
  setCurrentClipVideo,
  updateClip,
  updateClipSlotEnabled,
  uploadClipSlotOverride,
} from "./clips";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function emptyResponse(status: number): Response {
  return new Response(null, { status });
}

function requestInit(): RequestInit {
  const call = fetchMock.mock.calls.at(-1);
  if (call === undefined) {
    throw new Error("fetch was not called");
  }
  return call[1] ?? {};
}

function requestHeaders(init: RequestInit): Headers {
  return new Headers(init.headers);
}

function requestBody(init: RequestInit): Record<string, unknown> {
  if (typeof init.body !== "string") {
    throw new Error("request body was not JSON");
  }
  return JSON.parse(init.body) as Record<string, unknown>;
}

describe("Director clip API requests", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists clips with the episode GET path", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    await listClips(12);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/episodes/12/clips");
    const init = requestInit();
    expect(init.method).toBeUndefined();
    expect(requestHeaders(init).get("Accept")).toBe("application/json");
  });

  it("previews the exact selected shot body", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));

    await previewClips(12, { shot_ids: [9, 4] });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/episodes/12/clips/preview",
    );
    const init = requestInit();
    expect(init.method).toBe("POST");
    expect(requestBody(init)).toEqual({ shot_ids: [9, 4] });
    expect(requestHeaders(init).get("Content-Type")).toBe("application/json");
  });

  it("creates a clip with only the supplied public fields", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));
    const input = {
      shot_ids: [1, 2],
      reference_asset_ids: [8, 5],
      requested_duration: 7,
      user_note: "  keep spaces  ",
    };

    await createClip(12, input);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/episodes/12/clips");
    const init = requestInit();
    expect(init.method).toBe("POST");
    expect(requestBody(init)).toEqual(input);
  });

  it("gets and patches a clip with exact methods and bodies", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}));

    await getClip(33);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/clips/33");
    expect(requestInit().method).toBeUndefined();

    await updateClip(33, { user_note: null, requested_duration: 11 });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/clips/33");
    const init = requestInit();
    expect(init.method).toBe("PATCH");
    expect(requestBody(init)).toEqual({
      user_note: null,
      requested_duration: 11,
    });
  });

  it("deletes a clip through the strict no-content helper", async () => {
    fetchMock.mockResolvedValueOnce(emptyResponse(204));

    await deleteClip(33);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/clips/33");
    expect(requestInit().method).toBe("DELETE");
  });

  it("reads slots and sends one enabled JSON mutation", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}));

    await listClipSlots(33);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/clips/33/slots");

    await updateClipSlotEnabled(33, 2, false);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/clips/33/slots/2");
    const init = requestInit();
    expect(init.method).toBe("PATCH");
    expect(requestBody(init)).toEqual({ enabled: false });
    expect(requestHeaders(init).get("Content-Type")).toBe("application/json");
  });

  it("uploads one FormData file without setting multipart headers", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));
    const file = new File(["png-bytes"], "reference.png", {
      type: "image/png",
    });

    await uploadClipSlotOverride(33, 2, file);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/clips/33/slots/2");
    const init = requestInit();
    expect(init.method).toBe("PATCH");
    expect(requestHeaders(init).get("Content-Type")).toBeNull();
    expect(init.body).toBeInstanceOf(FormData);
    const formData = init.body as FormData;
    expect(Array.from(formData.keys())).toEqual(["file"]);
    expect(formData.get("file")).toBe(file);
  });

  it("clears a slot override with the formal multipart field", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));

    await clearClipSlotOverride(33, 2);

    const init = requestInit();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/clips/33/slots/2");
    expect(init.method).toBe("PATCH");
    expect(requestHeaders(init).get("Content-Type")).toBeNull();
    expect(init.body).toBeInstanceOf(FormData);
    const formData = init.body as FormData;
    expect(Array.from(formData.keys())).toEqual(["clear_override"]);
    expect(formData.get("clear_override")).toBe("true");
  });

  it("generates video with an empty body and validates the task response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ task_id: 41 }, 202));

    await expect(generateClipVideo(33)).resolves.toEqual({ task_id: 41 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/clips/33/generate-video",
    );
    const init = requestInit();
    expect(init.method).toBe("POST");
    expect(requestBody(init)).toEqual({});
    expect(requestBody(init)).not.toHaveProperty("request_id");
  });

  it("preserves an explicitly supplied note including null and empty string", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ task_id: 42 }, 202))
      .mockResolvedValueOnce(jsonResponse({ task_id: 43 }, 202));

    await generateClipVideo(33, { user_note: "  exact  " });
    expect(requestBody(requestInit())).toEqual({ user_note: "  exact  " });

    await generateClipVideo(33, { user_note: null });
    expect(requestBody(requestInit())).toEqual({ user_note: null });
  });

  it("keeps video seed as a string and preserves optional debug fields", async () => {
    const video = {
      id: 7,
      clip_id: 33,
      sha256: "hash",
      seed: "9007199254740993",
      requested_duration: 5,
      actual_duration: null,
      is_current: true,
      media_url: "/media/clip-videos/7",
      created_at: "2026-09-03T00:00:00Z",
      built_prompt: "prompt",
      input_snapshot: { seed: "9007199254740993" },
    };
    fetchMock.mockResolvedValueOnce(jsonResponse([video]));

    await expect(listClipVideos(33)).resolves.toEqual([video]);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/clips/33/videos");
    expect((video.seed satisfies string)).toBe("9007199254740993");
  });

  it("sets current video with the exact public body", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));

    await setCurrentClipVideo(33, 7);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/clips/33/current-video",
    );
    const init = requestInit();
    expect(init.method).toBe("PUT");
    expect(requestBody(init)).toEqual({ video_id: 7 });
  });

  it("deletes a clip video through the strict no-content helper", async () => {
    fetchMock.mockResolvedValueOnce(emptyResponse(204));

    await deleteClipVideo(7);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/clip-videos/7");
    expect(requestInit().method).toBe("DELETE");
  });

  it("surfaces structured 409 and 422 API errors verbatim", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: { code: "conflict", message: "当前 take 不能删除" } },
          409,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: { code: "validation_error", message: "时长必须是整数" } },
          422,
        ),
      );

    await expect(deleteClip(33)).rejects.toEqual(
      expect.objectContaining({
        status: 409,
        code: "conflict",
        message: "当前 take 不能删除",
      }),
    );
    await expect(updateClip(33, { requested_duration: 3.5 })).rejects.toEqual(
      expect.objectContaining({
        status: 422,
        code: "validation_error",
        message: "时长必须是整数",
      }),
    );
  });

  it("surfaces non-JSON responses and 204 drift as protocol errors", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("upstream failure", { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 200 }));

    await expect(listClips(12)).rejects.toEqual(
      expect.objectContaining({
        status: 500,
        code: "protocol_error",
        message: "API response was not valid JSON",
      }),
    );
    await expect(deleteClipVideo(7)).rejects.toEqual(
      expect.objectContaining({
        status: 200,
        code: "protocol_error",
        message: "Expected a 204 response",
      }),
    );
  });
});
