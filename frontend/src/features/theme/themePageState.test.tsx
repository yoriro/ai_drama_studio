// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useLocation, MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../routes/AppRoutes";
import { initializeTheme } from "./theme";

const fetchMock = vi.fn<typeof fetch>();

function responseJson(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestPath(input: RequestInfo | URL): string {
  const url = new URL(String(input), "http://localhost");
  return url.pathname + url.search;
}

function requestMethod(init: RequestInit | undefined): string {
  return init?.method ?? "GET";
}

function healthResponse(): unknown {
  return {
    vllm: { status: "healthy", message: null },
    comfy: { status: "healthy", message: null },
    workflow_bindings: {
      status: "valid",
      message: null,
      hashes: { zimage: "a".repeat(64), minimaxh3: "b".repeat(64) },
    },
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

function assetResponse(): unknown {
  return {
    id: 101,
    project_id: 1,
    type: "character",
    name: "主题角色",
    description: "角色描述",
    source: "manual",
    revision: 1,
    created_at: "2026-09-08T00:00:00Z",
    updated_at: "2026-09-08T00:00:00Z",
  };
}

function shotResponse(id: number, orderIndex: number): unknown {
  return {
    id,
    episode_id: 1,
    order_index: orderIndex,
    duration_est: 2,
    shot_type: "中景",
    camera: "固定",
    description: `镜头${orderIndex}描述`,
    dialogue: "",
    asset_ids: [101],
    status: "normal",
    revision: 1,
    created_at: "2026-09-08T00:00:00Z",
    updated_at: "2026-09-08T00:00:00Z",
  };
}

function clipResponse(): unknown {
  return {
    id: 7,
    episode_id: 1,
    generation_mode: "ref2v",
    user_note: null,
    requested_duration: 5,
    generation_state: "ready",
    freshness: "fresh",
    revision: 1,
    shot_ids: [1],
    start_order_index: 1,
    end_order_index: 1,
    enabled_slot_count: 1,
    warnings: [],
    created_at: "2026-09-08T00:00:00Z",
    updated_at: "2026-09-08T00:00:00Z",
  };
}

function clipSlotResponse(): unknown {
  return {
    id: 9,
    clip_id: 7,
    slot_no: 1,
    asset_id: 101,
    asset_name_snapshot: "主题角色",
    asset_type_snapshot: "character",
    asset_deleted: false,
    enabled: true,
    image_source: "asset_current",
    image_url: "/media/asset-images/101",
  };
}

class ThemePageSocket {
  static instances: ThemePageSocket[] = [];

  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    ThemePageSocket.instances.push(this);
    queueMicrotask(() => this.onopen?.({} as Event));
  }

  close(): void {
    this.onclose?.({} as CloseEvent);
  }
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="theme-page-location">
      {location.pathname + location.search + location.hash}
    </output>
  );
}

function mountAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
      <LocationProbe />
    </MemoryRouter>,
  );
}

function installCommonRoutes(): void {
  fetchMock.mockImplementation(async (input, init) => {
    const path = requestPath(input);
    const method = requestMethod(init);
    if (method === "GET" && path === "/api/system/health") {
      return responseJson(healthResponse());
    }
    if (method === "GET" && path === "/api/projects/1") {
      return responseJson(projectResponse());
    }
    if (method === "GET" && path === "/api/episodes/1") {
      return responseJson(episodeResponse());
    }
    throw new Error(`unexpected request ${method} ${path}`);
  });
}

function installAssetRoutes(): void {
  installCommonRoutes();
  fetchMock.mockImplementation(async (input, init) => {
    const path = requestPath(input);
    const method = requestMethod(init);
    if (method === "GET" && path === "/api/system/health") {
      return responseJson(healthResponse());
    }
    if (method === "GET" && path === "/api/projects/1") {
      return responseJson(projectResponse());
    }
    if (method === "GET" && path === "/api/episodes/1") {
      return responseJson(episodeResponse());
    }
    if (method === "GET" && path === "/api/projects/1/assets") {
      return responseJson([assetResponse()]);
    }
    if (method === "GET" && path === "/api/assets/101/images") {
      return responseJson([]);
    }
    throw new Error(`unexpected request ${method} ${path}`);
  });
}

function installDirectorRoutes(): void {
  installCommonRoutes();
  fetchMock.mockImplementation(async (input, init) => {
    const path = requestPath(input);
    const method = requestMethod(init);
    if (method === "GET" && path === "/api/system/health") {
      return responseJson(healthResponse());
    }
    if (method === "GET" && path === "/api/projects/1") {
      return responseJson(projectResponse());
    }
    if (method === "GET" && path === "/api/episodes/1") {
      return responseJson(episodeResponse());
    }
    if (method === "GET" && path === "/api/projects/1/assets") {
      return responseJson([assetResponse()]);
    }
    if (method === "GET" && path === "/api/episodes/1/shots") {
      return responseJson([shotResponse(1, 1), shotResponse(2, 2)]);
    }
    if (method === "GET" && path === "/api/episodes/1/clips") {
      return responseJson([clipResponse()]);
    }
    if (method === "GET" && path === "/api/clips/7") {
      return responseJson(clipResponse());
    }
    if (method === "GET" && path === "/api/clips/7/slots") {
      return responseJson({ clip_id: 7, items: [clipSlotResponse()], warnings: [] });
    }
    if (method === "GET" && path === "/api/clips/7/videos") {
      return responseJson([]);
    }
    throw new Error(`unexpected request ${method} ${path}`);
  });
}

