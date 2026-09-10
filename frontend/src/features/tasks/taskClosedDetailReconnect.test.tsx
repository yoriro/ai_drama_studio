// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { Task } from "../../api/tasks";
import { TasksPage } from "../../pages/TasksPage";

function makeTask(
  id: number,
  status: Task["status"],
  overrides: Partial<Task> = {},
): Task {
  const terminal =
    status === "done" || status === "failed" || status === "canceled";
  return {
    id,
    type: "gen_assets",
    target_id: id + 100,
    request_id: null,
    status,
    progress: terminal ? 1 : 0.5,
    error_msg: status === "failed" ? "任务失败" : null,
    heartbeat_at: "2026-09-10T00:00:03Z",
    cancel_requested_at: null,
    created_at: "2026-09-10T00:00:00Z",
    started_at: "2026-09-10T00:00:01Z",
    finished_at: terminal ? "2026-09-10T00:00:05Z" : null,
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

function formatTaskTime(value: string | null): string {
  return value === null
    ? "—"
    : new Date(value).toLocaleString(undefined, { timeZoneName: "short" });
}

function detailFields(container: HTMLElement): Record<string, string> {
  return Object.fromEntries(
    [...container.querySelectorAll("dt")].map((term) => [
      term.textContent,
      term.nextElementSibling?.textContent ?? "",
    ]),
  );
}

async function flushPromises(): Promise<void> {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) {
      await Promise.resolve();
    }
  });
}

class ClosedDetailSocket {
  static instances: ClosedDetailSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  opened = false;
  closed = false;

  constructor(readonly url: string) {
    ClosedDetailSocket.instances.push(this);
  }

  open(): void {
    this.opened = true;
    this.onopen?.({} as Event);
  }

