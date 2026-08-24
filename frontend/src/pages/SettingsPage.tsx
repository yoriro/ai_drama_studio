import { FormEvent, useEffect, useState } from "react";

import {
  createStyle,
  deleteStyle,
  listPromptTemplates,
  listStyles,
  updatePromptTemplate,
  updateStyle,
} from "../api";
import type { PromptTemplate, Style } from "../api";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

export function SettingsPage() {
  const [styles, setStyles] = useState<Style[]>([]);
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [templateDrafts, setTemplateDrafts] = useState<Record<string, string>>(
    {},
  );
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [styleName, setStyleName] = useState("");
  const [stylePrompt, setStylePrompt] = useState("");
  const [editingStyleId, setEditingStyleId] = useState<number | null>(null);
  const [editingStyleName, setEditingStyleName] = useState("");
  const [editingStylePrompt, setEditingStylePrompt] = useState("");
  const [savingTemplateKey, setSavingTemplateKey] = useState<string | null>(
    null,
  );

  useEffect(() => {
    let disposed = false;
    void Promise.all([listStyles(), listPromptTemplates()]).then(
      ([loadedStyles, loadedTemplates]) => {
        if (disposed) {
          return;
        }
        setStyles(loadedStyles);
        setTemplates(loadedTemplates);
        setTemplateDrafts(
          Object.fromEntries(
            loadedTemplates.map((template) => [template.key, template.content]),
          ),
        );
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

  async function handleCreateStyle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError(null);
    try {
      const created = await createStyle({
        name: styleName,
        prompt_fragment: stylePrompt,
      });
      setStyles((current) => [...current, created]);
      setStyleName("");
      setStylePrompt("");
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  function startEditingStyle(style: Style) {
    setActionError(null);
    setEditingStyleId(style.id);
    setEditingStyleName(style.name);
    setEditingStylePrompt(style.prompt_fragment);
  }

  async function handleUpdateStyle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingStyleId === null) {
      return;
    }
    setActionError(null);
    try {
      const updated = await updateStyle(editingStyleId, {
        name: editingStyleName,
        prompt_fragment: editingStylePrompt,
      });
      setStyles((current) =>
        current.map((style) => (style.id === updated.id ? updated : style)),
      );
      setEditingStyleId(null);
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  async function handleDeleteStyle(style: Style) {
    if (!window.confirm(`确认删除风格“${style.name}”吗？`)) {
      return;
    }
    setActionError(null);
    try {
      await deleteStyle(style.id);
      setStyles((current) => current.filter((item) => item.id !== style.id));
      if (editingStyleId === style.id) {
        setEditingStyleId(null);
      }
    } catch (error: unknown) {
      setActionError(error);
    }
  }

  async function handleUpdateTemplate(
    event: FormEvent<HTMLFormElement>,
    template: PromptTemplate,
  ) {
    event.preventDefault();
    setActionError(null);
    setSavingTemplateKey(template.key);
    try {
      const updated = await updatePromptTemplate(template.key, {
        content: templateDrafts[template.key] ?? template.content,
      });
      setTemplates((current) =>
        current.map((item) => (item.key === updated.key ? updated : item)),
      );
      setTemplateDrafts((current) => ({
        ...current,
        [updated.key]: updated.content,
      }));
    } catch (error: unknown) {
      setActionError(error);
    } finally {
      setSavingTemplateKey(null);
    }
  }

  if (loadState === "loading") {
    return (
      <>
        <PageTitle>设置</PageTitle>
        <p>正在加载风格与提示词模板…</p>
      </>
    );
  }

  if (loadState === "error") {
    return (
      <>
        <PageTitle>设置</PageTitle>
        <ApiErrorMessage error={loadError} />
      </>
    );
  }

  return (
    <>
      <PageTitle>设置</PageTitle>
      {actionError !== null && <ApiErrorMessage error={actionError} />}
      <section className="settings-section" aria-labelledby="styles-heading">
        <h2 id="styles-heading">风格</h2>
        <form className="panel form-grid" onSubmit={handleCreateStyle}>
          <h3>创建风格</h3>
          <label>
            风格名称
            <input
              required
              value={styleName}
              onChange={(event) => setStyleName(event.target.value)}
            />
          </label>
          <label>
            风格提示片段
            <textarea
              required
              rows={4}
              value={stylePrompt}
              onChange={(event) => setStylePrompt(event.target.value)}
            />
          </label>
          <button type="submit">创建风格</button>
        </form>
        {styles.length === 0 ? (
          <EmptyState message="暂无风格" />
        ) : (
          <section className="entity-list" aria-label="风格列表">
            {styles.map((style) => (
              <article className="entity-card" key={style.id}>
                <h3>{style.name}</h3>
                <p className="settings-content">{style.prompt_fragment}</p>
                <div className="action-row">
                  <button type="button" onClick={() => startEditingStyle(style)}>
                    编辑风格
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDeleteStyle(style)}
                  >
                    删除风格
                  </button>
                </div>
                {editingStyleId === style.id && (
                  <form className="form-grid" onSubmit={handleUpdateStyle}>
                    <label>
                      风格名称
                      <input
                        required
                        value={editingStyleName}
                        onChange={(event) =>
                          setEditingStyleName(event.target.value)
                        }
                      />
                    </label>
                    <label>
                      风格提示片段
                      <textarea
                        required
                        rows={4}
                        value={editingStylePrompt}
                        onChange={(event) =>
                          setEditingStylePrompt(event.target.value)
                        }
                      />
                    </label>
                    <div className="action-row">
                      <button type="submit">保存风格</button>
                      <button
                        type="button"
                        onClick={() => setEditingStyleId(null)}
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
      </section>
      <section className="settings-section" aria-labelledby="templates-heading">
        <h2 id="templates-heading">提示词模板</h2>
        {templates.length === 0 ? (
          <EmptyState message="暂无提示词模板" />
        ) : (
          <section className="entity-list" aria-label="提示词模板列表">
            {templates.map((template) => (
              <form
                className="panel form-grid"
                key={template.key}
                onSubmit={(event) => void handleUpdateTemplate(event, template)}
              >
                <h3>{template.key}</h3>
                <label>
                  模板内容
                  <textarea
                    required
                    rows={6}
                    value={templateDrafts[template.key] ?? template.content}
                    onChange={(event) =>
                      setTemplateDrafts((current) => ({
                        ...current,
                        [template.key]: event.target.value,
                      }))
                    }
                  />
                </label>
                <button
                  disabled={savingTemplateKey === template.key}
                  type="submit"
                >
                  {savingTemplateKey === template.key ? "保存中…" : "保存模板"}
                </button>
              </form>
            ))}
          </section>
        )}
      </section>
    </>
  );
}
