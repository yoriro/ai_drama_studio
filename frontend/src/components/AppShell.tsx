import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { ApiError, getHealth } from "../api";
import { getAuxiliaryNavigationState } from "../features/navigation/returnLocation";
import {
  getDocumentTheme,
  getThemeInitializationNotice,
  setThemePreference,
  type Theme,
} from "../features/theme/theme";
import { BackendStatus, type BackendState } from "./BackendStatus";
import { ThemeSwitch } from "./ThemeSwitch";

const navigation = [
  { label: "项目", to: "/" },
  { label: "设置", to: "/settings" },
  { label: "任务中心", to: "/tasks" },
];

export function AppShell() {
  const location = useLocation();
  const [theme, setTheme] = useState<Theme>(() => getDocumentTheme());
  const [themeNotice, setThemeNotice] = useState<string | null>(() =>
    getThemeInitializationNotice(),
  );
  const [backendState, setBackendState] = useState<BackendState>({
    status: "loading",
  });

  function handleThemeChange(nextTheme: Theme): void {
    if (nextTheme === theme) {
      return;
    }
    const change = setThemePreference(nextTheme);
    setTheme(change.theme);
    setThemeNotice(change.notice);
  }

  useEffect(() => {
    let disposed = false;

    void getHealth().then(
      (health) => {
        if (!disposed) {
          setBackendState({ status: "connected", health });
        }
      },
      (error: unknown) => {
        if (!disposed) {
          setBackendState({ status: "error", ...getConnectionError(error) });
        }
      },
    );

    return () => {
      disposed = true;
    };
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink className="brand" to="/">
          AI Drama Studio
        </NavLink>
        <div className="app-header-actions">
          <ThemeSwitch
            notice={themeNotice}
            onThemeChange={handleThemeChange}
            theme={theme}
          />
          <nav aria-label="主导航">
            {navigation.map((item) => (
              <NavLink
                className={({ isActive }) =>
                  isActive ? "nav-link nav-link-active" : "nav-link"
                }
                end={item.to === "/"}
                key={item.to}
                state={
                  item.to === "/"
                    ? undefined
                    : getAuxiliaryNavigationState(location, location.state)
                }
                to={item.to}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <BackendStatus state={backendState} />
      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
}

function getConnectionError(error: unknown): { code: string; message: string } {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message };
  }
  if (error instanceof TypeError) {
    return { code: "connection_error", message: "无法连接后端" };
  }
  if (error instanceof Error && error.message.length > 0) {
    return { code: "client_error", message: error.message };
  }
  return { code: "connection_error", message: "无法连接后端" };
}