  close(): void {
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

function cardFor(taskId: number): HTMLElement {
  const heading = screen.getByRole("heading", { name: `任务 #${taskId}` });
  const card = heading.closest("article");
  if (card === null) {
    throw new Error(`task card ${taskId} was not rendered`);
  }
  return card;
}

function detailFor(taskId: number): HTMLElement {
  const detail = document.querySelector(`#task-detail-${taskId}`);
  if (!(detail instanceof HTMLElement)) {
    throw new Error(`task detail ${taskId} was not rendered`);
  }
  return detail;
}

beforeEach(() => {
  ClosedDetailSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", ClosedDetailSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("closed task detail after connection rebuild", () => {
  it.each(["disconnect", "filter"] as const)(
    "keeps a collapsed detail stale until explicit reopen after %s",
    async (rebuild) => {
      const fetchMock = vi.mocked(fetch);
      const running = makeTask(501, "running", {
        progress: 0.5,
        finished_at: null,
      });
      const latest = makeTask(501, "failed", {
        progress: 1,
        error_msg: "server failed after reconnect",
        finished_at: "2026-09-10T00:00:08Z",
      });
      let defaultListCalls = 0;
      let filteredListCalls = 0;
      let detailCalls = 0;
      const requests: string[] = [];

      fetchMock.mockImplementation((input, init) => {
        const path = requestPath(input);
        requests.push(`${init?.method ?? "GET"} ${path}`);
        if (path === "/api/tasks?limit=50") {
          defaultListCalls += 1;
          return Promise.resolve(
            responseJson([defaultListCalls === 1 ? running : latest]),
          );
        }
        if (path === "/api/tasks?type=gen_assets&limit=50") {
          filteredListCalls += 1;
          return Promise.resolve(responseJson([latest]));
        }
        if (path === "/api/tasks/501") {
          detailCalls += 1;
          return Promise.resolve(
            responseJson(detailCalls === 1 ? running : latest),
          );
        }
        if (path === "/api/tasks/501/cancel") {
          throw new Error("unexpected cancellation mutation");
        }
        throw new Error(`unexpected request ${path}`);
      });

      mountTasks();
      const firstSocket = ClosedDetailSocket.instances[0];
      firstSocket.open();
      await flushPromises();
      expect(defaultListCalls).toBe(1);
      expect(cardFor(501).querySelector(".task-status")?.textContent).toBe(
        "running",
      );

      const card = cardFor(501);
      fireEvent.click(within(card).getByRole("button", { name: "查看详情" }));
      await flushPromises();
      expect(detailCalls).toBe(1);
      expect(
        within(card).getByRole("button", { name: "收起详情" }),
      ).toBeTruthy();
      fireEvent.click(within(card).getByRole("button", { name: "收起详情" }));
      expect(
        within(card).getByRole("button", { name: "查看详情" }),
      ).toBeTruthy();
      expect(detailCalls).toBe(1);

      if (rebuild === "disconnect") {
        firstSocket.close();
        await vi.advanceTimersByTimeAsync(1000);
        await flushPromises();
        expect(ClosedDetailSocket.instances).toHaveLength(2);
        ClosedDetailSocket.instances[1].open();
        await flushPromises();
        expect(defaultListCalls).toBe(2);
      } else {
        fireEvent.change(screen.getByRole("combobox", { name: "类型筛选" }), {
          target: { value: "gen_assets" },
        });
        await flushPromises();
        expect(ClosedDetailSocket.instances).toHaveLength(2);
        expect(firstSocket.closed).toBe(true);
        ClosedDetailSocket.instances[1].open();
        await flushPromises();
        expect(filteredListCalls).toBe(1);
      }

      expect(cardFor(501).querySelector(".task-status")?.textContent).toBe(
        "failed",
      );
      expect(detailCalls).toBe(1);
      expect(
        within(cardFor(501)).getByRole("button", { name: "查看详情" }),
      ).toBeTruthy();

      fireEvent.click(
        within(cardFor(501)).getByRole("button", { name: "查看详情" }),
      );
      await flushPromises();
      expect(detailCalls).toBe(2);

      const latestCard = cardFor(501);
      const detail = detailFor(501);
      const fields = detailFields(detail);
      expect(fields["状态"]).toBe(latest.status);
      expect(fields["进度"]).toBe(String(latest.progress));
      expect(fields["完成时间（本地时区）"]).toBe(
        formatTaskTime(latest.finished_at),
      );
      expect(fields["取消请求时间（本地时区）"]).toBe("—");
      expect(fields["完整错误"]).toBe(latest.error_msg);
      expect(latestCard.querySelector(".task-status")?.textContent).toBe(
        latest.status,
      );
      expect(
        latestCard.querySelector(".error-message")?.textContent,
      ).toBe(latest.error_msg);
      expect(
        requests.filter((request) => request === "POST /api/tasks/501/cancel"),
      ).toHaveLength(0);
    },
  );

  it("does not replay cancellation and refreshes a collapsed target with cancellation intent after reconnect", async () => {
    const fetchMock = vi.mocked(fetch);
    const targetRunning = makeTask(502, "running", {
      progress: 0.4,
      finished_at: null,
    });
    const confirmedTarget = makeTask(502, "running", {
      progress: 0.4,
      cancel_requested_at: "2026-09-10T00:00:06Z",
      finished_at: null,
    });
    const targetFailed = makeTask(502, "failed", {
      progress: 1,
      cancel_requested_at: "2026-09-10T00:00:06Z",
      error_msg: "worker stopped after cancellation",
      finished_at: "2026-09-10T00:00:09Z",
    });
    const otherRunning = makeTask(503, "running", {
      progress: 0.6,
      finished_at: null,
    });
    const otherLatest = makeTask(503, "done", {
      progress: 1,
      finished_at: "2026-09-10T00:00:10Z",
    });
    let listCalls = 0;
    let targetDetailCalls = 0;
    let otherDetailCalls = 0;
    let postCalls = 0;

    fetchMock.mockImplementation((input, init) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        return Promise.resolve(
          responseJson(
            listCalls === 1
              ? [targetRunning, otherRunning]
              : listCalls === 2
                ? [confirmedTarget, otherRunning]
                : [targetFailed, otherLatest],
          ),
        );
      }
      if (path === "/api/tasks/502") {
        targetDetailCalls += 1;
        return Promise.resolve(
          responseJson(
            targetDetailCalls === 1 ? confirmedTarget : targetFailed,
          ),
        );
      }
      if (path === "/api/tasks/503") {
        otherDetailCalls += 1;
        return Promise.resolve(
          responseJson(otherDetailCalls === 1 ? otherRunning : otherLatest),
        );
      }
      if (path === "/api/tasks/502/cancel") {
        expect(init?.method).toBe("POST");
        expect(init?.body).toBeUndefined();
        postCalls += 1;
        return Promise.resolve(responseJson(confirmedTarget));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const firstSocket = ClosedDetailSocket.instances[0];
    firstSocket.open();
    await flushPromises();
    expect(listCalls).toBe(1);

    const targetCard = cardFor(502);
    fireEvent.click(within(targetCard).getByRole("button", { name: "取消任务" }));
    await flushPromises();
    expect(postCalls).toBe(1);
    expect(targetDetailCalls).toBe(1);
    expect(listCalls).toBe(2);
    expect(
      within(cardFor(502)).getByText("已请求取消", { selector: "button" }),
    ).toBeTruthy();

    fireEvent.click(
      within(cardFor(503)).getByRole("button", { name: "查看详情" }),
    );
    await flushPromises();
    expect(otherDetailCalls).toBe(1);
    expect(
      within(cardFor(503)).getByRole("button", { name: "收起详情" }),
    ).toBeTruthy();

    firstSocket.close();
    await vi.advanceTimersByTimeAsync(1000);
    await flushPromises();
    expect(ClosedDetailSocket.instances).toHaveLength(2);
    ClosedDetailSocket.instances[1].open();
    await flushPromises();
    expect(listCalls).toBe(3);
    expect(otherDetailCalls).toBe(2);
    expect(targetDetailCalls).toBe(1);
    expect(postCalls).toBe(1);
    expect(cardFor(502).querySelector(".task-status")?.textContent).toBe(
      "failed",
    );
    expect(cardFor(503).querySelector(".task-status")?.textContent).toBe(
      "done",
    );
    const otherFields = detailFields(detailFor(503));
    expect(otherFields["状态"]).toBe(otherLatest.status);
    expect(otherFields["进度"]).toBe(String(otherLatest.progress));
    expect(otherFields["完成时间（本地时区）"]).toBe(
      formatTaskTime(otherLatest.finished_at),
    );

    fireEvent.click(
      within(cardFor(502)).getByRole("button", { name: "查看详情" }),
    );
    await flushPromises();
    expect(targetDetailCalls).toBe(2);
    expect(postCalls).toBe(1);

    const fields = detailFields(detailFor(502));
    expect(fields["状态"]).toBe(targetFailed.status);
    expect(fields["进度"]).toBe(String(targetFailed.progress));
    expect(fields["取消请求时间（本地时区）"]).toBe(
      formatTaskTime(targetFailed.cancel_requested_at),
    );
    expect(fields["完成时间（本地时区）"]).toBe(
      formatTaskTime(targetFailed.finished_at),
    );
    expect(fields["完整错误"]).toBe(targetFailed.error_msg);
    expect(cardFor(502).querySelector(".error-message")?.textContent).toBe(
      targetFailed.error_msg,
    );
  });
});
