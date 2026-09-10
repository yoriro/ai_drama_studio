// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
    target_id: 100 + id,
    request_id: null,
    status,
    progress: status === "running" ? 0.4 : 1,
    error_msg: status === "failed" ? "full failure context" : null,
    heartbeat_at: null,
    cancel_requested_at: status === "canceled" ? "2026-09-10T00:00:03Z" : null,
    created_at: "2026-09-10T00:00:00Z",
    started_at: "2026-09-10T00:00:01Z",
    finished_at: status === "running" ? null : "2026-09-10T00:00:04Z",
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

class SlowConsumerSocket {
  static instances: SlowConsumerSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  private closed = false;

  constructor(readonly url: string) {
    SlowConsumerSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.({} as Event);
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.onclose?.({ code: 1000 } as CloseEvent);
  }

  closeFromServer(code: number): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.onclose?.({ code } as CloseEvent);
  }
}

function mountTasks() {
  return render(
    <MemoryRouter initialEntries={["/tasks"]}>
      <TasksPage />
    </MemoryRouter>,
  );
}

function taskCard(taskId: number): HTMLElement {
  const heading = screen.getByRole("heading", { name: `任务 #${taskId}` });
  const card = heading.closest("article");
  if (card === null) {
    throw new Error(`task card ${taskId} was not rendered`);
  }
  return card;
}

async function flushPromises(): Promise<void> {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) {
      await Promise.resolve();
    }
  });
}

beforeEach(() => {
  SlowConsumerSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", SlowConsumerSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("TasksPage slow-consumer reconnect", () => {
  it("rebuilds expanded terminal detail after a 1013 close without replaying mutations", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(73, "running");
    const terminal = makeTask(73, "done");
    let serverTask = running;
    const paths: string[] = [];
    let listCalls = 0;
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      paths.push(path);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        return Promise.resolve(
          responseJson([listCalls === 1 ? running : serverTask]),
        );
      }
      if (path === "/api/tasks/73") {
        detailCalls += 1;
        return Promise.resolve(
          responseJson(detailCalls === 1 ? running : serverTask),
        );
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const firstSocket = SlowConsumerSocket.instances[0];
    firstSocket.open();
    await flushPromises();
    expect(paths).toEqual(["/api/tasks?limit=50"]);

    fireEvent.click(
      within(taskCard(73)).getByRole("button", { name: "查看详情" }),
    );
    await flushPromises();
    expect(detailCalls).toBe(1);
    expect(within(taskCard(73)).getByText("running", { selector: ".task-status" })).toBeTruthy();

    await act(async () => {
      firstSocket.closeFromServer(1013);
    });
    expect(screen.getByRole("status").textContent).toContain(
      "实时连接已断开，正在重连",
    );

    serverTask = terminal;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(SlowConsumerSocket.instances).toHaveLength(2);
    expect(paths).toEqual([
      "/api/tasks?limit=50",
      "/api/tasks/73",
    ]);

    SlowConsumerSocket.instances[1].open();
    await flushPromises();

    expect(paths).toEqual([
      "/api/tasks?limit=50",
      "/api/tasks/73",
      "/api/tasks?limit=50",
      "/api/tasks/73",
    ]);
    expect(listCalls).toBe(2);
    expect(detailCalls).toBe(2);
    expect(screen.queryByRole("status")).toBeNull();
    const finalCard = taskCard(73);
    expect(within(finalCard).getByText("done", { selector: ".task-status" })).toBeTruthy();
    expect(within(finalCard).getByText("100%")).toBeTruthy();
    const detail = finalCard.querySelector('[data-task-state="detail-ready"]');
    expect(detail).not.toBeNull();
    expect(detail?.textContent).toContain("done");
    expect(detail?.textContent).toContain("1");
    expect(finalCard.querySelector('[data-task-state="detail-loading"]')).toBeNull();
    expect(
      paths.filter(
        (path) => path.endsWith("/cancel") || path.endsWith("/generate-video"),
      ),
    ).toEqual([]);
    expect(screen.getByText("完成时间")).toBeTruthy();
  });
});
