import { FormEvent, useEffect, useState } from "react";
import { NavLink, useParams } from "react-router-dom";

import { getEpisode, getProject, updateEpisode } from "../api";
import type { Episode, Project } from "../api";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
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
  const numericProjectId = Number(projectId);
  const numericEpisodeId = Number(episodeId);
  const [context, setContext] = useState<
    { project: Project; episode: Episode } | null
  >(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [loadError, setLoadError] = useState<unknown>(null);

  useEffect(() => {
    if (
      !Number.isInteger(numericProjectId) ||
      numericProjectId <= 0 ||
      !Number.isInteger(numericEpisodeId) ||
      numericEpisodeId <= 0
    ) {
      setLoadError(new Error("项目或集 ID 无效"));
      setLoadState("error");
      return;
    }
    let disposed = false;
    void Promise.all([getProject(numericProjectId), getEpisode(numericEpisodeId)]).then(
      ([project, episode]) => {
        if (disposed) {
          return;
        }
        if (episode.project_id !== project.id) {
          setLoadError(new Error("该集不属于当前项目，已禁止编辑"));
          setLoadState("error");
          return;
        }
        setContext({ project, episode });
        setLoadState("ready");
      },
      (error: unknown) => {
        if (!disposed) {
          setLoadError(error);
          setLoadState("error");
        }
      },
    );
    return () => {
      disposed = true;
    };
  }, [numericEpisodeId, numericProjectId]);

  if (loadState === "loading") {
    return (
      <>
        <PageTitle>集工作区</PageTitle>
        <p>正在加载项目与剧集…</p>
      </>
    );
  }

  if (loadState === "error" || context === null) {
    return (
      <>
        <PageTitle>集工作区</PageTitle>
        <ApiErrorMessage error={loadError ?? new Error("剧集不存在")} />
      </>
    );
  }

  return (
    <>
      <PageTitle>集工作区</PageTitle>
      <p>
        {context.project.name} · 第 {context.episode.seq} 集 · {context.episode.title}
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
      {activeTab === "script" ? (
        <ScriptEditor
          episode={context.episode}
          onUpdated={(episode) => setContext({ ...context, episode })}
        />
      ) : (
        <EmptyState
          message={`${tabs.find((tab) => tab.key === activeTab)?.label}页暂未交付`}
        />
      )}
    </>
  );
}

interface ScriptEditorProps {
  episode: Episode;
  onUpdated: (episode: Episode) => void;
}

function ScriptEditor({ episode, onUpdated }: ScriptEditorProps) {
  const [scriptText, setScriptText] = useState(episode.script_text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setScriptText(episode.script_text);
  }, [episode.id, episode.script_text, episode.updated_at]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const updated = await updateEpisode(episode.id, { script_text: scriptText });
      onUpdated(updated);
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel">
      <h2>剧本</h2>
      {error !== null && <ApiErrorMessage error={error} />}
      <form className="form-grid" onSubmit={handleSubmit}>
        <label>
          剧本内容
          <textarea
            rows={16}
            value={scriptText}
            onChange={(event) => setScriptText(event.target.value)}
          />
        </label>
        <p className="field-hint">
          当前字符数：{Array.from(scriptText).length}
        </p>
        <button disabled={saving} type="submit">
          {saving ? "保存中…" : "保存剧本"}
        </button>
      </form>
    </section>
  );
}
