import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  getEpisode,
  listAssets,
  listShots,
  updateShot,
} from "../api";
import type {
  Asset,
  CameraType,
  Episode,
  Shot,
  ShotPatch,
  ShotType,
} from "../api";
import { getTask } from "../api/tasks";
import {
  closeWebSocket,
  openTaskWebSocket,
  parseTaskEvent,
} from "../api/ws";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import { presentShotStatus } from "../features/status/statusPresentation";

const SHOT_TYPES: ShotType[] = ["远景", "全景", "中景", "近景", "特写"];
const CAMERA_TYPES: CameraType[] = ["固定", "推", "拉", "摇", "移", "跟", "手持"];

interface ShotsPageProps {
  episode: Episode;
  onEpisodeUpdated: (episode: Episode) => void;
  projectId: number;
}

type LoadState = "loading" | "error" | "ready";

interface ShotDraft {
  shot_type: ShotType;
  camera: CameraType;
  description: string;
  dialogue: string;
  asset_ids: number[];
}

export function ShotsPage({
  episode,
  onEpisodeUpdated,
  projectId,
}: ShotsPageProps) {
  const [shots, setShots] = useState<Shot[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<unknown>(null);

  const loadData = useCallback(async () => {
    const [loadedShots, loadedAssets] = await Promise.all([
      listShots(episode.id),
      listAssets(projectId),
    ]);
    return {
      shots: loadedShots,
      assets: loadedAssets.filter(
        (asset) =>
          asset.project_id === projectId &&
          (asset.type === "character" || asset.type === "scene"),
      ),
    };
  }, [episode.id, projectId]);

  const applyLoadedData = useCallback(
    (loaded: { shots: Shot[]; assets: Asset[] }) => {
      setShots(loaded.shots);
      setAssets(loaded.assets);
      setLoadError(null);
      setLoadState("ready");
    },
    [],
  );

  useEffect(() => {
    let disposed = false;
    setLoadState("loading");
    setLoadError(null);
    void loadData().then(
      (loaded) => {
        if (!disposed) {
          applyLoadedData(loaded);
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
  }, [applyLoadedData, episode.shots_generated_script_revision, episode.updated_at, loadData]);

  useEffect(() => {
    let disposed = false;
    const socket = openTaskWebSocket();

    socket.onmessage = (message: MessageEvent) => {
      if (typeof message.data !== "string") {
        throw new TypeError("Task WebSocket messages must be text");
      }
      const event = parseTaskEvent(message.data);
      if (
        event.type !== "gen_shots" ||
        (event.status !== "done" &&
          event.status !== "failed" &&
          event.status !== "canceled")
      ) {
        return;
      }

      void getTask(event.task_id).then(
        (task) => {
          if (
            disposed ||
            task.type !== "gen_shots" ||
            task.target_id !== episode.id
          ) {
            return;
          }
          void loadData().then(
            (loaded) => {
              if (!disposed) {
                applyLoadedData(loaded);
                void refreshEpisode(episode.id).then(
                  (updatedEpisode) => {
                    if (!disposed) {
                      onEpisodeUpdated(updatedEpisode);
                    }
                  },
                  (error: unknown) => {
                    if (!disposed) {
                      setLoadError(error);
                      setLoadState("error");
                    }
                  },
                );
              }
            },
            (error: unknown) => {
              if (!disposed) {
                setLoadError(error);
                setLoadState("error");
              }
            },
          );
        },
        (error: unknown) => {
          if (!disposed) {
            setLoadError(error);
            setLoadState("error");
          }
        },
      );
    };
    socket.onerror = () => {
      closeWebSocket(socket);
    };

    return () => {
      disposed = true;
      closeWebSocket(socket);
    };
  }, [applyLoadedData, episode.id, loadData, onEpisodeUpdated]);

  function handleSaved(updated: Shot): void {
    setShots((current) =>
      current.map((shot) => (shot.id === updated.id ? updated : shot)),
    );
  }

  if (loadState === "loading") {
    return (
      <section className="panel" aria-live="polite">
        <h2>分镜</h2>
        <p>正在加载分镜…</p>
      </section>
    );
  }

  if (loadState === "error") {
    return (
      <section className="panel">
        <h2>分镜</h2>
        <ApiErrorMessage error={loadError ?? new Error("分镜加载失败")} />
      </section>
    );
  }

  return (
    <section className="shots-page">
      <div className="panel shots-overview-panel">
        <div className="shots-heading">
          <div>
            <h2>分镜</h2>
            <p className="field-hint">按叙事顺序查看和编辑分镜</p>
            {isShotsStale(episode) && (
              <p className="field-hint">分镜基于旧剧本</p>
            )}
          </div>
        </div>
        {shots.length === 0 && <EmptyState message="暂无分镜" />}
      </div>
      {shots.length > 0 && (
        <div aria-label="分镜列表" className="shot-list">
          {shots.map((shot) => (
            <ShotCard
              assets={assets}
              key={shot.id}
              onSaved={handleSaved}
              shot={shot}
            />
          ))}
        </div>
      )}
    </section>
  );
}

async function refreshEpisode(episodeId: number): Promise<Episode> {
  return await getEpisode(episodeId);
}

interface ShotCardProps {
  assets: Asset[];
  onSaved: (shot: Shot) => void;
  shot: Shot;
}

function ShotCard({ assets, onSaved, shot }: ShotCardProps) {
  const [draft, setDraft] = useState<ShotDraft>(() => draftFromShot(shot));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    setDraft(draftFromShot(shot));
    setError(null);
    setSuccessMessage(null);
  }, [shot.id, shot.revision, shot.updated_at]);

  const sceneCount = draft.asset_ids.reduce(
    (count, assetId) =>
      count + (assets.some((asset) => asset.id === assetId && asset.type === "scene") ? 1 : 0),
    0,
  );
  const boundAssetNames = draft.asset_ids.map((assetId) => {
    const asset = assets.find((candidate) => candidate.id === assetId);
    return asset === undefined ? `资产 #${assetId}` : asset.name;
  });
  const statusBadge = presentShotStatus(shot.status);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSuccessMessage(null);
    const input: ShotPatch = {
      shot_type: draft.shot_type,
      camera: draft.camera,
      description: draft.description,
      dialogue: draft.dialogue,
      asset_ids: [...draft.asset_ids].sort((left, right) => left - right),
    };
    try {
      const updated = await updateShot(shot.id, input);
      setDraft(draftFromShot(updated));
      onSaved(updated);
      setSuccessMessage("分镜已保存");
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setSaving(false);
    }
  }

  function toggleAsset(assetId: number, checked: boolean): void {
    setDraft((current) => {
      const next = checked
        ? [...current.asset_ids, assetId]
        : current.asset_ids.filter((id) => id !== assetId);
      return {
        ...current,
        asset_ids: [...new Set(next)].sort((left, right) => left - right),
      };
    });
    setSuccessMessage(null);
  }

  return (
    <article className="panel shot-card">
      <div className="shot-card-heading">
        <div>
          <h3>镜头 {shot.order_index}</h3>
          <p className="shot-meta">时长：{shot.duration_est} 秒</p>
        </div>
        <div className="shot-badges">
          <span className="shot-status">状态：{shot.status}</span>
          {statusBadge !== null && (
            <span className={`shot-badge ${statusBadge.className}`}>
              {statusBadge.label}
            </span>
          )}
          {sceneCount === 0 && (
            <span className="shot-badge shot-badge-note">未绑定场景</span>
          )}
          {sceneCount >= 2 && (
            <span className="shot-badge shot-badge-warning">
              绑定多个场景，需修正
            </span>
          )}
        </div>
      </div>
      {error !== null && <ApiErrorMessage error={error} />}
      {successMessage !== null && (
        <p className="success-message" role="status">
          {successMessage}
        </p>
      )}
      <form className="form-grid shot-edit-form" onSubmit={handleSubmit}>
        <label>
          景别
          <select
            value={draft.shot_type}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                shot_type: event.target.value as ShotType,
              }));
              setSuccessMessage(null);
            }}
          >
            {SHOT_TYPES.map((shotType) => (
              <option key={shotType} value={shotType}>
                {shotType}
              </option>
            ))}
          </select>
        </label>
        <label>
          运镜
          <select
            value={draft.camera}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                camera: event.target.value as CameraType,
              }));
              setSuccessMessage(null);
            }}
          >
            {CAMERA_TYPES.map((camera) => (
              <option key={camera} value={camera}>
                {camera}
              </option>
            ))}
          </select>
        </label>
        <label>
          描述
          <textarea
            rows={4}
            value={draft.description}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                description: event.target.value,
              }));
              setSuccessMessage(null);
            }}
          />
        </label>
        <label>
          台词
          <textarea
            rows={3}
            value={draft.dialogue}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                dialogue: event.target.value,
              }));
              setSuccessMessage(null);
            }}
          />
        </label>
        <fieldset className="shot-assets">
          <legend>绑定资产</legend>
          <p className="field-hint">
            当前绑定：{boundAssetNames.length === 0 ? "无" : boundAssetNames.join("、")}
          </p>
          <div className="shot-asset-options">
            {assets.length === 0 ? (
              <p className="field-hint">暂无可绑定的角色或场景资产</p>
            ) : (
              assets.map((asset) => (
                <label className="shot-asset-option" key={asset.id}>
                  <input
                    checked={draft.asset_ids.includes(asset.id)}
                    type="checkbox"
                    onChange={(event) =>
                      toggleAsset(asset.id, event.target.checked)
                    }
                  />
                  <span>
                    {asset.name}（{asset.type === "character" ? "角色" : "场景"}）
                  </span>
                </label>
              ))
            )}
          </div>
        </fieldset>
        <div className="action-row shot-edit-actions">
          <button disabled={saving} type="submit">
            {saving ? "保存中…" : "保存分镜"}
          </button>
        </div>
      </form>
    </article>
  );
}

function draftFromShot(shot: Shot): ShotDraft {
  return {
    shot_type: shot.shot_type,
    camera: shot.camera,
    description: shot.description,
    dialogue: shot.dialogue,
    asset_ids: [...shot.asset_ids].sort((left, right) => left - right),
  };
}

function isShotsStale(episode: Episode): boolean {
  return (
    episode.shots_generated_script_revision !== null &&
    episode.shots_generated_script_revision < episode.script_revision
  );
}
