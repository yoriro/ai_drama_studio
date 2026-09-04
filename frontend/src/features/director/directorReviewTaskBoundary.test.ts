import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiProtocolError } from "../../api/client";
import {
  getTask,
  parseTaskEventResponse,
  type Task,
} from "../../api/tasks";
import { parseTaskEvent } from "../../api/ws";
import {
  createDirectorSync,
  type DirectorPageSnapshot,
  type DirectorTaskSocket,
} from "./directorSync";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function task(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 7,
    type: "gen_clip_video",
    target_id: 33,
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

function event(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    task_id: 7,
    type: "gen_clip_video",
    status: "done",
    progress: 1,
    message: "任务已完成",
    ...overrides,
  };
}

function snapshot(): DirectorPageSnapshot {
  return { assets: [], shots: [], clips: [] };
}

function validTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 71,
    type: "gen_clip_video",
    target_id: 999,
    request_id: null,
    status: "running",
    progress: 0.5,
    error_msg: null,
    heartbeat_at: "2026-09-04T00:00:01Z",
    cancel_requested_at: null,
    created_at: "2026-09-04T00:00:00Z",
    started_at: "2026-09-04T00:00:01Z",
    finished_at: null,
    ...overrides,
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

async function flushPromises(): Promise<void> {
  for (let index = 0; index < 12; index += 1) {
    await Promise.resolve();
  }
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

describe("Director Task REST/WS boundaries", () => {
  it("accepts a complete Task response without changing safe IDs or nullable fields", async () => {
    const maximumId = Number.MAX_SAFE_INTEGER;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        task({
          id: maximumId,
          target_id: maximumId,
          request_id: "request-7",
          progress: 0,
          error_msg: "",
          heartbeat_at: "2026-09-04T00:00:01Z",
          cancel_requested_at: null,
          started_at: null,
          finished_at: null,
        }),
      ),
    );

    const parsed = await getTask(maximumId);

    expect(parsed.id).toBe(maximumId);
    expect(parsed.target_id).toBe(maximumId);
    expect(parsed.request_id).toBe("request-7");
    expect(parsed.progress).toBe(0);
    expect(parsed.error_msg).toBe("");
    expect(parsed.started_at).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/tasks/${Number.MAX_SAFE_INTEGER}`,
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("rejects malformed Task details before exposing them to a caller", async () => {
    const invalidResponses: Array<[string, unknown]> = [
      ["null response", null],
      ["array response", []],
      ["unsafe id", task({ id: Number.MAX_SAFE_INTEGER + 1 })],
      ["string target id", task({ target_id: "33" })],
      ["unknown type", task({ type: "unknown_task" })],
      ["unknown status", task({ status: "unknown" })],
      ["wrong progress type", task({ progress: "0.5" })],
      ["out of range progress", task({ progress: 1.1 })],
      ["wrong error type", task({ error_msg: false })],
      ["wrong timestamp type", task({ created_at: 7 })],
    ];

    for (const [label, payload] of invalidResponses) {
      fetchMock.mockResolvedValueOnce(jsonResponse(payload));
      let caught: unknown;
      try {
        await getTask(9);
      } catch (error: unknown) {
        caught = error;
      }
      expect(caught, label).toBeInstanceOf(ApiProtocolError);
    }

    expect(fetchMock).toHaveBeenCalledTimes(invalidResponses.length);
  });

  it("rejects invalid WS JSON values before task detail lookup", () => {
    const invalidEvents: Array<[string, unknown]> = [
      ["null response", null],
      ["array response", []],
      ["path-shaped task id", event({ task_id: "../../system/health" })],
      ["unsafe task id", event({ task_id: Number.MAX_SAFE_INTEGER + 1 })],
      ["wrong type", event({ type: "unknown_task" })],
      ["wrong status", event({ status: "unknown" })],
      ["wrong progress", event({ progress: "0.5" })],
      ["out of range progress", event({ progress: -0.1 })],
      ["wrong message", event({ message: null })],
    ];

    for (const [label, payload] of invalidEvents) {
      expectProtocolError(
        () => parseTaskEvent(JSON.stringify(payload)),
        `Task ${label === "null response" || label === "array response" ? "event" : "event"}`,
      );
    }

    expectProtocolError(
      () => parseTaskEventResponse({ task_id: 7 }, 200),
      "invalid field set",
    );
  });

  it("closes the Director socket and exposes a path-shaped task error before getTask", async () => {
    const socket = new FakeSocket();
    const readTask = vi.fn(async () => validTask());
    const states = [] as ReturnType<ReturnType<typeof createDirectorSync>["getState"]>[];
    const controller = createDirectorSync({
      readPageSnapshot: async () => snapshot(),
      readTask,
      openSocket: () => socket,
    });
    const unsubscribe = controller.subscribe((state) => {
      states.push(state);
    });

    controller.start();
    socket.open();
    await flushPromises();
    socket.message(JSON.stringify(event({ task_id: "../../system/health" })));

    expect(readTask).not.toHaveBeenCalled();
    expect(socket.closed).toBe(true);
    expect(states.at(-1)?.pagePhase).toBe("error");
    expect(states.at(-1)?.error).toBeInstanceOf(ApiProtocolError);
    expect((states.at(-1)?.error as Error).message).toContain(
      "Task event.task_id",
    );

    unsubscribe();
    controller.dispose();
  });

  it("performs one detail lookup for a legal unknown task event", async () => {
    const socket = new FakeSocket();
    const readTask = vi.fn(async () => validTask());
    const controller = createDirectorSync({
      readPageSnapshot: async () => snapshot(),
      readTask,
      openSocket: () => socket,
    });

    controller.start();
    socket.open();
    await flushPromises();
    socket.message(JSON.stringify(event({ task_id: 71, status: "running", progress: 0.5 })));
    await flushPromises();

    expect(readTask).toHaveBeenCalledTimes(1);
    expect(readTask).toHaveBeenCalledWith(71);
    controller.dispose();
  });
});
