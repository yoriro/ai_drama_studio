// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "../../routes/AppRoutes";
import { initializeTheme } from "./theme";

interface Deferred<T> {
  promise: Promise<T>;
  reject: (reason?: unknown) => void;
  resolve: (value: T | PromiseLike<T>) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
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

function healthResponse(): unknown {
  return {
    vllm: { status: "healthy", message: null },
    comfy: { status: "healthy", message: null },
    workflow_bindings: {
      status: "valid",
      message: null,
      hashes: {
        zimage: "a".repeat(64),
        minimaxh3: "b".repeat(64),
      },
    },
  };
}

function taskResponse(): unknown {
  return {
    id: 7,
    type: "gen_assets",
    target_id: 1,
    request_id: null,
    status: "failed",
    progress: 1,
    error_msg: "fixture failure",
    heartbeat_at: null,
    cancel_requested_at: null,
    created_at: "2026-09-08T00:00:00Z",
    started_at: "2026-09-08T00:00:01Z",
    finished_at: "2026-09-08T00:00:02Z",
  };
}

function projectResponse(): unknown {
  return {
    id: 1,
    name: "主题保持项目",
    style_id: 1,
    created_at: "2026-09-08T00:00:00Z",
  };
}

function episodeResponse(): unknown {
  return {
    id: 1,
    project_id: 1,
    seq: 1,
    title: "主题保持集",
    script_text: "原始剧本",
    script_revision: 1,
    assets_generated_script_revision: null,
    shots_generated_script_revision: null,
    created_at: "2026-09-08T00:00:00Z",
    updated_at: "2026-09-08T00:00:00Z",
  };
}

class ThemeSocket {
  static instances: ThemeSocket[] = [];

  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    ThemeSocket.instances.push(this);
  }

  close(): void {
    this.onclose?.({} as CloseEvent);
  }
}

function mountAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  document.head.innerHTML = '<meta name="theme-color" content="">';
  window.localStorage.clear();
  initializeTheme();
  ThemeSocket.instances = [];
  vi.stubGlobal("WebSocket", ThemeSocket);
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AppShell theme wiring", () => {
  it("changes the official buttons without resetting task filters, fetches, or the socket", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/system/health") {
        return Promise.resolve(responseJson(healthResponse()));
      }
      if (
        path === "/api/tasks?limit=50" ||
        path === "/api/tasks?status=failed&limit=50"
      ) {
        return Promise.resolve(responseJson([taskResponse()]));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountAt("/tasks");
    await waitFor(() =>
      expect(screen.getByRole("group", { name: "外观主题" })).toBeTruthy(),
    );
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "状态筛选" })).toBeTruthy(),
    );
    expect(ThemeSocket.instances).toHaveLength(1);

    fireEvent.change(screen.getByRole("combobox", { name: "状态筛选" }), {
      target: { value: "failed" },
    });
    await waitFor(() =>
      expect(
        (screen.getByRole("combobox", { name: "状态筛选" }) as HTMLSelectElement)
          .value,
      ).toBe("failed"),
    );
    await waitFor(() => expect(ThemeSocket.instances).toHaveLength(2));

    const fetchCountBeforeTheme = fetchMock.mock.calls.length;
    const socketCountBeforeTheme = ThemeSocket.instances.length;
    fireEvent.click(screen.getByRole("button", { name: "亮色" }));

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe("light");
      expect(
        document.head.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
          ?.content,
      ).toBe("#ffffff");
      expect(
        screen.getByRole("button", { name: "亮色" }).getAttribute(
          "aria-pressed",
        ),
      ).toBe("true");
      expect(
        screen.getByRole("button", { name: "暗色" }).getAttribute(
          "aria-pressed",
        ),
      ).toBe("false");
      expect(
        (screen.getByRole("combobox", { name: "状态筛选" }) as HTMLSelectElement)
          .value,
      ).toBe("failed");
    });
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBeforeTheme);
    expect(ThemeSocket.instances).toHaveLength(socketCountBeforeTheme);

    fireEvent.click(screen.getByRole("button", { name: "暗色" }));
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("dark"),
    );
    expect(
      (screen.getByRole("combobox", { name: "状态筛选" }) as HTMLSelectElement)
        .value,
    ).toBe("failed");
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBeforeTheme);
    expect(ThemeSocket.instances).toHaveLength(socketCountBeforeTheme);
  });

  it("keeps an edited script through a button theme change", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/system/health") {
        return Promise.resolve(responseJson(healthResponse()));
      }
      if (path === "/api/projects/1") {
        return Promise.resolve(responseJson(projectResponse()));
      }
      if (path === "/api/episodes/1") {
        return Promise.resolve(responseJson(episodeResponse()));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountAt("/projects/1/episodes/1/script");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "编辑剧本" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "编辑剧本" }));
    const editor = screen.getByRole("textbox", { name: "剧本内容" });
    fireEvent.change(editor, { target: { value: "未保存的主题草稿" } });

    const fetchCountBeforeTheme = fetchMock.mock.calls.length;
    expect(ThemeSocket.instances).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "亮色" }));
    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe("light");
      expect(
        (screen.getByRole("textbox", { name: "剧本内容" }) as HTMLTextAreaElement)
          .value,
      ).toBe("未保存的主题草稿");
    });
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBeforeTheme);
    expect(ThemeSocket.instances).toHaveLength(1);
  });

  it("keeps one in-flight generation request and its response through a button theme change", async () => {
    const fetchMock = vi.mocked(fetch);
    const generation = deferred<Response>();
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/system/health") {
        return Promise.resolve(responseJson(healthResponse()));
      }
      if (path === "/api/projects/1") {
        return Promise.resolve(responseJson(projectResponse()));
      }
      if (path === "/api/episodes/1") {
        return Promise.resolve(responseJson(episodeResponse()));
      }
      if (path === "/api/episodes/1/generate-assets") {
        return generation.promise;
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountAt("/projects/1/episodes/1/script");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "编辑剧本" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "生成资产" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([input]) => requestPath(input) === "/api/episodes/1/generate-assets",
        ),
      ).toHaveLength(1),
    );
    const generationCall = fetchMock.mock.calls.find(
      ([input]) => requestPath(input) === "/api/episodes/1/generate-assets",
    );
    expect(generationCall?.[1]).toMatchObject({ method: "POST" });
    expect((generationCall?.[1] as RequestInit | undefined)?.body).toBeUndefined();
    const fetchCountBeforeTheme = fetchMock.mock.calls.length;
    expect(ThemeSocket.instances).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "亮色" }));
    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe("light");
      expect(
        (screen.getByRole("button", { name: "提交生成任务…" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true);
    });
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBeforeTheme);
    expect(ThemeSocket.instances).toHaveLength(1);

    generation.resolve(responseJson({ task_id: 42 }));
    await waitFor(() =>
      expect(screen.getByText(/资产生成任务已提交：#42/)).toBeTruthy(),
    );
    expect(
      fetchMock.mock.calls.filter(
        ([input]) => requestPath(input) === "/api/episodes/1/generate-assets",
      ),
    ).toHaveLength(1);
  });
});
