import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  { label: "项目", to: "/" },
  { label: "设置", to: "/settings" },
  { label: "任务中心", to: "/tasks" },
];

export function AppShell() {
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
      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
}
