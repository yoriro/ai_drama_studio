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
    target_id: id + 100,
    request_id: null,
    status,
    progress: status === "done" ? 1 : 0.5,
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

function makeEvent(
  taskId: number,
  status: Task["status"],
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

class RacingSocket {
  static instances: RacingSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    RacingSocket.instances.push(this);
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

beforeEach(() => {
  RacingSocket.instances = [];
  vi.stubGlobal("WebSocket", RacingSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TasksPage cancellation races and identity", () => {
  it("keeps a terminal WS winner when a late POST returns running", async () => {
    const fetchMock = vi.mocked(fetch);
    const post = deferred<Response>();
    const running = makeTask(1, "running");
    const done = makeTask(1, "done");
    let listRead = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listRead += 1;
        return Promise.resolve(responseJson(listRead === 1 ? [running] : [done]));
      }
      if (path === "/api/tasks/1/cancel") {
        return post.promise;
      }
      if (path === "/api/tasks/1") {
        return Promise.resolve(responseJson(done));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = RacingSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(within(cardFor(1)).getByRole("button", { name: "取消任务" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(1)).getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/1/cancel",
        ),
      ).toHaveLength(1),
    );

    socket.message(makeEvent(1, "done", 1, "任务完成"));
    post.resolve(responseJson(running));
    await waitFor(() =>
      expect(within(cardFor(1)).getByText("done")).toBeTruthy(),
    );
    await flushPromises();
    expect(within(cardFor(1)).queryByText("running")).toBeNull();
    expect(screen.queryByText("取消成功")).toBeNull();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/1/cancel",
      ),
    ).toHaveLength(1);
  });

  it("keeps a 409 message while authoritative reads show the done winner", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(2, "running");
    const done = makeTask(2, "done");
    let listRead = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listRead += 1;
        return Promise.resolve(responseJson(listRead === 1 ? [running] : [done]));
      }
      if (path === "/api/tasks/2/cancel") {
        return Promise.resolve(
          responseJson(
            { detail: { code: "task_conflict", message: "任务已完成，不能取消" } },
            409,
          ),
        );
      }
      if (path === "/api/tasks/2") {
        return Promise.resolve(responseJson(done));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = RacingSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(within(cardFor(2)).getByRole("button", { name: "取消任务" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(2)).getByRole("button", { name: "取消任务" }));

    await waitFor(() => {
      expect(within(cardFor(2)).getByText("任务已完成，不能取消")).toBeTruthy();
      expect(within(cardFor(2)).getByText("done")).toBeTruthy();
    });
    expect(within(cardFor(2)).queryByRole("button", { name: /取消/ })).toBeNull();
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

  it("keeps a 404 message at list level and clears vanished task detail", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(3, "running", { request_id: "request-3" });
    let listRead = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listRead += 1;
        return Promise.resolve(responseJson(listRead === 1 ? [running] : []));
      }
      if (path === "/api/tasks/3/cancel") {
        return Promise.resolve(
          responseJson({ detail: { code: "not_found", message: "任务已被删除" } }, 404),
        );
      }
      if (path === "/api/tasks/3") {
        return Promise.resolve(responseJson(running));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = RacingSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(within(cardFor(3)).getByRole("button", { name: "查看详情" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(3)).getByRole("button", { name: "查看详情" }));
    await waitFor(() => expect(screen.getByText("request-3")).toBeTruthy());
    fireEvent.click(within(cardFor(3)).getByRole("button", { name: "取消任务" }));

    await waitFor(() =>
      expect(screen.getByText("任务已被删除")).toBeTruthy(),
    );
    await waitFor(() =>
      expect(screen.getByText("任务 #3：取消操作")).toBeTruthy(),
    );
    expect(screen.queryByRole("heading", { name: "任务 #3" })).toBeNull();
    expect(screen.queryByText("request-3")).toBeNull();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/3/cancel",
      ),
    ).toHaveLength(1);
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks?limit=50",
      ),
    ).toHaveLength(2);
  });

  it("keeps network cancellation unknown until one detail read and never reposts", async () => {
    const fetchMock = vi.mocked(fetch);
    const detail = deferred<Response>();
    const running = makeTask(4, "running");
    const requested = makeTask(4, "running", {
      cancel_requested_at: "2026-09-07T00:01:00Z",
    });
    let listRead = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listRead += 1;
        return Promise.resolve(responseJson(listRead === 1 ? [running] : [requested]));
      }
      if (path === "/api/tasks/4/cancel") {
        return Promise.reject(new Error("network timeout"));
      }
      if (path === "/api/tasks/4") {
        return detail.promise;
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = RacingSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(within(cardFor(4)).getByRole("button", { name: "取消任务" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(4)).getByRole("button", { name: "取消任务" }));

    await waitFor(() => {
      expect(within(cardFor(4)).getByText("network timeout")).toBeTruthy();
      expect(
        within(cardFor(4)).getByText("取消结果未确认，正在读取最新任务状态"),
      ).toBeTruthy();
    });
    expect(
      within(cardFor(4))
        .getByRole("button", { name: "取消结果未确认" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/4/cancel",
      ),
    ).toHaveLength(1);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/4",
        ),
      ).toHaveLength(1),
    );

    detail.resolve(responseJson(requested));
    await waitFor(() =>
      expect(within(cardFor(4)).getByText("已请求取消，等待任务停止")).toBeTruthy(),
    );
    expect(within(cardFor(4)).getByText("network timeout")).toBeTruthy();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/4/cancel",
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

  it("isolates a late A cancellation from filter B and expanded B detail", async () => {
    const fetchMock = vi.mocked(fetch);
    const post = deferred<Response>();
    const taskA = makeTask(10, "queued");
    const taskB = makeTask(20, "running", { request_id: "request-20" });
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([taskB, taskA]));
      }
      if (path === "/api/tasks?status=running&limit=50") {
        return Promise.resolve(responseJson([taskB]));
      }
      if (path === "/api/tasks/10/cancel") {
        return post.promise;
      }
      if (path === "/api/tasks/20") {
        return Promise.resolve(responseJson(taskB));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const firstSocket = RacingSocket.instances[0];
    firstSocket.open();
    await waitFor(() =>
      expect(within(cardFor(10)).getByRole("button", { name: "取消任务" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(10)).getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/10/cancel",
        ),
      ).toHaveLength(1),
    );

    fireEvent.change(screen.getByRole("combobox", { name: "状态筛选" }), {
      target: { value: "running" },
    });
    await waitFor(() => expect(RacingSocket.instances).toHaveLength(2));
    RacingSocket.instances[1].open();
    await waitFor(() =>
      expect(within(cardFor(20)).getByRole("button", { name: "查看详情" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(20)).getByRole("button", { name: "查看详情" }));
    await waitFor(() => expect(screen.getByText("request-20")).toBeTruthy());

    post.resolve(responseJson(makeTask(10, "canceled")));
    await flushPromises();
    expect(screen.queryByRole("heading", { name: "任务 #10" })).toBeNull();
    expect(within(cardFor(20)).getByText("request-20")).toBeTruthy();
    expect(screen.queryByText("任务已被删除")).toBeNull();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        requestPath(input) === "/api/tasks/10",
      ),
    ).toBe(false);
  });

  it("does not let an unmounted page consume a late cancellation response", async () => {
    const fetchMock = vi.mocked(fetch);
    const post = deferred<Response>();
    const task = makeTask(30, "queued");
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([task]));
      }
      if (path === "/api/tasks/30/cancel") {
        return post.promise;
      }
      if (path === "/api/tasks/30") {
        return Promise.resolve(responseJson(task));
      }
      throw new Error(`unexpected request ${path}`);
    });

    const mounted = mountTasks();
    const socket = RacingSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(within(cardFor(30)).getByRole("button", { name: "取消任务" })).toBeTruthy(),
    );
    fireEvent.click(within(cardFor(30)).getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/30/cancel",
        ),
      ).toHaveLength(1),
    );
    mounted.unmount();
    post.resolve(responseJson(makeTask(30, "canceled")));
    await flushPromises();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        requestPath(input) === "/api/tasks/30",
      ),
    ).toBe(false);
  });
});
