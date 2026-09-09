// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    progress: 0.5,
    error_msg: null,
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: "2026-09-09T00:00:00Z",
    started_at: "2026-09-09T00:00:01Z",
    finished_at: null,
    ...overrides,
  };
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

function cancelIntentEvent(taskId: number): string {
  return JSON.stringify({
    task_id: taskId,
    type: "gen_assets",
    status: "running",
    progress: 0.5,
    message: "已请求取消",
  });
}

class CancelIntentSocket {
  static instances: CancelIntentSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    CancelIntentSocket.instances.push(this);
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
  CancelIntentSocket.instances = [];
  vi.stubGlobal("WebSocket", CancelIntentSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("remote cancellation intent observation", () => {
  it("reads one latest detail for a known running task and deduplicates the event", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(21, "running");
    const requested = makeTask(21, "running", {
      cancel_requested_at: "2026-09-09T00:00:03Z",
    });
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([running]));
      }
      if (path === "/api/tasks/21") {
        detailCalls += 1;
        return Promise.resolve(responseJson(requested));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = CancelIntentSocket.instances[0];
    socket.open();
    await waitFor(() => expect(cardFor(21)).toBeTruthy());

    socket.message(cancelIntentEvent(21));
    socket.message(cancelIntentEvent(21));
    await waitFor(() => expect(detailCalls).toBe(1));
    await waitFor(() =>
      expect(
        within(cardFor(21)).getByRole("button", { name: "已请求取消" }),
      ).toBeTruthy(),
    );

    const card = cardFor(21);
    expect(within(card).getAllByText("running")).not.toHaveLength(0);
    expect(within(card).getByText("50%")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "查看详情" }));
    await waitFor(() =>
      expect(
        within(cardFor(21)).getAllByText(
          formatTaskTime(requested.cancel_requested_at!),
        ),
      ).not.toHaveLength(0),
    );
    expect(
      within(cardFor(21))
        .getByRole("button", { name: "已请求取消" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(within(cardFor(21)).queryByRole("button", { name: "取消任务" })).toBeNull();
    expect(detailCalls).toBe(1);
  });

  it("waits for an old detail read, then performs one follow-up read", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(22, "running");
    const requested = makeTask(22, "running", {
      cancel_requested_at: "2026-09-09T00:00:04Z",
    });
    const oldDetail = deferred<Response>();
    const followUpDetail = deferred<Response>();
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([running]));
      }
      if (path === "/api/tasks/22") {
        detailCalls += 1;
        if (detailCalls === 1) {
          return oldDetail.promise;
        }
        if (detailCalls === 2) {
          return followUpDetail.promise;
        }
        throw new Error("unexpected third detail request");
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = CancelIntentSocket.instances[0];
    socket.open();
    await waitFor(() => expect(cardFor(22)).toBeTruthy());
    fireEvent.click(within(cardFor(22)).getByRole("button", { name: "查看详情" }));
    await waitFor(() => expect(detailCalls).toBe(1));

    socket.message(cancelIntentEvent(22));
    socket.message(cancelIntentEvent(22));
    await waitFor(() =>
      expect(
        within(cardFor(22)).getByRole("button", { name: "正在确认取消…" }),
      ).toBeTruthy(),
    );
    expect(detailCalls).toBe(1);

    oldDetail.resolve(responseJson(running));
    await waitFor(() => expect(detailCalls).toBe(2));
    expect(detailCalls).toBe(2);
    followUpDetail.resolve(responseJson(requested));
    await waitFor(() =>
      expect(
        within(cardFor(22)).getAllByText(
          formatTaskTime(requested.cancel_requested_at!),
        ),
      ).not.toHaveLength(0),
    );
    expect(
      within(cardFor(22))
        .getByRole("button", { name: "已请求取消" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(within(cardFor(22)).queryByRole("button", { name: "取消任务" })).toBeNull();
    expect(detailCalls).toBe(2);
  });

  it("keeps the running task locked and exposes a latest-detail failure", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(23, "running");
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([running]));
      }
      if (path === "/api/tasks/23") {
        detailCalls += 1;
        return Promise.reject(new Error("远端取消详情读取失败"));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = CancelIntentSocket.instances[0];
    socket.open();
    await waitFor(() => expect(cardFor(23)).toBeTruthy());
    socket.message(cancelIntentEvent(23));
    await waitFor(() => expect(screen.getByText("远端取消详情读取失败")).toBeTruthy());

    expect(detailCalls).toBe(1);
    expect(within(cardFor(23)).getByText("running")).toBeTruthy();
    expect(
      within(cardFor(23))
        .getByRole("button", { name: "正在确认取消…" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(within(cardFor(23)).queryByRole("button", { name: "取消任务" })).toBeNull();
  });
});