function expectNoWrites(): void {
  expect(
    fetchMock.mock.calls.filter(([, init]) => requestMethod(init) !== "GET"),
  ).toHaveLength(0);
}

beforeEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  document.head.innerHTML = '<meta name="theme-color" content="">';
  window.localStorage.clear();
  initializeTheme();
  ThemePageSocket.instances = [];
  vi.stubGlobal("WebSocket", ThemePageSocket);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("page state through theme changes", () => {
  it("keeps an AssetPage opinion draft, URL, history and request/socket counts", async () => {
    installAssetRoutes();
    mountAt("/projects/1/episodes/1/assets?source=t36#asset");

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "出图意见" })).toBeTruthy(),
    );
    const note = screen.getByRole("textbox", {
      name: "出图意见",
    }) as HTMLTextAreaElement;
    fireEvent.change(note, { target: { value: "未保存的资产意见" } });
    const locationBefore = screen.getByTestId("theme-page-location").textContent;
    const fetchCountBefore = fetchMock.mock.calls.length;
    const socketCountBefore = ThemePageSocket.instances.length;

    fireEvent.click(screen.getByRole("button", { name: "亮色" }));
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("light"),
    );
    expect(note.value).toBe("未保存的资产意见");
    expect(screen.getByTestId("theme-page-location").textContent).toBe(
      locationBefore,
    );
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBefore);
    expect(ThemePageSocket.instances).toHaveLength(socketCountBefore);

    fireEvent.click(screen.getByRole("button", { name: "暗色" }));
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("dark"),
    );
    expect(note.value).toBe("未保存的资产意见");
    expect(screen.getByTestId("theme-page-location").textContent).toBe(
      locationBefore,
    );
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBefore);
    expect(ThemePageSocket.instances).toHaveLength(socketCountBefore);
    expectNoWrites();
  });

  it("keeps Director shot selection through a button theme change", async () => {
    installDirectorRoutes();
    mountAt("/projects/1/episodes/1/director?source=t36#shot");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Clip #7/ })).toBeTruthy(),
    );
    const shotCheckbox = screen.getByRole("checkbox", {
      name: "镜头 2",
    }) as HTMLInputElement;
    fireEvent.click(shotCheckbox);
    await waitFor(() => expect(shotCheckbox.checked).toBe(true));
    const locationBefore = screen.getByTestId("theme-page-location").textContent;
    const fetchCountBefore = fetchMock.mock.calls.length;
    const socketCountBefore = ThemePageSocket.instances.length;

    fireEvent.click(screen.getByRole("button", { name: "亮色" }));
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("light"),
    );
    expect(shotCheckbox.checked).toBe(true);
    expect(screen.getByTestId("theme-page-location").textContent).toBe(
      locationBefore,
    );
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBefore);
    expect(ThemePageSocket.instances).toHaveLength(socketCountBefore);

    fireEvent.click(screen.getByRole("button", { name: "暗色" }));
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("dark"),
    );
    expect(shotCheckbox.checked).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBefore);
    expect(ThemePageSocket.instances).toHaveLength(socketCountBefore);
    expectNoWrites();
  });

  it("keeps Director Clip opinion, selection and local scroll through theme changes", async () => {
    installDirectorRoutes();
    mountAt("/projects/1/episodes/1/director?source=t36#clip");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Clip #7/ })).toBeTruthy(),
    );
    const clipButton = screen.getByRole("button", { name: /Clip #7/ });
    fireEvent.click(clipButton);
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "片段意见" })).toBeTruthy(),
    );
    const note = screen.getByRole("textbox", {
      name: "片段意见",
    }) as HTMLTextAreaElement;
    fireEvent.change(note, { target: { value: "未保存的片段意见" } });
    const trackScroll = document.querySelector(
      ".director-track-scroll",
    ) as HTMLDivElement | null;
    expect(trackScroll).not.toBeNull();
    trackScroll!.scrollLeft = 137;
    expect(clipButton.getAttribute("aria-pressed")).toBe("true");
    const locationBefore = screen.getByTestId("theme-page-location").textContent;
    const fetchCountBefore = fetchMock.mock.calls.length;
    const socketCountBefore = ThemePageSocket.instances.length;

    fireEvent.click(screen.getByRole("button", { name: "亮色" }));
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("light"),
    );
    expect(note.value).toBe("未保存的片段意见");
    expect(clipButton.getAttribute("aria-pressed")).toBe("true");
    expect(trackScroll!.scrollLeft).toBe(137);
    expect(screen.getByTestId("theme-page-location").textContent).toBe(
      locationBefore,
    );
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBefore);
    expect(ThemePageSocket.instances).toHaveLength(socketCountBefore);

    fireEvent.click(screen.getByRole("button", { name: "暗色" }));
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("dark"),
    );
    expect(note.value).toBe("未保存的片段意见");
    expect(clipButton.getAttribute("aria-pressed")).toBe("true");
    expect(trackScroll!.scrollLeft).toBe(137);
    expect(fetchMock).toHaveBeenCalledTimes(fetchCountBefore);
    expect(ThemePageSocket.instances).toHaveLength(socketCountBefore);
    expectNoWrites();
  });
});
