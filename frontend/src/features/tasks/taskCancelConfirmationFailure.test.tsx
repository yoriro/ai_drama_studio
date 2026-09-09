// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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

class ConfirmationFailureSocket {
  static instances: ConfirmationFailureSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    ConfirmationFailureSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.({} as Event);
  }

  message(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
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
  ConfirmationFailureSocket.instances = [];
  vi.stubGlobal("WebSocket", ConfirmationFailureSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("cancellation confirmation read failures", () => {
  it.each([
    ["canceled", makeTask(51, "canceled", { finished_at: "2026-09-09T00:00:05Z" })],
    [
      "running with cancel_requested_at",
      makeTask(51, "running", {
        cancel_requested_at: "2026-09-09T00:00:04Z",
        finished_at: null,
      }),
    ],
  ] as const)(
    "keeps cancellation protected after a post-cancel %s read fails",
    async (_name, authoritative) => {
      const fetchMock = vi.mocked(fetch);
      const preCancelDetail = deferred<Response>();
      const failedConfirmationDetail = deferred<Response>();
      const recoveryDetail = deferred<Response>();
      const refreshedList = deferred<Response>();
      const queued = makeTask(51, "queued");
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
        if (path === "/api/tasks/51") {
          detailCalls += 1;
          if (detailCalls === 1) {
            return preCancelDetail.promise;
          }
          if (detailCalls === 2) {
            return failedConfirmationDetail.promise;
          }
          if (detailCalls === 3) {
            return recoveryDetail.promise;
          }
          throw new Error("unexpected fourth detail request");
        }
        if (path === "/api/tasks/51/cancel") {
          postCalls += 1;
          expect(init?.method).toBe("POST");
          expect(init?.body).toBeUndefined();
          return Promise.resolve(responseJson(authoritative));
        }
        throw new Error(`unexpected request ${path}`);
      });

      mountTasks();
      const socket = ConfirmationFailureSocket.instances[0];
      socket.open();
      await waitFor(() =>
        expect(
          within(cardFor(51)).getByRole("button", { name: "查看详情" }),
        ).toBeTruthy(),
      );

      fireEvent.click(
        within(cardFor(51)).getByRole("button", { name: "查看详情" }),
      );
      await waitFor(() => expect(detailCalls).toBe(1));
      const firstCancelButton = within(cardFor(51)).getByRole("button", {
        name: "取消任务",
      }) as HTMLButtonElement;
      fireEvent.click(firstCancelButton);
      await waitFor(() =>
        expect(
          within(cardFor(51)).getByRole("button", { name: "正在确认取消…" }),
        ).toBeTruthy(),
      );

      preCancelDetail.resolve(responseJson(queued));
      await waitFor(() => expect(detailCalls).toBe(2));
      expect(postCalls).toBe(1);

      failedConfirmationDetail.reject(
        new TypeError("取消后的权威详情读取失败"),
      );
      await waitFor(() =>
        expect(
          within(cardFor(51)).getAllByText("取消后的权威详情读取失败").length,
        ).toBeGreaterThan(0),
      );

      const currentCancelButton = firstCancelButton.isConnected
        ? firstCancelButton
        : within(cardFor(51)).queryByRole("button", { name: "取消任务" });
      if (
        currentCancelButton !== null &&
        !(currentCancelButton as HTMLButtonElement).disabled
      ) {
        fireEvent.click(currentCancelButton);
      }
      expect(postCalls).toBe(1);
      expect(
        within(cardFor(51)).getByText(
          "取消结果未确认，正在读取最新任务状态",
        ),
      ).toBeTruthy();
      expect(detailCalls).toBe(2);

      socket.message({
        task_id: 51,
        type: "gen_assets",
        status: authoritative.status,
        progress: authoritative.progress,
        message:
          authoritative.status === "running"
            ? "已请求取消"
            : "任务已取消",
      });
      await waitFor(() => expect(detailCalls).toBe(3));

      recoveryDetail.resolve(responseJson(authoritative));
      await waitFor(() =>
        expect(
          within(cardFor(51)).getByText(authoritative.status, {
            selector: ".task-status",
          }),
        ).toBeTruthy(),
      );
      expect(postCalls).toBe(1);
      if (authoritative.status === "running") {
        expect(
          within(cardFor(51)).getByText("已请求取消，等待任务停止"),
        ).toBeTruthy();
      } else {
        expect(
          within(cardFor(51)).queryByRole("button", { name: "取消任务" }),
        ).toBeNull();
      }
    },
  );

  it("does not self-refresh detail after a successful list and repeated authority failures", async () => {
    const fetchMock = vi.mocked(fetch);
    const parkedDetail = deferred<Response>();
    const queued = makeTask(541, "queued");
    let listCalls = 0;
    let detailCalls = 0;
    let postCalls = 0;

    fetchMock.mockImplementation((input, init) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        return Promise.resolve(responseJson([queued]));
      }
      if (path === "/api/tasks/541") {
        detailCalls += 1;
        if (detailCalls === 1) {
          return Promise.reject(new TypeError("authority read unavailable"));
        }
        return parkedDetail.promise;
      }
      if (path === "/api/tasks/541/cancel") {
        postCalls += 1;
        expect(init?.method).toBe("POST");
        expect(init?.body).toBeUndefined();
        return Promise.resolve(responseJson(makeTask(541, "canceled")));
      }
      throw new Error(`unexpected request ${path}`);
    });

    const page = mountTasks();
    const socket = ConfirmationFailureSocket.instances[0];
    socket.open();
    await waitFor(() =>
      expect(
        within(cardFor(541)).getByRole("button", { name: "取消任务" }),
      ).toBeTruthy(),
    );

    fireEvent.click(
      within(cardFor(541)).getByRole("button", { name: "取消任务" }),
    );
    await waitFor(() =>
      expect(page.container.textContent).toContain("authority read unavailable"),
    );
    await act(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });

    const observed = { listCalls, detailCalls, postCalls };
    parkedDetail.resolve(responseJson(queued));

    expect(observed).toEqual({ listCalls: 1, detailCalls: 1, postCalls: 1 });
    expect(
      within(cardFor(541)).queryByRole("button", { name: "取消任务" }),
    ).toBeNull();
    expect(page.container.textContent).toContain(
      "取消结果未确认，正在读取最新任务状态",
    );
  });
});
