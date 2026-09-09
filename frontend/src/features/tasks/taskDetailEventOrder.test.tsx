// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { Task, TaskEvent } from "../../api/tasks";
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

function makeTask(
  id: number,
  status: Task["status"],
  overrides: Partial<Task> = {},
): Task {
  return {
    id,
    type: "gen_assets",
    target_id: id + 100,
    request_id: null,
    status,
    progress: status === "done" ? 1 : 0.5,
    error_msg: null,
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: "2026-09-09T00:00:00Z",
    started_at: status === "queued" ? null : "2026-09-09T00:00:01Z",
    finished_at:
      status === "done" || status === "failed" || status === "canceled"
        ? "2026-09-09T00:00:02Z"
        : null,
    ...overrides,
  };
}

function makeEvent(
  taskId: number,
  status: TaskEvent["status"],
  progress: number,
  message: string,
): string {
  return JSON.stringify({
    task_id: taskId,
    type: "gen_assets",
    status,
    progress,
    message,
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

class EventOrderSocket {
  static instances: EventOrderSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    EventOrderSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.({} as Event);
  }

  message(data: string): void {
    this.onmessage?.({ data } as MessageEvent);
  }

  close(): void {
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

function cardFor(taskId: number): HTMLElement {
  const heading = screen.getByRole("heading", { name: `任务 #${taskId}` });
  const card = heading.closest("article");
  if (card === null) {
    throw new Error(`task card ${taskId} was not rendered`);
  }
  return card;
}

function formatTaskTime(value: string): string {
  return new Date(value).toLocaleString(undefined, { timeZoneName: "short" });
}

beforeEach(() => {
  EventOrderSocket.instances = [];
  vi.stubGlobal("WebSocket", EventOrderSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("task detail event ordering", () => {
  it("does not let a cached running event overwrite a later REST done detail", async () => {
    const fetchMock = vi.mocked(fetch);
    const detail = deferred<Response>();
    const running = makeTask(11, "running");
    const done = makeTask(11, "done", {
      progress: 1,
      finished_at: "2026-09-09T00:00:04Z",
    });
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([running]));
      }
      if (path === "/api/tasks/11") {
        return detail.promise;
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = EventOrderSocket.instances[0];
    socket.open();
    await waitFor(() => expect(cardFor(11)).toBeTruthy());
    socket.message(makeEvent(11, "running", 0.7, "进度更新"));
    fireEvent.click(within(cardFor(11)).getByRole("button", { name: "查看详情" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/11",
        ),
      ).toHaveLength(1),
    );

    detail.resolve(responseJson(done));
    await waitFor(() => {
      expect(within(cardFor(11)).getAllByText("done")).not.toHaveLength(0);
      expect(within(cardFor(11)).getByText("1")).toBeTruthy();
      expect(
        within(cardFor(11)).getAllByText(formatTaskTime(done.finished_at!)),
      ).not.toHaveLength(0);
    });
    expect(within(cardFor(11)).queryByText("0.7")).toBeNull();
  });

  it("keeps a terminal event when an older detail request returns late", async () => {
    const fetchMock = vi.mocked(fetch);
    const oldDetail = deferred<Response>();
    const running = makeTask(12, "running");
    const done = makeTask(12, "done", {
      progress: 1,
      finished_at: "2026-09-09T00:00:05Z",
    });
    let listValue = running;
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([listValue]));
      }
      if (path === "/api/tasks/12") {
        detailCalls += 1;
        return detailCalls === 1
          ? oldDetail.promise
          : Promise.resolve(responseJson(done));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = EventOrderSocket.instances[0];
    socket.open();
    await waitFor(() => expect(cardFor(12)).toBeTruthy());
    fireEvent.click(within(cardFor(12)).getByRole("button", { name: "查看详情" }));
    await waitFor(() => expect(detailCalls).toBe(1));

    listValue = done;
    socket.message(makeEvent(12, "done", 1, "任务完成"));
    oldDetail.resolve(responseJson(running));
    await waitFor(() => {
      expect(within(cardFor(12)).getAllByText("done")).not.toHaveLength(0);
      expect(within(cardFor(12)).getByText("1")).toBeTruthy();
    });
    await waitFor(() => expect(detailCalls).toBe(2));
    expect(
      within(cardFor(12)).getAllByText(formatTaskTime(done.finished_at!)),
    ).not.toHaveLength(0);
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/12/cancel",
      ),
    ).toHaveLength(0);
  });
});
