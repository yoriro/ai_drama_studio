import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  createEpisode,
  deleteEpisode,
  getProject,
  listEpisodes,
  updateEpisode,
} from "../api";
import type { Episode, Project } from "../api";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const numericProjectId = Number(projectId);
  const [project, setProject] = useState<Project | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [episodeSeq, setEpisodeSeq] = useState("");
  const [episodeTitle, setEpisodeTitle] = useState("");
  const [editingEpisodeId, setEditingEpisodeId] = useState<number | null>(null);
  const [editingSeq, setEditingSeq] = useState("");
  const [editingTitle, setEditingTitle] = useState("");

  useEffect(() => {
    if (!Number.isInteger(numericProjectId) || numericProjectId <= 0) {
      setLoadError(new Error("项目 ID 无效"));
      setLoadState("error");
      return;
    }
    let disposed = false;
    void Promise.all([getProject(numericProjectId), listEpisodes(numericProjectId)]).then(
      ([loadedProject, loadedEpisodes]) => {
        if (!disposed) {
          setProject(loadedProject);
          setEpisodes(loadedEpisodes);
          setLoadState("ready");
        }
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
  }, [numericProjectId]);

  async function handleCreateEpisode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError(null);
    try {
      const created = await createEpisode(numericProjectId, {
        seq: Number(episodeSeq),
        title: episodeTitle,
      });
      setEpisodes((current) =>
        [...current, created].sort((left, right) =>
          left.seq === right.seq ? left.id - right.id : left.seq - right.seq,
        ),
      );
      setEpisodeSeq("");
      setEpisodeTitle("");
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  function startEditingEpisode(episode: Episode) {
    setActionError(null);
    setEditingEpisodeId(episode.id);
    setEditingSeq(String(episode.seq));
    setEditingTitle(episode.title);
  }

  async function handleUpdateEpisode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingEpisodeId === null) {
      return;
    }
    setActionError(null);
    try {
      const updated = await updateEpisode(editingEpisodeId, {
        seq: Number(editingSeq),
        title: editingTitle,
      });
      setEpisodes((current) =>
        [...current.map((episode) =>
          episode.id === updated.id ? updated : episode,
        )].sort((left, right) =>
          left.seq === right.seq ? left.id - right.id : left.seq - right.seq,
        ),
      );
      setEditingEpisodeId(null);
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  async function handleDeleteEpisode(episode: Episode) {
    if (!window.confirm(`确认删除第 ${episode.seq} 集“${episode.title}”吗？`)) {
      return;
    }
    setActionError(null);
    try {
      await deleteEpisode(episode.id);
      setEpisodes((current) => current.filter((item) => item.id !== episode.id));
      if (editingEpisodeId === episode.id) {
        setEditingEpisodeId(null);
      }
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  if (loadState === "loading") {
    return (
      <>
        <PageTitle>项目详情</PageTitle>
        <p>正在加载项目与剧集…</p>
      </>
    );
  }

  if (loadState === "error" || project === null) {
    return (
      <>
        <PageTitle>项目详情</PageTitle>
        <ApiErrorMessage error={loadError ?? new Error("项目不存在")} />
      </>
    );
  }

  return (
    <>
      <PageTitle>项目详情</PageTitle>
      <p>
        <Link className="button-link" to="/">
          返回项目首页
        </Link>
      </p>
      <p>项目 ID：{project.id} · 风格 ID：{project.style_id}</p>
      {actionError !== null && <ApiErrorMessage error={actionError} />}
      <section className="panel">
        <h2>创建剧集</h2>
        <form className="form-grid" onSubmit={handleCreateEpisode}>
          <label>
            集序
            <input
              min="1"
              required
              type="number"
              value={episodeSeq}
              onChange={(event) => setEpisodeSeq(event.target.value)}
            />
          </label>
          <label>
            集标题
            <input
              required
              value={episodeTitle}
              onChange={(event) => setEpisodeTitle(event.target.value)}
            />
          </label>
          <button type="submit">创建剧集</button>
        </form>
      </section>
      {episodes.length === 0 ? (
        <EmptyState message="暂无剧集" />
      ) : (
        <section className="entity-list" aria-label="剧集列表">
          {episodes.map((episode) => (
            <article className="entity-card" key={episode.id}>
              <Link
                to={`/projects/${project.id}/episodes/${episode.id}/script`}
              >
                <h2>
                  第 {episode.seq} 集 · {episode.title}
                </h2>
              </Link>
              <p>剧本修订：{episode.script_revision}</p>
              <div className="action-row">
                <button type="button" onClick={() => startEditingEpisode(episode)}>
                  编辑集信息
                </button>
                <button
                  type="button"
                  onClick={() => void handleDeleteEpisode(episode)}
                >
                  删除剧集
                </button>
              </div>
              {editingEpisodeId === episode.id && (
                <form className="form-grid" onSubmit={handleUpdateEpisode}>
                  <label>
                    集序
                    <input
                      min="1"
                      required
                      type="number"
                      value={editingSeq}
                      onChange={(event) => setEditingSeq(event.target.value)}
                    />
                  </label>
                  <label>
                    集标题
                    <input
                      required
                      value={editingTitle}
                      onChange={(event) => setEditingTitle(event.target.value)}
                    />
                  </label>
                  <div className="action-row">
                    <button type="submit">保存集信息</button>
                    <button
                      type="button"
                      onClick={() => setEditingEpisodeId(null)}
                    >
                      取消
                    </button>
                  </div>
                </form>
              )}
            </article>
          ))}
        </section>
      )}
    </>
  );
}
