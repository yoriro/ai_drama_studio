import { NavLink, useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

type WorkspaceTab = "script" | "assets" | "shots" | "director";

interface EpisodeWorkspacePageProps {
  activeTab: WorkspaceTab;
}

const tabs: Array<{ key: WorkspaceTab; label: string }> = [
  { key: "script", label: "剧本" },
  { key: "assets", label: "资产" },
  { key: "shots", label: "分镜" },
  { key: "director", label: "导演台" },
];

export function EpisodeWorkspacePage({ activeTab }: EpisodeWorkspacePageProps) {
  const { projectId, episodeId } = useParams<{
    projectId: string;
    episodeId: string;
  }>();
  const basePath = `/projects/${projectId}/episodes/${episodeId}`;

  return (
    <>
      <PageTitle>集工作区</PageTitle>
      <p>
        项目 ID：{projectId ?? "未知"} · 集 ID：{episodeId ?? "未知"}
      </p>
      <nav aria-label="集工作区选项卡" className="workspace-tabs">
        {tabs.map((tab) => (
          <NavLink
            className={({ isActive }) =>
              isActive ? "workspace-tab workspace-tab-active" : "workspace-tab"
            }
            end
            key={tab.key}
            to={`${basePath}/${tab.key}`}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <EmptyState
        message={
          activeTab === "script"
            ? "剧本页壳已就绪，业务编辑将在后续任务接入。"
            : `${tabs.find((tab) => tab.key === activeTab)?.label}页暂未交付`
        }
      />
    </>
  );
}
