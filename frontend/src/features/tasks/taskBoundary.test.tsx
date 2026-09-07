// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { Task } from "../../api/tasks";
import { TasksPage } from "../../pages/TasksPage";

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
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
}

function makeTask(
  id: number,
  status: Task["status"],
  overrides: Partial<Task> = {},
): Task {
  return {
    id,
    type: "gen_assets",
    target_id: 7,
    request_id: null,
    status,
    progress: status === "done" ? 1 : 0.5,
    error_msg: null,
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: "2026-09-07T00:00:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function makeEvent(
  taskId: unknown,
  overrides: Record<string, unknown> = {},
): string {
  return JSON.stringify({
    task_id: taskId,
    type: "gen_assets",
    status: "running",
    progress: 0.5,
    message: "观察到任务事件",
    ...overrides,
  });
}

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestPath(input: RequestInfo | URL): string {
  const url = new URL(String(input), "http://localhost");
  return url.pathname + url.search;
}

class BoundarySocket {
  static instances: BoundarySocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    BoundarySocket.instances.push(this);
  }

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

function mountTasks() {
  return render(
    <MemoryRouter initialEntries={["/tasks"]}>
      <TasksPage />
    </MemoryRouter>,
  );
}

function installListResponse(payload: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation((input) => {
    const path = requestPath(input);
    if (path === "/api/tasks?limit=50") {
      return Promise.resolve(responseJson(payload));
    }
    throw new Error(`unexpected request ${path}`);
  });
  return fetchMock;
}

beforeEach(() => {
  BoundarySocket.instances = [];
  vi.stubGlobal("WebSocket", BoundarySocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("TasksPage task public boundary", () => {
  it("expands one formal detail, preserves nulls and long error text, and does not expose payload", async () => {
    const fetchMock = vi.mocked(fetch);
    const detail = deferred<Response>();
    const summary = makeTask(7, "running");
    const fullDetail = makeTask(7, "failed", {
      request_id: "request-7-long",
      progress: 0.375,
      error_msg: "line one\nline two\nline three with full context",
      heartbeat_at: null,
      cancel_requested_at: "2026-09-07T01:02:03Z",
      created_at: "2026-09-07T00:00:00Z",
      started_at: null,
      finished_at: "2026-09-07T01:02:04Z",
    });
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([summary]));
      }
      if (path === "/api/tasks/7") {
        return detail.promise;
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = BoundarySocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "任务 #7" })).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/7",
        ),
      ).toHaveLength(1);
    });
    detail.resolve(responseJson(fullDetail));
    await waitFor(() => {
      expect(screen.getByText("request-7-long")).toBeTruthy();
      expect(
        screen.getByText(
          (_, element) =>
            element?.tagName === "PRE" &&
            element.textContent === fullDetail.error_msg,
        ),
      ).toBeTruthy();
    });
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("0.375")).toBeTruthy();
    expect(document.body.textContent).not.toContain("payload");

    fireEvent.click(screen.getByRole("button", { name: "收起详情" }));
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    await flushPromises();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/7",
      ),
    ).toHaveLength(1);
  });

  it.each([
    ["unknown status", { status: "unexpected" }, "Task.status has an unknown value"],
    ["out of range progress", { progress: 2 }, "Task.progress must be between 0 and 1"],
    ["unsafe id", { id: Number.MAX_SAFE_INTEGER + 1 }, "Task.id must be a positive JavaScript safe integer"],
    ["extra field", { payload: { secret: true } }, "Task response has an invalid field set"],
  ])("shows strict list parser failure for %s", async (_name, overrides, expected) => {
    const base = makeTask(1, "running");
    const payload = { ...base, ...overrides };
    const fetchMock = installListResponse([payload]);

    mountTasks();
    const socket = BoundarySocket.instances[0];
    socket.open();
    await waitFor(() => expect(screen.getByText(expected)).toBeTruthy());
    expect(socket.closed).toBe(true);
    expect(screen.queryByText("当前条件下暂无任务")).toBeNull();
    expect(fetchMock.mock.calls.filter(([input]) =>
      requestPath(input).includes("/api/tasks/") &&
      requestPath(input) !== "/api/tasks?limit=50",
    )).toHaveLength(0);
  });

  it("shows malformed JSON from the list as a protocol error instead of an empty list", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      if (requestPath(input) === "/api/tasks?limit=50") {
        return Promise.resolve(
          new Response("{not-json", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      throw new Error("unexpected request");
    });

    mountTasks();
    const socket = BoundarySocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(screen.getByText("API response was not valid JSON")).toBeTruthy(),
    );
    expect(socket.closed).toBe(true);
    expect(screen.queryByText("当前条件下暂无任务")).toBeNull();
  });

  it.each([
    [422, "validation_error", "输入不符合任务查询合同"],
    [500, "server_error", "任务服务暂时不可用"],
  ])("shows an API %s error without rendering empty state", async (status, code, message) => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      if (requestPath(input) === "/api/tasks?limit=50") {
        return Promise.resolve(
          responseJson({ detail: { code, message } }, status),
        );
      }
      throw new Error("unexpected request");
    });

    mountTasks();
    const socket = BoundarySocket.instances[0];
    socket.open();
    await waitFor(() => {
      expect(screen.getByText(message)).toBeTruthy();
      expect(screen.getByText(`code: ${code}`)).toBeTruthy();
    });
    expect(socket.closed).toBe(true);
    expect(screen.queryByText("当前条件下暂无任务")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["unknown status", makeEvent(91, { status: "unexpected" }), "Task event.status has an unknown value"],
    ["out of range progress", makeEvent(92, { progress: 2 }), "Task event.progress must be between 0 and 1"],
    ["unsafe id", makeEvent(Number.MAX_SAFE_INTEGER + 1), "Task event.task_id must be a positive JavaScript safe integer"],
    ["extra field", makeEvent(94, { payload: { debug: true } }), "Task event has an invalid field set"],
    ["malformed JSON", "{not-json", "Unexpected token"],
  ])("closes the socket and shows strict WS parser failure for %s", async (_name, event, expected) => {
    const fetchMock = installListResponse([makeTask(1, "running")]);
    mountTasks();
    const socket = BoundarySocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "任务 #1" })).toBeTruthy(),
    );
    socket.message(event);
    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert.textContent).toMatch(
        expected === "Unexpected token" ? /JSON|Unexpected token/ : new RegExp(expected),
      );
    });
    expect(socket.closed).toBe(true);
    expect(fetchMock.mock.calls.filter(([input]) =>
      requestPath(input) === "/api/tasks/91" ||
      requestPath(input) === "/api/tasks/92" ||
      requestPath(input) === "/api/tasks/94",
    )).toHaveLength(0);
  });

  it("keeps a WS protocol error until a later successful observation sync", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      if (requestPath(input) === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([makeTask(1, "running")]));
      }
      throw new Error("unexpected request");
    });

    mountTasks();
    const firstSocket = BoundarySocket.instances[0];
    firstSocket.open();
    await flushPromises();
    expect(screen.getByRole("heading", { name: "任务 #1" })).toBeTruthy();
    firstSocket.message(makeEvent(1, { status: "unexpected" }));
    await flushPromises();
    expect(screen.getByText("Task event.status has an unknown value")).toBeTruthy();
    await vi.advanceTimersByTimeAsync(1000);
    expect(BoundarySocket.instances).toHaveLength(2);
    const secondSocket = BoundarySocket.instances[1];
    secondSocket.open();
    await flushPromises();
    expect(screen.queryByText("Task event.status has an unknown value")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
