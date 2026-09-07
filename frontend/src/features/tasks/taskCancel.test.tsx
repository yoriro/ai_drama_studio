// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { Task } from "../../api/tasks";
import { TasksPage } from "../../pages/TasksPage";

function makeTask(
  id: number,
  status: Task["status"],
  overrides: Partial<Task> = {},
): Task {
  return {
    id,
    type: "gen_assets",
    target_id: id + 10,
    request_id: null,
    status,
    progress: status === "done" ? 1 : 0.4,
    error_msg: null,
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: "2026-09-07T00:00:00Z",
    started_at: status === "queued" ? null : "2026-09-07T00:00:01Z",
    finished_at:
      status === "done" || status === "failed" || status === "canceled"
        ? "2026-09-07T00:00:02Z"
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

class CancelSocket {
  static instances: CancelSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    CancelSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.({} as Event);
  }

  close(): void {
    this.onclose?.({} as CloseEvent);
  }
}

function mountTasks(): void {
  render(
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

beforeEach(() => {
  CancelSocket.instances = [];
  vi.stubGlobal("WebSocket", CancelSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TasksPage task cancellation", () => {
  it("cancels a queued task once, then confirms detail and list state", async () => {
    const fetchMock = vi.mocked(fetch);
    const detail = new Promise<Response>((resolve) => {
      setTimeout(() => resolve(responseJson(makeTask(1, "canceled"))), 0);
    });
    const queued = makeTask(1, "queued");
    const canceled = makeTask(1, "canceled");
    let listRead = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listRead += 1;
        return Promise.resolve(responseJson(listRead === 1 ? [queued] : [canceled]));
      }
      if (path === "/api/tasks/1/cancel") {
        return Promise.resolve(responseJson(canceled));
      }
      if (path === "/api/tasks/1") {
        return detail;
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = CancelSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(within(cardFor(1)).getByRole("button", { name: "取消任务" })).toBeTruthy(),
    );

    const cancelButton = within(cardFor(1)).getByRole("button", {
      name: "取消任务",
    });
    fireEvent.click(cancelButton);
    fireEvent.click(cancelButton);
    await waitFor(() => {
      const postingButton = within(cardFor(1)).getByRole("button", {
        name: "正在取消…",
      });
      expect(postingButton.hasAttribute("disabled")).toBe(true);
    });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/1/cancel",
        ),
      ).toHaveLength(1);
    });
    const cancelCall = fetchMock.mock.calls.find(([input]) =>
      requestPath(input) === "/api/tasks/1/cancel",
    );
    expect(cancelCall?.[1]).toMatchObject({ method: "POST" });
    expect((cancelCall?.[1] as RequestInit | undefined)?.body).toBeUndefined();

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/1",
        ),
      ).toHaveLength(1),
    );
    await waitFor(() =>
      expect(within(cardFor(1)).getByText("canceled")).toBeTruthy(),
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks?limit=50",
        ),
      ).toHaveLength(2),
    );
    expect(within(cardFor(1)).queryByRole("button", { name: "取消任务" })).toBeNull();
    expect(screen.queryByText("取消成功")).toBeNull();
  });

  it("keeps a running task running after a confirmed cancel request", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(2, "running");
    const requested = makeTask(2, "running", {
      cancel_requested_at: "2026-09-07T00:01:00Z",
    });
    let listRead = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listRead += 1;
        return Promise.resolve(responseJson(listRead === 1 ? [running] : [requested]));
      }
      if (path === "/api/tasks/2/cancel") {
        return Promise.resolve(responseJson(requested));
      }
      if (path === "/api/tasks/2") {
        return Promise.resolve(responseJson(requested));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = CancelSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(within(cardFor(2)).getByRole("button", { name: "取消任务" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(2)).getByRole("button", { name: "取消任务" }));

    await waitFor(() =>
      expect(
        within(cardFor(2))
          .getByRole("button", { name: "已请求取消" })
          .hasAttribute("disabled"),
      ).toBe(true),
    );
    expect(within(cardFor(2)).getByText("已请求取消，等待任务停止")).toBeTruthy();
    expect(within(cardFor(2)).getByText("running")).toBeTruthy();
    expect(within(cardFor(2)).getByText("40%")).toBeTruthy();
    expect(within(cardFor(2)).queryByText("canceled")).toBeNull();
    expect(screen.queryByText("取消成功")).toBeNull();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/2/cancel",
      ),
    ).toHaveLength(1);
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/2",
      ),
    ).toHaveLength(1);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks?limit=50",
        ),
      ).toHaveLength(2),
    );
  });

  it("isolates queued, already-requested, and terminal task controls", async () => {
    const fetchMock = vi.mocked(fetch);
    const post = new Promise<Response>(() => undefined);
    const queued = makeTask(1, "queued");
    const requested = makeTask(2, "running", {
      cancel_requested_at: "2026-09-07T00:01:00Z",
    });
    const done = makeTask(3, "done");
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([done, requested, queued]));
      }
      if (path === "/api/tasks/1/cancel") {
        return post;
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = CancelSocket.instances[0];
    socket.open();
    await waitFor(() => expect(cardFor(3)).toBeTruthy());

    const queuedCard = cardFor(1);
    const requestedCard = cardFor(2);
    const doneCard = cardFor(3);
    const queuedButton = within(queuedCard).getByRole("button", {
      name: "取消任务",
    });
    expect(queuedButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(queuedButton);
    fireEvent.click(queuedButton);
    expect(
      within(queuedCard)
        .getByRole("button", { name: "正在取消…" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(
      within(requestedCard)
        .getByRole("button", { name: "已请求取消" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(within(requestedCard).getByText("已请求取消，等待任务停止")).toBeTruthy();
    expect(within(doneCard).queryByRole("button", { name: /取消/ })).toBeNull();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/1/cancel",
        ),
      ).toHaveLength(1),
    );
    expect(
      fetchMock.mock.calls.some(([input]) =>
        requestPath(input) === "/api/tasks/2/cancel" ||
        requestPath(input) === "/api/tasks/3/cancel",
      ),
    ).toBe(false);
  });
});
