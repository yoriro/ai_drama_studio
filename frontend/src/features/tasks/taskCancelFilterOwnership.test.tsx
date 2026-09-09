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
  type: Task["type"] = "gen_assets",
  overrides: Partial<Task> = {},
): Task {
  return {
    id,
    type,
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

class OwnershipSocket {
  static instances: OwnershipSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    OwnershipSocket.instances.push(this);
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

beforeEach(() => {
  OwnershipSocket.instances = [];
  vi.stubGlobal("WebSocket", OwnershipSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TasksPage cancellation ownership across filter windows", () => {
  it("keeps one pending cancellation across matching status/type/limit changes and isolates a late error", async () => {
    const fetchMock = vi.mocked(fetch);
    const cancelA = deferred<Response>();
    const taskA = makeTask(10, "queued");
    const taskB = makeTask(20, "running", "gen_asset_image");
    const listForQuery = (path: string): Task[] => {
      if (path === "/api/tasks?status=queued&type=gen_assets&limit=20") {
        return [taskA];
      }
      if (path === "/api/tasks?type=gen_assets&limit=20") {
        return [taskA];
      }
      if (path === "/api/tasks?limit=20") {
        return [taskB, taskA];
      }
      if (path === "/api/tasks?status=queued&limit=50") {
        return [taskA];
      }
      if (path === "/api/tasks?limit=50") {
        return [taskB, taskA];
      }
      if (path === "/api/tasks?status=queued&type=gen_assets&limit=50") {
        return [taskA];
      }
      throw new Error(`unexpected list request ${path}`);
    };

    fetchMock.mockImplementation((input, init) => {
      const path = requestPath(input);
      if (path === "/api/tasks/10/cancel") {
        expect(init?.body).toBeUndefined();
        return cancelA.promise;
      }
      if (path === "/api/tasks/20/cancel") {
        expect(init?.body).toBeUndefined();
        return Promise.resolve(responseJson(taskB));
      }
      if (path === "/api/tasks/20") {
        return Promise.resolve(responseJson(taskB));
      }
      if (path === "/api/tasks/10") {
        return Promise.resolve(responseJson(taskA));
      }
      return Promise.resolve(responseJson(listForQuery(path)));
    });

    mountTasks();
    const socket = OwnershipSocket.instances[0];
    socket.open();
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

    const filters = [
      ["状态筛选", "queued"],
      ["类型筛选", "gen_assets"],
      ["任务数量", "20"],
    ] as const;
    for (const [label, value] of filters) {
      fireEvent.change(screen.getByRole("combobox", { name: label }), {
        target: { value },
      });
      await waitFor(() => {
        expect(within(cardFor(10)).getByRole("button", { name: "正在取消…" })).toBeTruthy();
      });
      const pendingButton = within(cardFor(10)).getByRole("button", {
        name: "正在取消…",
      });
      pendingButton.focus();
      fireEvent.keyDown(pendingButton, { key: "Enter", code: "Enter" });
      fireEvent.keyUp(pendingButton, { key: "Enter", code: "Enter" });
      fireEvent.click(pendingButton);
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/10/cancel",
        ),
      ).toHaveLength(1);
    }

    fireEvent.change(screen.getByRole("combobox", { name: "状态筛选" }), {
      target: { value: "all" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "类型筛选" }), {
      target: { value: "all" },
    });
    await waitFor(() => expect(cardFor(20)).toBeTruthy());
    fireEvent.click(within(cardFor(20)).getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          requestPath(input) === "/api/tasks/20/cancel",
        ),
      ).toHaveLength(1),
    );
    expect(
      within(cardFor(10)).getByRole("button", { name: "正在取消…" }),
    ).toBeTruthy();

    cancelA.resolve(
      responseJson(
        { detail: { code: "task_conflict", message: "任务取消结果待确认" } },
        409,
      ),
    );
    await waitFor(() =>
      expect(within(cardFor(10)).getByText("任务取消结果待确认")).toBeTruthy(),
    );
    expect(within(cardFor(20)).queryByText("任务取消结果待确认")).toBeNull();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/10/cancel",
      ),
    ).toHaveLength(1);
  });

  it("does not let a late cancellation response update a page after unmount", async () => {
    const fetchMock = vi.mocked(fetch);
    const cancel = deferred<Response>();
    const task = makeTask(30, "queued");
    fetchMock.mockImplementation((input, init) => {
      const path = requestPath(input);
      if (path === "/api/tasks/30/cancel") {
        expect(init?.body).toBeUndefined();
        return cancel.promise;
      }
      if (path === "/api/tasks?limit=50") {
        return Promise.resolve(responseJson([task]));
      }
      throw new Error(`unexpected request ${path}`);
    });

    const mounted = mountTasks();
    OwnershipSocket.instances[0].open();
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
    cancel.resolve(responseJson(task));
    await flushPromises();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/30",
      ),
    ).toHaveLength(0);
  });
});
