// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getThemeInitializationNotice,
  initializeTheme,
  setThemePreference,
} from "./theme";

function themeColorMeta(): HTMLMetaElement {
  const meta = document.head.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  if (meta === null) {
    throw new Error("theme-color meta is missing from the test document");
  }
  return meta;
}

beforeEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  document.head.innerHTML = '<meta name="theme-color" content="">';
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("theme preference", () => {
  it("defaults to dark when there is no stored preference", () => {
    expect(initializeTheme()).toEqual({ theme: "dark", notice: null });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeColorMeta().content).toBe("#0a0a0c");
    expect(getThemeInitializationNotice()).toBeNull();
  });

  it.each(["dark", "light"] as const)(
    "applies the exact stored %s preference",
    (theme) => {
      window.localStorage.setItem("ai-drama-studio.theme", theme);

      expect(initializeTheme()).toEqual({ theme, notice: null });
      expect(document.documentElement.dataset.theme).toBe(theme);
      expect(themeColorMeta().content).toBe(
        theme === "dark" ? "#0a0a0c" : "#ffffff",
      );
    },
  );

  it("uses dark and exposes a notice for an invalid stored value", () => {
    window.localStorage.setItem("ai-drama-studio.theme", "sepia");

    expect(initializeTheme()).toEqual({
      theme: "dark",
      notice: "主题设置无效，请重新选择",
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeColorMeta().content).toBe("#0a0a0c");
  });

  it("uses dark and exposes the required notice for a read DOMException", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(initializeTheme()).toEqual({
      theme: "dark",
      notice: "无法读取主题设置，本次使用暗色",
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeColorMeta().content).toBe("#0a0a0c");
  });

  it("applies the selected theme and exposes the required notice for a write DOMException", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });

    expect(setThemePreference("light")).toEqual({
      theme: "light",
      notice: "主题已切换，但无法保存到此浏览器",
    });
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(themeColorMeta().content).toBe("#ffffff");
  });

  it("propagates an unknown storage error", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("unexpected storage failure");
    });

    expect(() => initializeTheme()).toThrow("unexpected storage failure");
  });
});
