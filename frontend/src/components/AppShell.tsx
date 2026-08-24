import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { ApiError, getHealth } from "../api";
import { BackendStatus, type BackendState } from "./BackendStatus";

const navigation = [
  { label: "项目", to: "/" },
  { label: "设置", to: "/settings" },
  { label: "任务中心", to: "/tasks" },
];

export function AppShell() {
  const [backendState, setBackendState] = useState<BackendState>({
    status: "loading",
  });

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
          setBackendState({
            status: "error",
            message: getConnectionErrorMessage(error),
          });
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
        <nav aria-label="主导航">
          {navigation.map((item) => (
            <NavLink
              className={({ isActive }) =>
                isActive ? "nav-link nav-link-active" : "nav-link"
              }
              end={item.to === "/"}
              key={item.to}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <BackendStatus state={backendState} />
      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
}

function getConnectionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof TypeError) {
    return "无法连接后端";
  }
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  return "无法连接后端";
}
