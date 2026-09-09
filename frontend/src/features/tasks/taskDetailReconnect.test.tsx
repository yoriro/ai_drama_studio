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
    target_id: id + 100,
    request_id: null,
    status,
    progress: status === "running" ? 0.4 : 1,
    error_msg: status === "failed" ? "line one\nline two\nfull failure context" : null,
    heartbeat_at: null,
    cancel_requested_at: status === "canceled" ? "2026-09-09T00:00:03Z" : null,
    created_at: "2026-09-09T00:00:00Z",
    started_at: "2026-09-09T00:00:01Z",
    finished_at: status === "running" ? null : "2026-09-09T00:00:04Z",
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

class ReconnectSocket {
  static instances: ReconnectSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    ReconnectSocket.instances.push(this);
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

async function flushPromises(): Promise<void> {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) {
      await Promise.resolve();
    }
  });
}

beforeEach(() => {
  ReconnectSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", ReconnectSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("expanded task detail after WebSocket reconnect", () => {
  it.each([
    ["done", makeTask(13, "done")],
    ["failed", makeTask(13, "failed")],
    ["canceled", makeTask(13, "canceled")],
  ] as const)("rebuilds expanded %s detail from the post-reconnect GET", async (_name, terminal) => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(13, "running");
    let listCalls = 0;
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        return Promise.resolve(responseJson([listCalls === 1 ? running : terminal]));
      }
      if (path === "/api/tasks/13") {
        detailCalls += 1;
        return Promise.resolve(responseJson(detailCalls === 1 ? running : terminal));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const firstSocket = ReconnectSocket.instances[0];
    firstSocket.open();
    await flushPromises();
    expect(cardFor(13)).toBeTruthy();
    fireEvent.click(within(cardFor(13)).getByRole("button", { name: "查看详情" }));
    await flushPromises();
    expect(detailCalls).toBe(1);
    expect(within(cardFor(13)).getAllByText("running")).not.toHaveLength(0);

    firstSocket.close();
    await vi.advanceTimersByTimeAsync(1000);
    await flushPromises();
    expect(ReconnectSocket.instances).toHaveLength(2);
    ReconnectSocket.instances[1].open();
    await flushPromises();
    expect(listCalls).toBe(2);
    expect(detailCalls).toBe(2);

    expect(within(cardFor(13)).getAllByText(terminal.status)).not.toHaveLength(0);
    expect(within(cardFor(13)).getByText(String(terminal.progress))).toBeTruthy();
    expect(
      within(cardFor(13)).getAllByText(formatTaskTime(terminal.finished_at!)),
    ).not.toHaveLength(0);
    expect(within(cardFor(13)).getAllByText("—")).not.toHaveLength(0);
    if (terminal.error_msg !== null) {
      expect(
        within(cardFor(13)).getByText(
          (_, element) =>
            element?.tagName === "PRE" && element.textContent === terminal.error_msg,
        ),
      ).toBeTruthy();
    }
    if (terminal.cancel_requested_at !== null) {
      expect(
        within(cardFor(13)).getAllByText(formatTaskTime(terminal.cancel_requested_at)),
      ).not.toHaveLength(0);
    }
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        requestPath(input) === "/api/tasks/13/cancel",
      ),
    ).toHaveLength(0);
  });

  it("shows a refreshed detail read failure without unloading the page", async () => {
    const fetchMock = vi.mocked(fetch);
    const running = makeTask(14, "running");
    let listCalls = 0;
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        return Promise.resolve(responseJson([makeTask(14, listCalls === 1 ? "running" : "done")]));
      }
      if (path === "/api/tasks/14") {
        detailCalls += 1;
        return detailCalls === 1
          ? Promise.resolve(responseJson(running))
          : Promise.reject(new Error("重连后的任务详情读取失败"));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const firstSocket = ReconnectSocket.instances[0];
    firstSocket.open();
    await flushPromises();
    expect(cardFor(14)).toBeTruthy();
    fireEvent.click(within(cardFor(14)).getByRole("button", { name: "查看详情" }));
    await flushPromises();
    expect(detailCalls).toBe(1);
    firstSocket.close();
    await vi.advanceTimersByTimeAsync(1000);
    await flushPromises();
    ReconnectSocket.instances[1].open();
    await flushPromises();
    expect(listCalls).toBe(2);
    expect(detailCalls).toBe(2);
    expect(screen.getAllByText("重连后的任务详情读取失败").length).toBeGreaterThan(0);
    expect(screen.queryByText("当前条件下暂无任务")).toBeNull();
  });
});
