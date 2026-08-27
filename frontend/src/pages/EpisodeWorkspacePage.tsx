import { FormEvent, useEffect, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";

import {
  generateAssets,
  generateShots,
  getEpisode,
  getProject,
  readGenerateShotsImpact,
  updateEpisode,
} from "../api";
import type { Episode, Project } from "../api";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";
import { AssetPage } from "./AssetPage";

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
  }, [activeTab, numericEpisodeId, numericProjectId]);

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
      <p>
        <Link className="button-link" to={`/projects/${context.project.id}`}>
          返回项目
        </Link>
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
      ) : activeTab === "assets" ? (
        <AssetPage episode={context.episode} projectId={context.project.id} />
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
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generationTaskId, setGenerationTaskId] = useState<number | null>(null);
  const [generationError, setGenerationError] = useState<unknown>(null);
  const [generatingShots, setGeneratingShots] = useState(false);
  const [shotGenerationTaskId, setShotGenerationTaskId] = useState<number | null>(
    null,
  );
  const [shotGenerationError, setShotGenerationError] = useState<unknown>(null);
  const [error, setError] = useState<unknown>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    setScriptText(episode.script_text);
  }, [episode.id, episode.script_text, episode.updated_at]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const updated = await updateEpisode(episode.id, { script_text: scriptText });
      onUpdated(updated);
      setEditing(false);
      setSuccessMessage(`剧本已保存，当前修订：${updated.script_revision}`);
    } catch (requestError: unknown) {
      setError(requestError);
      setSuccessMessage(null);
    } finally {
      setSaving(false);
    }
  }

  function handleStartEditing() {
    setEditing(true);
    setError(null);
    setSuccessMessage(null);
  }

  async function handleGenerateAssets() {
    setGenerating(true);
    setGenerationError(null);
    setGenerationTaskId(null);
    try {
      const result = await generateAssets(episode.id);
      setGenerationTaskId(result.task_id);
    } catch (requestError: unknown) {
      setGenerationError(requestError);
    } finally {
      setGenerating(false);
    }
  }

  async function handleGenerateShots() {
    setGeneratingShots(true);
    setShotGenerationError(null);
    setShotGenerationTaskId(null);
    try {
      const impact = await readGenerateShotsImpact(episode.id);
      let confirmToken: string | undefined;
      if (impact.clips_count !== 0 || impact.videos_count !== 0) {
        const confirmed = window.confirm(
          `将删除片段 ${impact.clips_count} 个\n将删除视频 ${impact.videos_count} 个\n确认生成分镜？`,
        );
        if (!confirmed) {
          return;
        }
        if (impact.confirm_token === null) {
          throw new Error("影响预检未返回确认 token");
        }
        confirmToken = impact.confirm_token;
      }
      const result = await generateShots(episode.id, confirmToken);
      setShotGenerationTaskId(result.task_id);
    } catch (requestError: unknown) {
      setShotGenerationError(requestError);
    } finally {
      setGeneratingShots(false);
    }
  }

  function handleCancelEditing() {
    setEditing(false);
    setScriptText(episode.script_text);
    setError(null);
    setSuccessMessage(null);
  }

  return (
    <section className="panel">
      <h2>剧本</h2>
      {error !== null && <ApiErrorMessage error={error} />}
      {successMessage !== null && (
        <p className="success-message" role="status">
          {successMessage}
        </p>
      )}
      {isAssetsStale(episode) && (
        <p className="field-hint">资产提取基于旧剧本</p>
      )}
      {!editing ? (
        <>
          <p className="field-hint">剧本修订：{episode.script_revision}</p>
          {episode.script_text.length === 0 ? (
            <EmptyState message="尚未保存剧本内容" />
          ) : (
            <div className="script-content">{episode.script_text}</div>
          )}
          <div className="action-row">
            <button type="button" onClick={handleStartEditing}>
              编辑剧本
            </button>
            <button
              disabled={generating}
              type="button"
              onClick={() => void handleGenerateAssets()}
            >
              {generating ? "提交生成任务…" : "生成资产"}
            </button>
            <button
              type="button"
              onClick={() => void handleGenerateShots()}
            >
              {generatingShots ? "检查分镜生成影响…" : "生成分镜"}
            </button>
          </div>
          {generationError !== null && (
            <ApiErrorMessage error={generationError} />
          )}
          {generationTaskId !== null && (
            <p className="success-message" role="status">
              资产生成任务已提交：#{generationTaskId}。{" "}
              <Link to="/tasks">前往任务中心</Link>
            </p>
          )}
          {shotGenerationError !== null && (
            <ApiErrorMessage error={shotGenerationError} />
          )}
          {shotGenerationTaskId !== null && (
            <p className="success-message" role="status">
              分镜生成任务已提交：#{shotGenerationTaskId}。{" "}
              <Link to="/tasks">前往任务中心</Link>
            </p>
          )}
        </>
      ) : (
        <form className="form-grid" onSubmit={handleSubmit}>
          <label>
            剧本内容
            <textarea
              rows={16}
              value={scriptText}
              onChange={(event) => {
                setScriptText(event.target.value);
                setSuccessMessage(null);
              }}
            />
          </label>
          <p className="field-hint">
            当前字符数：{Array.from(scriptText).length}
          </p>
          <div className="action-row">
            <button disabled={saving} type="submit">
              {saving ? "保存中…" : "保存剧本"}
            </button>
            <button
              disabled={saving}
              type="button"
              onClick={handleCancelEditing}
            >
              取消编辑
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function isAssetsStale(episode: Episode): boolean {
  return (
    episode.assets_generated_script_revision !== null &&
    episode.assets_generated_script_revision < episode.script_revision
  );
}
