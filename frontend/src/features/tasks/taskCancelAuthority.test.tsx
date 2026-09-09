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
    progress: status === "done" || status === "canceled" ? 1 : 0.5,
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

class AuthoritySocket {
  static instances: AuthoritySocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    AuthoritySocket.instances.push(this);
  }

  open(): void {
    this.onopen?.({} as Event);
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
  AuthoritySocket.instances = [];
  vi.stubGlobal("WebSocket", AuthoritySocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("cancellation authority after a pre-cancel detail read", () => {
  it.each([
    [
      "canceled",
      makeTask(7, "canceled", {
        finished_at: "2026-09-09T00:00:04Z",
      }),
    ],
    [
      "running with cancel_requested_at",
      makeTask(7, "running", {
        cancel_requested_at: "2026-09-09T00:00:03Z",
        finished_at: null,
      }),
    ],
  ] as const)("applies the post-cancel authoritative %s detail", async (_name, authoritative) => {
    const fetchMock = vi.mocked(fetch);
    const preCancelDetail = deferred<Response>();
    const postCancelDetail = deferred<Response>();
    const queued = makeTask(7, "queued");
    let detailCalls = 0;
    let listValue = queued;

    fetchMock.mockImplementation((input, init) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([listValue]));
      }
      if (path === "/api/tasks/7") {
        detailCalls += 1;
        if (detailCalls === 1) {
          return preCancelDetail.promise;
        }
        if (detailCalls === 2) {
          return postCancelDetail.promise;
        }
        throw new Error("unexpected third detail request");
      }
      if (path === "/api/tasks/7/cancel") {
        expect(init?.method).toBe("POST");
        expect(init?.body).toBeUndefined();
        return Promise.resolve(responseJson(queued));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    AuthoritySocket.instances[0].open();
    await waitFor(() =>
      expect(within(cardFor(7)).getByRole("button", { name: "查看详情" })).toBeTruthy(),
    );

    fireEvent.click(within(cardFor(7)).getByRole("button", { name: "查看详情" }));
    await waitFor(() => expect(detailCalls).toBe(1));
    fireEvent.click(within(cardFor(7)).getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(
        within(cardFor(7)).getByRole("button", { name: "正在确认取消…" }),
      ).toBeTruthy(),
    );
    expect(detailCalls).toBe(1);

    preCancelDetail.resolve(responseJson(queued));
    await waitFor(() => expect(detailCalls).toBe(2));
    expect(
      within(cardFor(7)).getByRole("button", { name: "正在确认取消…" }),
    ).toBeTruthy();

    listValue = authoritative;
    postCancelDetail.resolve(responseJson(authoritative));
    await waitFor(() => {
      expect(
        within(cardFor(7)).getAllByText(authoritative.status),
      ).not.toHaveLength(0);
      expect(
        within(cardFor(7)).getByText(String(authoritative.progress)),
      ).toBeTruthy();
    });
    if (authoritative.finished_at !== null) {
      expect(
        within(cardFor(7)).getAllByText(formatTaskTime(authoritative.finished_at)),
      ).not.toHaveLength(0);
    }
    if (authoritative.cancel_requested_at !== null) {
      expect(
        within(cardFor(7)).getAllByText(
          formatTaskTime(authoritative.cancel_requested_at),
        ),
      ).not.toHaveLength(0);
      expect(
        within(cardFor(7)).getByRole("button", { name: "已请求取消" }),
      ).toBeTruthy();
      expect(
        within(cardFor(7)).getByText("已请求取消，等待任务停止"),
      ).toBeTruthy();
    } else {
      expect(within(cardFor(7)).queryByRole("button", { name: /取消/ })).toBeNull();
    }
    expect(detailCalls).toBe(2);
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/7/cancel",
      ),
    ).toHaveLength(1);
  });

  it("keeps the confirmation error visible when the post-cancel authority read fails", async () => {
    const fetchMock = vi.mocked(fetch);
    const preCancelDetail = deferred<Response>();
    const postCancelDetail = deferred<Response>();
    const queued = makeTask(8, "queued");
    let detailCalls = 0;

    fetchMock.mockImplementation((input, init) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([queued]));
      }
      if (path === "/api/tasks/8") {
        detailCalls += 1;
        return detailCalls === 1
          ? preCancelDetail.promise
          : postCancelDetail.promise;
      }
      if (path === "/api/tasks/8/cancel") {
        expect(init?.body).toBeUndefined();
        return Promise.resolve(responseJson(queued));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    AuthoritySocket.instances[0].open();
    await waitFor(() => expect(cardFor(8)).toBeTruthy());
    fireEvent.click(within(cardFor(8)).getByRole("button", { name: "查看详情" }));
    await waitFor(() => expect(detailCalls).toBe(1));
    fireEvent.click(within(cardFor(8)).getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(
        within(cardFor(8)).getByRole("button", { name: "正在确认取消…" }),
      ).toBeTruthy(),
    );

    preCancelDetail.resolve(responseJson(queued));
    await waitFor(() => expect(detailCalls).toBe(2));
    postCancelDetail.reject(new Error("取消后的权威详情读取失败"));
    await waitFor(() =>
      expect(screen.getAllByText("取消后的权威详情读取失败").length).toBeGreaterThan(0),
    );
    expect(detailCalls).toBe(2);
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/8/cancel",
      ),
    ).toHaveLength(1);
  });
});
