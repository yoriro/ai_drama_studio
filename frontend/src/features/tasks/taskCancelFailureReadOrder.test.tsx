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
    progress: status === "done" || status === "canceled" ? 1 : 0,
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

class FailureReadSocket {
  static instances: FailureReadSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    FailureReadSocket.instances.push(this);
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
  FailureReadSocket.instances = [];
  vi.stubGlobal("WebSocket", FailureReadSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("cancel failure detail read ordering", () => {
  it.each([
    ["network failure", "cancel response lost", null],
    ["409 conflict", "task is already terminal", 409],
  ] as const)(
    "does not let the pre-cancel queued detail clear protection after a %s",
    async (_name, message, cancelStatus) => {
      const fetchMock = vi.mocked(fetch);
      const oldDetail = deferred<Response>();
      const freshDetail = deferred<Response>();
      const refreshedList = deferred<Response>();
      const queued = makeTask(41, "queued");
      const authoritative =
        cancelStatus === null
          ? makeTask(41, "canceled", {
              finished_at: "2026-09-09T00:00:05Z",
            })
          : makeTask(41, "done", {
              finished_at: "2026-09-09T00:00:06Z",
            });
      let detailCalls = 0;
      let listCalls = 0;
      let postCalls = 0;

      fetchMock.mockImplementation((input, init) => {
        const path = requestPath(input);
        if (path === "/api/tasks?limit=50") {
          listCalls += 1;
          return listCalls === 1
            ? Promise.resolve(responseJson([queued]))
            : refreshedList.promise;
        }
        if (path === "/api/tasks/41") {
          detailCalls += 1;
          if (detailCalls === 1) {
            return oldDetail.promise;
          }
          if (detailCalls === 2) {
            return freshDetail.promise;
          }
          throw new Error("unexpected third detail request");
        }
        if (path === "/api/tasks/41/cancel") {
          postCalls += 1;
          expect(init?.method).toBe("POST");
          expect(init?.body).toBeUndefined();
          if (cancelStatus === null) {
            return Promise.reject(new TypeError(message));
          }
          return Promise.resolve(
            responseJson(
              { detail: { code: "task_conflict", message } },
              cancelStatus,
            ),
          );
        }
        throw new Error(`unexpected request ${path}`);
      });

      mountTasks();
      const socket = FailureReadSocket.instances[0];
      socket.open();
      await waitFor(() => expect(within(cardFor(41)).getByRole("button", { name: "查看详情" })).toBeTruthy());

      fireEvent.click(within(cardFor(41)).getByRole("button", { name: "查看详情" }));
      await waitFor(() => expect(detailCalls).toBe(1));
      const firstCancelButton = within(cardFor(41)).getByRole("button", {
        name: "取消任务",
      }) as HTMLButtonElement;
      fireEvent.click(firstCancelButton);

      await waitFor(() => {
        expect(within(cardFor(41)).getByText(message)).toBeTruthy();
        expect(postCalls).toBe(1);
      });
      expect(detailCalls).toBe(1);
      expect(
        within(cardFor(41)).queryByRole("button", { name: "取消任务" }),
      ).toBeNull();

      oldDetail.resolve(responseJson(queued));
      let reactivationAttempted = false;
      await waitFor(() => {
        const currentCancelButton = firstCancelButton.isConnected
          ? firstCancelButton
          : within(cardFor(41)).queryByRole("button", { name: "取消任务" });
        if (
          !reactivationAttempted &&
          currentCancelButton !== null &&
          !(currentCancelButton as HTMLButtonElement).disabled
        ) {
          reactivationAttempted = true;
          fireEvent.click(currentCancelButton);
        }
        expect(detailCalls).toBe(2);
        expect(postCalls).toBe(1);
      });
      expect(postCalls).toBe(1);
      expect(
        within(cardFor(41)).queryByRole("button", { name: "取消任务" }),
      ).toBeNull();
      expect(within(cardFor(41)).getByText(message)).toBeTruthy();
      if (cancelStatus === null) {
        expect(
          within(cardFor(41)).getByText(
            "取消结果未确认，正在读取最新任务状态",
          ),
        ).toBeTruthy();
      }

      freshDetail.resolve(responseJson(authoritative));
      await waitFor(() => {
        expect(
          within(cardFor(41)).getByText(authoritative.status, {
            selector: ".task-status",
          }),
        ).toBeTruthy();
        expect(within(cardFor(41)).getByText(message)).toBeTruthy();
      });
      await waitFor(() => expect(listCalls).toBe(2));
      refreshedList.resolve(responseJson([authoritative]));
      await waitFor(() => expect(postCalls).toBe(1));
      expect(detailCalls).toBe(2);
    },
  );
});
