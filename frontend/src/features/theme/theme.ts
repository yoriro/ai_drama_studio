export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "ai-drama-studio.theme";

const THEME_COLORS: Record<Theme, string> = {
  dark: "#0a0a0c",
  light: "#ffffff",
};

const INVALID_THEME_MESSAGE = "主题设置无效，请重新选择";
const READ_THEME_ERROR_MESSAGE = "无法读取主题设置，本次使用暗色";
const WRITE_THEME_ERROR_MESSAGE = "主题已切换，但无法保存到此浏览器";

let initializationNotice: string | null = null;

export interface ThemeInitialization {
  theme: Theme;
  notice: string | null;
}

export interface ThemeChange {
  theme: Theme;
  notice: string | null;
}

export function isTheme(value: string | null | undefined): value is Theme {
  return value === "dark" || value === "light";
}

export function getDocumentTheme(): Theme {
  const value = document.documentElement.dataset.theme;
  return isTheme(value) ? value : "dark";
}

export function getThemeInitializationNotice(): string | null {
  return initializationNotice;
}

export function initializeTheme(): ThemeInitialization {
  let theme: Theme = "dark";
  let notice: string | null = null;

  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored !== null && stored !== "") {
      if (isTheme(stored)) {
        theme = stored;
      } else {
        notice = INVALID_THEME_MESSAGE;
      }
    }
  } catch (error: unknown) {
    if (!isDomException(error)) {
      throw error;
    }
    notice = READ_THEME_ERROR_MESSAGE;
  }

  applyTheme(theme);
  initializationNotice = notice;
  return { theme, notice };
}

export function setThemePreference(theme: Theme): ThemeChange {
  applyTheme(theme);

  let notice: string | null = null;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (error: unknown) {
    if (!isDomException(error)) {
      throw error;
    }
    notice = WRITE_THEME_ERROR_MESSAGE;
  }

  return { theme, notice };
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  const themeColor = document.head.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  if (themeColor === null) {
    throw new Error('Missing meta[name="theme-color"]');
  }
  themeColor.content = THEME_COLORS[theme];
}

function isDomException(error: unknown): error is DOMException {
  return typeof DOMException !== "undefined" && error instanceof DOMException;
}
