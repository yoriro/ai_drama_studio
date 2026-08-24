import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  createProject,
  deleteProject,
  listProjects,
  listStyles,
  updateProject,
} from "../api";
import type { Project, Style } from "../api";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

export function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [styles, setStyles] = useState<Style[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [projectName, setProjectName] = useState("");
  const [styleId, setStyleId] = useState("");
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");
  const [editingStyleId, setEditingStyleId] = useState("");

  useEffect(() => {
    let disposed = false;
    void Promise.all([listProjects(), listStyles()]).then(
      ([loadedProjects, loadedStyles]) => {
        if (disposed) {
          return;
        }
        setProjects(loadedProjects);
        setStyles(loadedStyles);
        setStyleId((current) => current || String(loadedStyles[0]?.id ?? ""));
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
  }, []);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError(null);
    try {
      const created = await createProject({
        name: projectName,
        style_id: Number(styleId),
      });
      setProjects((current) => [...current, created]);
      setProjectName("");
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  function startEditing(project: Project) {
    setActionError(null);
    setEditingProjectId(project.id);
    setEditingName(project.name);
    setEditingStyleId(String(project.style_id));
  }

  async function handleUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingProjectId === null) {
      return;
    }
    setActionError(null);
    try {
      const updated = await updateProject(editingProjectId, {
        name: editingName,
        style_id: Number(editingStyleId),
      });
      setProjects((current) =>
        current.map((project) => (project.id === updated.id ? updated : project)),
      );
      setEditingProjectId(null);
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  async function handleDelete(project: Project) {
    if (!window.confirm(`确认删除项目“${project.name}”及其剧集吗？`)) {
      return;
    }
    setActionError(null);
    try {
      await deleteProject(project.id);
      setProjects((current) => current.filter((item) => item.id !== project.id));
      if (editingProjectId === project.id) {
        setEditingProjectId(null);
      }
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  if (loadState === "loading") {
    return (
      <>
        <PageTitle>项目首页</PageTitle>
        <p>正在加载项目与风格…</p>
      </>
    );
  }

  if (loadState === "error") {
    return (
      <>
        <PageTitle>项目首页</PageTitle>
        <ApiErrorMessage error={loadError} />
      </>
    );
  }

  return (
    <>
      <PageTitle>项目首页</PageTitle>
      {actionError !== null && <ApiErrorMessage error={actionError} />}
      <section className="panel">
        <h2>创建项目</h2>
        {styles.length === 0 ? (
          <p>
            暂无可用风格，请先前往 <Link to="/settings">设置</Link> 创建风格。
          </p>
        ) : (
          <form className="form-grid" onSubmit={handleCreate}>
            <label>
              项目名称
              <input
                required
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
              />
            </label>
            <label>
              风格
              <select
                required
                value={styleId}
                onChange={(event) => setStyleId(event.target.value)}
              >
                {styles.map((style) => (
                  <option key={style.id} value={style.id}>
                    {style.name}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit">创建项目</button>
          </form>
        )}
      </section>
      {projects.length === 0 ? (
        <EmptyState message="暂无项目" />
      ) : (
        <section className="entity-list" aria-label="项目列表">
          {projects.map((project) => (
            <article className="entity-card" key={project.id}>
              <Link to={`/projects/${project.id}`}>
                <h2>{project.name}</h2>
              </Link>
              <p>风格 ID：{project.style_id}</p>
              <div className="action-row">
                <button type="button" onClick={() => startEditing(project)}>
                  编辑
                </button>
                <button type="button" onClick={() => void handleDelete(project)}>
                  删除
                </button>
              </div>
              {editingProjectId === project.id && (
                <form className="form-grid" onSubmit={handleUpdate}>
                  <label>
                    项目名称
                    <input
                      required
                      value={editingName}
                      onChange={(event) => setEditingName(event.target.value)}
                    />
                  </label>
                  <label>
                    风格
                    <select
                      required
                      value={editingStyleId}
                      onChange={(event) => setEditingStyleId(event.target.value)}
                    >
                      {styles.map((style) => (
                        <option key={style.id} value={style.id}>
                          {style.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="action-row">
                    <button type="submit">保存项目</button>
                    <button
                      type="button"
                      onClick={() => setEditingProjectId(null)}
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
