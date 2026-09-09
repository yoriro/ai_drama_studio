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
    progress: status === "done" || status === "failed" || status === "canceled" ? 1 : 0.4,
    error_msg: null,
    heartbeat_at: "2026-09-09T00:00:03Z",
    cancel_requested_at: null,
    created_at: "2026-09-09T00:00:00Z",
    started_at: "2026-09-09T00:00:01Z",
    finished_at:
      status === "done" || status === "failed" || status === "canceled"
        ? "2026-09-09T00:00:05Z"
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

class FilterDetailSocket {
  static instances: FilterDetailSocket[] = [];

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  opened = false;
  closed = false;

  constructor(readonly url: string) {
    FilterDetailSocket.instances.push(this);
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

function pageDetailFor(taskId: number): HTMLElement {
  const detail = document.querySelector(`#task-detail-${taskId}`);
  if (!(detail instanceof HTMLElement)) {
    throw new Error(`task detail ${taskId} was not rendered`);
  }
  return detail;
}

beforeEach(() => {
  FilterDetailSocket.instances = [];
  vi.stubGlobal("WebSocket", FilterDetailSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TasksPage filter detail rebuild", () => {
  it.each([
    [
      "done",
      makeTask(431, "done", {
        progress: 1,
        finished_at: "2026-09-09T00:00:05Z",
      }),
    ],
    [
      "failed",
      makeTask(431, "failed", {
        progress: 1,
        error_msg: "terminal failure from latest GET",
        finished_at: "2026-09-09T00:00:06Z",
      }),
    ],
    [
      "canceled",
      makeTask(431, "canceled", {
        progress: 1,
        cancel_requested_at: "2026-09-09T00:00:04Z",
        finished_at: "2026-09-09T00:00:07Z",
      }),
    ],
  ] as const)(
    "rebuilds the expanded %s detail after a matching filter reconnect",
    async (_name, latestTask) => {
      const fetchMock = vi.mocked(fetch);
      const oldDetail = deferred<Response>();
      const newList = deferred<Response>();
      const newDetail = deferred<Response>();
      const runningTask = makeTask(431, "running", {
        progress: 0.4,
        heartbeat_at: "2026-09-09T00:00:03Z",
        finished_at: null,
      });
      const requests: string[] = [];
      let detailCalls = 0;
      let listCalls = 0;
      let postCalls = 0;

      fetchMock.mockImplementation((input, init) => {
        const path = requestPath(input);
        requests.push(`${init?.method ?? "GET"} ${path}`);
        if (path === "/api/tasks?limit=50") {
          listCalls += 1;
          if (listCalls === 1) {
            return Promise.resolve(responseJson([runningTask]));
          }
          throw new Error(`unexpected list request ${path}`);
        }
        if (path === "/api/tasks?type=gen_assets&limit=50") {
          listCalls += 1;
          return newList.promise;
        }
        if (path === "/api/tasks/431") {
          detailCalls += 1;
          return detailCalls === 1 ? oldDetail.promise : newDetail.promise;
        }
        if (path === "/api/tasks/431/cancel") {
          postCalls += 1;
          throw new Error("unexpected mutation");
        }
        throw new Error(`unexpected request ${path}`);
      });

      const page = mountTasks();
      const oldSocket = FilterDetailSocket.instances[0];
      oldSocket.open();
      await waitFor(() =>
        expect(
          within(cardFor(431)).getByText("running", {
            selector: ".task-status",
          }),
        ).toBeTruthy(),
      );

      fireEvent.click(
        within(cardFor(431)).getByRole("button", { name: "查看详情" }),
      );
      await waitFor(() => expect(detailCalls).toBe(1));
      expect(
        within(cardFor(431)).getByText("正在加载任务详情…"),
      ).toBeTruthy();

      fireEvent.change(screen.getByRole("combobox", { name: "类型筛选" }), {
        target: { value: "gen_assets" },
      });
      await waitFor(() =>
        expect(FilterDetailSocket.instances).toHaveLength(2),
      );
      const newSocket = FilterDetailSocket.instances[1];
      expect(oldSocket.closed).toBe(true);
      expect(newSocket.opened).toBe(false);
      newSocket.open();
      await waitFor(() => expect(listCalls).toBe(2));

      newList.resolve(responseJson([latestTask]));
      await waitFor(() => expect(detailCalls).toBe(2));

      oldDetail.resolve(responseJson(runningTask));
      await act(async () => {
        for (let index = 0; index < 8; index += 1) {
          await Promise.resolve();
        }
      });
      expect(
        page.container.querySelector('[data-task-state="detail-ready"]'),
      ).toBeNull();
      expect(
        page.container.querySelector('[data-task-state="detail-loading"]'),
      ).not.toBeNull();

      newDetail.resolve(responseJson(latestTask));
      await waitFor(() =>
        expect(
          page.container.querySelector('[data-task-state="detail-ready"]'),
        ).not.toBeNull(),
      );

      const card = cardFor(431);
      const detail = page.container.querySelector(
        '#task-detail-431[data-task-state="detail-ready"]',
      );
      if (!(detail instanceof HTMLElement)) {
        throw new Error("latest task detail was not rendered");
      }
      const fields = detailFields(detail);
      const cardTimes = detailFields(card);
      expect(card.querySelector(".task-status")?.textContent).toBe(
        latestTask.status,
      );
      expect(
        (card.querySelector("progress") as HTMLProgressElement).value,
      ).toBe(latestTask.progress);
      expect(cardTimes["完成时间"]).toBe(
        formatTaskTime(latestTask.finished_at),
      );
      expect(fields["状态"]).toBe(latestTask.status);
      expect(fields["进度"]).toBe(String(latestTask.progress));
      expect(fields["取消请求时间（本地时区）"]).toBe(
        formatTaskTime(latestTask.cancel_requested_at),
      );
      expect(fields["完成时间（本地时区）"]).toBe(
        formatTaskTime(latestTask.finished_at),
      );
      expect(fields["完整错误"]).toBe(latestTask.error_msg ?? "—");
      expect(
        [...card.querySelectorAll(".error-message")].some(
          (element) => element.textContent === latestTask.error_msg,
        ),
      ).toBe(latestTask.error_msg !== null);
      expect(
        requests.filter((request) => request.startsWith("GET /api/tasks?")),
      ).toEqual([
        "GET /api/tasks?limit=50",
        "GET /api/tasks?type=gen_assets&limit=50",
      ]);
      expect(detailCalls).toBe(2);
      expect(postCalls).toBe(0);
      expect(newSocket.opened).toBe(true);
      expect(
        within(card)
          .getByRole("button", { name: "收起详情" })
          .getAttribute("aria-expanded"),
      ).toBe("true");
    },
  );

  it("rebuilds a ready expanded detail when changing the task limit", async () => {
    const fetchMock = vi.mocked(fetch);
    const nextList = deferred<Response>();
    const runningTask = makeTask(434, "running", {
      progress: 0.4,
      finished_at: null,
    });
    const latestTask = makeTask(434, "done", {
      progress: 1,
      finished_at: "2026-09-09T00:00:08Z",
    });
    let detailCalls = 0;
    let listCalls = 0;
    let postCalls = 0;
    const listPaths: string[] = [];

    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        listPaths.push(path);
        return Promise.resolve(responseJson([runningTask]));
      }
      if (path === "/api/tasks?limit=20") {
        listCalls += 1;
        listPaths.push(path);
        return nextList.promise;
      }
      if (path === "/api/tasks/434") {
        detailCalls += 1;
        return Promise.resolve(
          responseJson(detailCalls === 1 ? runningTask : latestTask),
        );
      }
      if (path === "/api/tasks/434/cancel") {
        postCalls += 1;
        throw new Error("unexpected mutation");
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const firstSocket = FilterDetailSocket.instances[0];
    firstSocket.open();
    await waitFor(() => expect(cardFor(434)).toBeTruthy());
    fireEvent.click(
      within(cardFor(434)).getByRole("button", { name: "查看详情" }),
    );
    await waitFor(() =>
      expect(
        within(cardFor(434)).getByText("running", {
          selector: ".task-detail dd",
        }),
      ).toBeTruthy(),
    );
    expect(detailCalls).toBe(1);

    fireEvent.change(screen.getByRole("combobox", { name: "任务数量" }), {
      target: { value: "20" },
    });
    await waitFor(() =>
      expect(FilterDetailSocket.instances).toHaveLength(2),
    );
    const secondSocket = FilterDetailSocket.instances[1];
    expect(firstSocket.closed).toBe(true);
    secondSocket.open();
    await waitFor(() => expect(listCalls).toBe(2));
    nextList.resolve(responseJson([latestTask]));
    await waitFor(() => expect(detailCalls).toBe(2));
    await waitFor(() =>
      expect(
        within(cardFor(434)).getByText("done", {
          selector: ".task-status",
        }),
      ).toBeTruthy(),
    );

    const detail = pageDetailFor(434);
    const fields = detailFields(detail);
    expect(fields["状态"]).toBe("done");
    expect(fields["进度"]).toBe("1");
    expect(fields["完成时间（本地时区）"]).toBe(
      formatTaskTime(latestTask.finished_at),
    );
    expect(listPaths).toEqual([
      "/api/tasks?limit=50",
      "/api/tasks?limit=20",
    ]);
    expect(detailCalls).toBe(2);
    expect(postCalls).toBe(0);
    expect(secondSocket.opened).toBe(true);
    expect(
      within(cardFor(434))
        .getByRole("button", { name: "收起详情" })
        .getAttribute("aria-expanded"),
    ).toBe("true");
  });

  it("does not resurrect an expanded identity after a task disappears and returns", async () => {
    const fetchMock = vi.mocked(fetch);
    const disappearedList = deferred<Response>();
    const returnedList = deferred<Response>();
    const task = makeTask(432, "running");
    const returnedTask = makeTask(432, "done", {
      progress: 1,
      finished_at: "2026-09-09T00:00:09Z",
    });
    let listCalls = 0;
    let detailCalls = 0;

    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        if (listCalls === 1) {
          return Promise.resolve(responseJson([task]));
        }
        return returnedList.promise;
      }
      if (path === "/api/tasks?type=gen_assets&limit=50") {
        listCalls += 1;
        return disappearedList.promise;
      }
      if (path === "/api/tasks/432") {
        detailCalls += 1;
        return Promise.resolve(
          responseJson(detailCalls === 1 ? task : returnedTask),
        );
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    const firstSocket = FilterDetailSocket.instances[0];
    firstSocket.open();
    await waitFor(() => expect(cardFor(432)).toBeTruthy());
    fireEvent.click(
      within(cardFor(432)).getByRole("button", { name: "查看详情" }),
    );
    await waitFor(() =>
      expect(
        within(cardFor(432)).getByRole("button", { name: "收起详情" }),
      ).toBeTruthy(),
    );
    await waitFor(() =>
      expect(
        within(cardFor(432)).getByText("running", {
          selector: ".task-detail dd",
        }),
      ).toBeTruthy(),
    );

    fireEvent.change(screen.getByRole("combobox", { name: "类型筛选" }), {
      target: { value: "gen_assets" },
    });
    await waitFor(() =>
      expect(FilterDetailSocket.instances).toHaveLength(2),
    );
    FilterDetailSocket.instances[1].open();
    await waitFor(() => expect(listCalls).toBe(2));
    disappearedList.resolve(responseJson([]));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "任务 #432" })).toBeNull(),
    );

    fireEvent.change(screen.getByRole("combobox", { name: "类型筛选" }), {
      target: { value: "all" },
    });
    await waitFor(() =>
      expect(FilterDetailSocket.instances).toHaveLength(3),
    );
    FilterDetailSocket.instances[2].open();
    await waitFor(() => expect(listCalls).toBe(3));
    returnedList.resolve(responseJson([returnedTask]));
    await waitFor(() => expect(cardFor(432)).toBeTruthy());
    expect(detailCalls).toBe(1);
    expect(
      within(cardFor(432)).getByRole("button", { name: "查看详情" }),
    ).toBeTruthy();
    expect(
      within(cardFor(432)).queryByRole("button", { name: "收起详情" }),
    ).toBeNull();
    expect(cardFor(432).querySelector(".task-status")?.textContent).toBe(
      "done",
    );
    fireEvent.click(
      within(cardFor(432)).getByRole("button", { name: "查看详情" }),
    );
    await waitFor(() => expect(detailCalls).toBe(2));
    await waitFor(() =>
      expect(
        within(cardFor(432)).getByText("done", {
          selector: ".task-detail dd",
        }),
      ).toBeTruthy(),
    );
    const detail = pageDetailFor(432);
    const fields = detailFields(detail);
    expect(fields["状态"]).toBe("done");
    expect(fields["进度"]).toBe("1");
    expect(fields["完成时间（本地时区）"]).toBe(
      formatTaskTime(returnedTask.finished_at),
    );
    expect(detailCalls).toBe(2);
  });

