// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "../../routes/AppRoutes";

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

function mountAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ProjectPage deleted-project return navigation", () => {
  it("shows the structured 404 and returns to the real home route without mutation", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/system/health") {
        return Promise.resolve(responseJson(healthResponse()));
      }
      if (path === "/api/projects/999") {
        return Promise.resolve(
          responseJson(
            { detail: { code: "project_not_found", message: "项目 999 不存在" } },
            404,
          ),
        );
      }
      if (path === "/api/projects/999/episodes") {
        return Promise.resolve(responseJson([]));
      }
      if (path === "/api/projects") {
        return Promise.resolve(responseJson([]));
      }
      if (path === "/api/styles") {
        return Promise.resolve(responseJson([]));
      }
      throw new Error(`unexpected request ${path}`);
    });

    mountAt("/projects/999");
    await waitFor(() =>
      expect(screen.getByText("项目 999 不存在")).toBeTruthy(),
    );

    const backLink = screen.getByRole("link", { name: "返回项目首页" });
    expect(backLink.getAttribute("href")).toBe("/");
    expect(backLink.getAttribute("title")).toBe("返回项目首页");
    expect(screen.getByRole("heading", { name: "项目详情" })).toBeTruthy();

    fireEvent.click(backLink);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "项目首页" })).toBeTruthy(),
    );
    expect(screen.queryByText("项目 999 不存在")).toBeNull();
    expect(
      fetchMock.mock.calls.some(([, init]) =>
        init?.method !== undefined && init.method !== "GET",
      ),
    ).toBe(false);
  });
});
