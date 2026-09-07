// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    target_id: 1,
    request_id: null,
    status,
    progress: status === "done" ? 1 : 0.5,
    error_msg: status === "failed" ? "server failure" : null,
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
  status: TaskEvent["status"],
  overrides: Partial<TaskEvent> = {},
): TaskEvent {
  return {
    task_id: taskId,
    type: "gen_assets",
    status,
    progress: status === "done" ? 1 : 0.5,
    message: status === "failed" ? "任务失败：server failure" : "状态已更新",
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
  return new URL(String(input), "http://localhost").pathname +
    new URL(String(input), "http://localhost").search;
}

class FakeSocket {
  static instances: FakeSocket[] = [];

  readonly url: string;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.({} as Event);
  }

  message(event: TaskEvent | string): void {
    this.onmessage?.({
      data: typeof event === "string" ? event : JSON.stringify(event),
    } as MessageEvent);
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

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("TasksPage task observation", () => {
  it("opens the socket first, buffers events, deduplicates unknown detail, and replaces terminal state", async () => {
    const fetchMock = vi.mocked(fetch);
    const initial = deferred<Response>();
    const detailUnknown = deferred<Response>();
    const detailTerminal = deferred<Response>();
    let serverTasks = [makeTask(10, "running")];
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50" && fetchMock.mock.calls.length === 1) {
        return initial.promise;
      }
      if (path === "/api/tasks/41") {
        return detailUnknown.promise;
      }
      if (path === "/api/tasks/10") {
        return detailTerminal.promise;
      }
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson(serverTasks));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    expect(FakeSocket.instances).toHaveLength(1);
    expect(fetchMock).not.toHaveBeenCalled();
    const socket = FakeSocket.instances[0];
    socket.open();
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestPath(fetchMock.mock.calls[0][0])).toBe(
      "/api/tasks?limit=50",
    );

    socket.message(makeEvent(41, "done"));
    socket.message(makeEvent(41, "done"));
    initial.resolve(responseJson(serverTasks));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "任务 #10" })).toBeTruthy();
      expect(fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/41",
      )).toHaveLength(1);
    });

    socket.message(makeEvent(10, "done"));
    socket.message(makeEvent(10, "done"));
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/10",
      )).toHaveLength(1);
    });

    const terminalTask = makeTask(10, "done");
    const unknownTask = makeTask(41, "done");
    serverTasks = [unknownTask, terminalTask];
    detailTerminal.resolve(responseJson(terminalTask));
    detailUnknown.resolve(responseJson(unknownTask));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "历史" })).toBeTruthy();
      expect(screen.getByRole("heading", { name: "任务 #41" })).toBeTruthy();
      expect(screen.getByRole("heading", { name: "任务 #10" })).toBeTruthy();
    });
    expect(screen.queryByText("进行中")).toBeNull();
    expect(
      screen.getByText(/最多显示匹配条件的最近 50 条，本次已加载 2 条/),
    ).toBeTruthy();
  });

  it("drops an old filter request and old socket events when filter B becomes current", async () => {
    const fetchMock = vi.mocked(fetch);
    const oldList = deferred<Response>();
    const newList = deferred<Response>();
    fetchMock
      .mockReturnValueOnce(oldList.promise)
      .mockReturnValueOnce(newList.promise);

    mountTasks();
    const firstSocket = FakeSocket.instances[0];
    firstSocket.open();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("状态筛选"), {
      target: { value: "failed" },
    });
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(2));
    const secondSocket = FakeSocket.instances[1];
    secondSocket.open();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(requestPath(fetchMock.mock.calls[1][0])).toBe(
      "/api/tasks?status=failed&limit=50",
    );

    firstSocket.message(makeEvent(99, "done"));
    oldList.resolve(responseJson([makeTask(1, "running")]));
    newList.resolve(responseJson([makeTask(2, "failed")]));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "任务 #2" })).toBeTruthy();
      expect(screen.queryByRole("heading", { name: "任务 #1" })).toBeNull();
    });
    expect(screen.getByText("failed", { selector: ".task-status" })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("uses one in-flight list/detail read per event revision and performs terminal replacement", async () => {
    const fetchMock = vi.mocked(fetch);
    const refreshBeforeDetail = deferred<Response>();
    const detail = deferred<Response>();
    const refreshAfterDetail = deferred<Response>();
    let listCall = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks/7") {
        return detail.promise;
      }
      if (path === "/api/tasks?limit=50") {
        listCall += 1;
        if (listCall === 1) {
          return Promise.resolve(responseJson([makeTask(7, "running")]));
        }
        return listCall === 2
          ? refreshBeforeDetail.promise
          : refreshAfterDetail.promise;
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = FakeSocket.instances[0];
    socket.open();
    await waitFor(() => expect(screen.getByRole("heading", { name: "任务 #7" })).toBeTruthy());

    socket.message(makeEvent(7, "done"));
    socket.message(makeEvent(7, "done"));
    await flushPromises();
    expect(fetchMock.mock.calls.filter(([input]) =>
      requestPath(input) === "/api/tasks/7",
    )).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) =>
      requestPath(input) === "/api/tasks?limit=50",
    )).toHaveLength(2);

    refreshBeforeDetail.resolve(responseJson([makeTask(7, "running")]));
    detail.resolve(responseJson(makeTask(7, "done")));
    await flushPromises();
    expect(fetchMock.mock.calls.filter(([input]) =>
      requestPath(input) === "/api/tasks?limit=50",
    )).toHaveLength(3);
    refreshAfterDetail.resolve(responseJson([makeTask(7, "done")]));
    await waitFor(() =>
      expect(screen.getByText("done", { selector: ".task-status" })).toBeTruthy(),
    );
    expect(fetchMock.mock.calls.filter(([input]) =>
      requestPath(input) === "/api/tasks/7",
    )).toHaveLength(1);
  });

  it("keeps detail and latest list failures visible instead of turning them into empty state", async () => {
    const fetchMock = vi.mocked(fetch);
    const detailFailure = deferred<Response>();
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks/55") {
        return detailFailure.promise;
      }
      if (path === "/api/tasks?limit=50") {
        if (fetchMock.mock.calls.length === 1) {
          return Promise.resolve(responseJson([makeTask(5, "running")]));
        }
        return Promise.reject(new Error("最新列表读取失败"));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const socket = FakeSocket.instances[0];
    socket.open();
    await waitFor(() => expect(screen.getByRole("heading", { name: "任务 #5" })).toBeTruthy());

    socket.message(makeEvent(55, "done"));
    await waitFor(() => expect(screen.getByText("最新列表读取失败")).toBeTruthy());
    detailFailure.reject(new Error("任务详情读取失败"));
    await waitFor(() => {
      expect(screen.getByText("任务详情读取失败")).toBeTruthy();
      expect(screen.queryByText("当前条件下暂无任务")).toBeNull();
    });
  });

  it("reconnects at 1/2/5/10 seconds, clears protocol error after sync, and stops on unmount", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(() =>
      Promise.resolve(responseJson([makeTask(3, "done")])),
    );

    const mounted = mountTasks();
    const firstSocket = FakeSocket.instances[0];
    firstSocket.open();
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    firstSocket.close();
    await vi.advanceTimersByTimeAsync(999);
    expect(FakeSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1].close();
    await vi.advanceTimersByTimeAsync(1999);
    expect(FakeSocket.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(3);
    FakeSocket.instances[2].close();
    await vi.advanceTimersByTimeAsync(4999);
    expect(FakeSocket.instances).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(4);
    FakeSocket.instances[3].close();
    await vi.advanceTimersByTimeAsync(9999);
    expect(FakeSocket.instances).toHaveLength(4);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.instances).toHaveLength(5);

    const lastSocket = FakeSocket.instances[4];
    lastSocket.open();
    await flushPromises();
    lastSocket.message("not-json");
    await flushPromises();
    expect(screen.getByText(/Unexpected token/)).toBeTruthy();
    lastSocket.close();
    mounted.unmount();
    const socketCount = FakeSocket.instances.length;
    const fetchCount = fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60000);
    expect(FakeSocket.instances).toHaveLength(socketCount);
    expect(fetchMock).toHaveBeenCalledTimes(fetchCount);
  });
});