  it("clears the expanded identity when the user closes detail", async () => {
    const fetchMock = vi.mocked(fetch);
    const task = makeTask(433, "running");
    let listCalls = 0;
    let detailCalls = 0;
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/tasks?limit=50") {
        listCalls += 1;
        return Promise.resolve(responseJson([task]));
      }
      if (path === "/api/tasks?limit=20") {
        listCalls += 1;
        return Promise.resolve(responseJson([task]));
      }
      if (path === "/api/tasks/433") {
        detailCalls += 1;
        return Promise.resolve(responseJson(task));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountTasks();
    FilterDetailSocket.instances[0].open();
    await waitFor(() => expect(cardFor(433)).toBeTruthy());
    fireEvent.click(
      within(cardFor(433)).getByRole("button", { name: "查看详情" }),
    );
    await waitFor(() =>
      expect(
        within(cardFor(433)).getByRole("button", { name: "收起详情" }),
      ).toBeTruthy(),
    );
    expect(detailCalls).toBe(1);
    fireEvent.click(
      within(cardFor(433)).getByRole("button", { name: "收起详情" }),
    );
    expect(
      within(cardFor(433)).getByRole("button", { name: "查看详情" }),
    ).toBeTruthy();
    expect(
      within(cardFor(433)).queryByRole("button", { name: "收起详情" }),
    ).toBeNull();

    fireEvent.change(screen.getByRole("combobox", { name: "任务数量" }), {
      target: { value: "20" },
    });
    await waitFor(() =>
      expect(FilterDetailSocket.instances).toHaveLength(2),
    );
    FilterDetailSocket.instances[1].open();
    await waitFor(() => expect(listCalls).toBe(2));
    expect(detailCalls).toBe(1);
    expect(
      within(cardFor(433)).getByRole("button", { name: "查看详情" }),
    ).toBeTruthy();
    expect(
      within(cardFor(433)).queryByRole("button", { name: "收起详情" }),
    ).toBeNull();
  });
});
