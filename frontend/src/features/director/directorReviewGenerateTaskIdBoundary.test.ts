import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProtocolError } from "../../api/client";
import { generateClipVideo } from "../../api/clips";
import { createDirectorGenerationRequester } from "./directorSync";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 202): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Director generate-video task_id boundary", () => {
  it("tracks the maximum safe task id once through the production submit seam", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ task_id: Number.MAX_SAFE_INTEGER }),
    );
    const requester = createDirectorGenerationRequester(generateClipVideo);
    const trackTask = vi.fn();
    const generationTaskIds: number[] = [];
    const refresh = vi.fn();

    const pending = requester.submit(33, {});
    expect(pending).not.toBeNull();
    await pending!.then(({ task_id }) => {
      trackTask(task_id);
      generationTaskIds.push(task_id);
      refresh();
    });

    expect(trackTask).toHaveBeenCalledTimes(1);
    expect(trackTask).toHaveBeenCalledWith(Number.MAX_SAFE_INTEGER);
    expect(generationTaskIds).toEqual([Number.MAX_SAFE_INTEGER]);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["unsafe number", Number.MAX_SAFE_INTEGER + 1],
    ["string path", "../../tasks/41"],
    ["boolean", true],
    ["float", 41.5],
    ["null", null],
    ["array", []],
  ])(
    "rejects %s before Director task state or follow-up reads are touched",
    async (_label, taskId) => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ task_id: taskId }));
      const requester = createDirectorGenerationRequester(generateClipVideo);
      const trackTask = vi.fn();
      const generationTaskIds: number[] = [];
      const taskDetailGet = vi.fn();
      const refresh = vi.fn();

      const pending = requester.submit(33, {});
      expect(pending).not.toBeNull();
      await expect(pending!).rejects.toEqual(
        expect.objectContaining({
          code: "protocol_error",
          status: 202,
        }),
      );
      await expect(pending!).rejects.toBeInstanceOf(ApiProtocolError);

      expect(trackTask).not.toHaveBeenCalled();
      expect(generationTaskIds).toEqual([]);
      expect(taskDetailGet).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );
});
