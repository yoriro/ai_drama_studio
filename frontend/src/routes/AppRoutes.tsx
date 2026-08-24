import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { HomePage } from "../pages/HomePage";
import { EpisodeWorkspacePage } from "../pages/EpisodeWorkspacePage";
import { ProjectPage } from "../pages/ProjectPage";
import { SettingsPage } from "../pages/SettingsPage";
import { TasksPage } from "../pages/TasksPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="projects/:projectId" element={<ProjectPage />} />
        <Route
          path="projects/:projectId/episodes/:episodeId"
          element={<Navigate replace to="script" />}
        />
        <Route
          path="projects/:projectId/episodes/:episodeId/script"
          element={<EpisodeWorkspacePage activeTab="script" />}
        />
        <Route
          path="projects/:projectId/episodes/:episodeId/assets"
          element={<EpisodeWorkspacePage activeTab="assets" />}
        />
        <Route
          path="projects/:projectId/episodes/:episodeId/shots"
          element={<EpisodeWorkspacePage activeTab="shots" />}
        />
        <Route
          path="projects/:projectId/episodes/:episodeId/director"
          element={<EpisodeWorkspacePage activeTab="director" />}
        />
      </Route>
    </Routes>
  );
}
