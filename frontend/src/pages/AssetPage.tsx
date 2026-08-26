import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import {
  createAsset,
  deleteAsset,
  deleteAssetImage,
  getAssetImageMediaUrl,
  listAssetImages,
  listAssets,
  setCurrentAssetImage,
  updateAsset,
  uploadAssetImage,
} from "../api";
import type {
  Asset,
  AssetCreate,
  AssetImage,
  AssetPatch,
  AssetType,
  Episode,
} from "../api";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";

interface AssetPageProps {
  episode: Episode;
  projectId: number;
}

interface AssetEntry {
  asset: Asset;
  images: AssetImage[];
}

type LoadState = "loading" | "error" | "ready";

export function AssetPage({ episode, projectId }: AssetPageProps) {
  const [entries, setEntries] = useState<AssetEntry[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  async function readEntries(): Promise<AssetEntry[]> {
    const assets = await listAssets(projectId);
    return await Promise.all(
      assets.map(async (asset) => ({
        asset,
        images: await listAssetImages(asset.id),
      })),
    );
  }

  useEffect(() => {
    let disposed = false;
    setLoadState("loading");
    setLoadError(null);
    void readEntries().then(
      (loadedEntries) => {
        if (!disposed) {
          setEntries(loadedEntries);
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
  }, [projectId]);

  async function refreshAssets(): Promise<void> {
    setRefreshing(true);
    setLoadError(null);
    try {
      const loadedEntries = await readEntries();
      setEntries(loadedEntries);
      setLoadState("ready");
    } catch (error: unknown) {
      setLoadError(error);
      if (entries.length === 0) {
        setLoadState("error");
      }
      throw error;
    } finally {
      setRefreshing(false);
    }
  }

  function handleCreated() {
    setCreateOpen(false);
    setSuccessMessage("资产已创建");
  }

  return (
    <section className="asset-page">
      <div className="panel">
        <div className="asset-page-heading">
          <div>
            <h2>资产</h2>
            <p className="field-hint">项目级角色与场景资产</p>
            {isAssetsStale(episode) && (
              <p className="field-hint">资产提取基于旧剧本</p>
            )}
          </div>
          {!createOpen && loadState === "ready" && (
            <button
              disabled={refreshing}
              type="button"
              onClick={() => {
                setCreateOpen(true);
                setSuccessMessage(null);
              }}
            >
              创建资产
            </button>
          )}
        </div>
        {successMessage !== null && (
          <p className="success-message" role="status">
            {successMessage}
          </p>
        )}
        {loadState === "loading" && <p>正在加载资产…</p>}
        {loadState === "error" && (
          <ApiErrorMessage error={loadError ?? new Error("资产加载失败")} />
        )}
        {loadState === "ready" && loadError !== null && (
          <ApiErrorMessage error={loadError} />
        )}
        {loadState === "ready" && createOpen && (
          <AssetCreateForm
            disabled={refreshing}
            onCancel={() => setCreateOpen(false)}
            onCreated={async () => {
              await refreshAssets();
              handleCreated();
            }}
            projectId={projectId}
          />
        )}
        {loadState === "ready" && entries.length === 0 && !createOpen && (
          <EmptyState message="暂无资产，创建第一个角色或场景" />
        )}
      </div>
      {loadState === "ready" && entries.length > 0 && (
        <div className="asset-list">
          {entries.map(({ asset, images }) => (
            <AssetCard
              asset={asset}
              images={images}
              key={asset.id}
              onChanged={refreshAssets}
              onDeleted={async () => {
                await refreshAssets();
                setSuccessMessage("资产已删除，全部图片已进入 trash");
              }}
            />
          ))}
        </div>
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

interface AssetCreateFormProps {
  disabled: boolean;
  onCancel: () => void;
  onCreated: () => Promise<void>;
  projectId: number;
}

function AssetCreateForm({
  disabled,
  onCancel,
  onCreated,
  projectId,
}: AssetCreateFormProps) {
  const [type, setType] = useState<AssetType>("character");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const input: AssetCreate = { type, name, description };
    try {
      await createAsset(projectId, input);
      await onCreated();
      setName("");
      setDescription("");
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form-grid asset-create-form" onSubmit={handleSubmit}>
      <h3>创建资产</h3>
      {error !== null && <ApiErrorMessage error={error} />}
      <label>
        类型
        <select
          disabled={disabled || saving}
          value={type}
          onChange={(event) => setType(event.target.value as AssetType)}
        >
          <option value="character">角色</option>
          <option value="scene">场景</option>
        </select>
      </label>
      <label>
        名称
        <input
          disabled={disabled || saving}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        描述
        <textarea
          disabled={disabled || saving}
          rows={4}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      <div className="action-row">
        <button disabled={disabled || saving} type="submit">
          {saving ? "创建中…" : "保存资产"}
        </button>
        <button disabled={saving} type="button" onClick={onCancel}>
          取消
        </button>
      </div>
    </form>
  );
}

interface AssetCardProps {
  asset: Asset;
  images: AssetImage[];
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
}

function AssetCard({ asset, images, onChanged, onDeleted }: AssetCardProps) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(asset.name);
  const [description, setDescription] = useState(asset.description);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [imageActionId, setImageActionId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const currentImage = images.find((image) => image.is_current) ?? null;
  const busy = saving || uploading || imageActionId !== null || deleting;

  useEffect(() => {
    setName(asset.name);
    setDescription(asset.description);
  }, [asset.id, asset.name, asset.description, asset.updated_at]);

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSuccessMessage(null);
    const input: AssetPatch = { name, description };
    try {
      await updateAsset(asset.id, input);
      await onChanged();
      setEditing(false);
      setSuccessMessage("资产已保存");
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setSaving(false);
    }
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file === undefined) {
      return;
    }
    setUploading(true);
    setError(null);
    setSuccessMessage(null);
    try {
      await uploadAssetImage(asset.id, file);
      await onChanged();
      event.target.value = "";
      setSuccessMessage("图片已上传");
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setUploading(false);
    }
  }

  async function handleSetCurrent(image: AssetImage) {
    setImageActionId(image.id);
    setError(null);
    setSuccessMessage(null);
    try {
      await setCurrentAssetImage(asset.id, image.id);
      await onChanged();
      setSuccessMessage("当前图片已切换");
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setImageActionId(null);
    }
  }

  async function handleDeleteImage(image: AssetImage) {
    if (!window.confirm("删除这个非当前图片版本？文件将进入 trash。")) {
      return;
    }
    setImageActionId(image.id);
    setError(null);
    setSuccessMessage(null);
    try {
      await deleteAssetImage(image.id);
      await onChanged();
      setSuccessMessage("图片版本已删除");
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setImageActionId(null);
    }
  }

  async function handleDeleteAsset() {
    if (!window.confirm("删除这个资产？其全部图片将进入 trash。")) {
      return;
    }
    setDeleting(true);
    setError(null);
    setSuccessMessage(null);
    try {
      await deleteAsset(asset.id);
      await onDeleted();
    } catch (requestError: unknown) {
      setError(requestError);
    } finally {
      setDeleting(false);
    }
  }

  function handleCancelEdit() {
    setEditing(false);
    setName(asset.name);
    setDescription(asset.description);
    setError(null);
    setSuccessMessage(null);
  }

  return (
    <article className="panel asset-card">
      <div className="asset-card-heading">
        <div>
          <p className="asset-type">{assetTypeLabel(asset.type)}</p>
          <h3>{asset.name}</h3>
          <p className="field-hint">修订：{asset.revision}</p>
        </div>
        <button disabled={busy} type="button" onClick={handleDeleteAsset}>
          {deleting ? "删除中…" : "删除资产"}
        </button>
      </div>
      {error !== null && <ApiErrorMessage error={error} />}
      {successMessage !== null && (
        <p className="success-message" role="status">
          {successMessage}
        </p>
      )}
      {!editing ? (
        <>
          <p className="asset-description">{asset.description}</p>
          <button disabled={busy} type="button" onClick={() => setEditing(true)}>
            编辑名称和描述
          </button>
        </>
      ) : (
        <form className="form-grid" onSubmit={handleSave}>
          <p className="field-hint">类型：{assetTypeLabel(asset.type)}（不可修改）</p>
          <label>
            名称
            <input
              disabled={busy}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            描述
            <textarea
              disabled={busy}
              rows={4}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <div className="action-row">
            <button disabled={busy} type="submit">
              {saving ? "保存中…" : "保存修改"}
            </button>
            <button disabled={busy} type="button" onClick={handleCancelEdit}>
              取消
            </button>
          </div>
        </form>
      )}
      <div className="asset-current-image">
        <h4>当前图片</h4>
        {currentImage === null ? (
          <p className="field-hint">暂无当前图片</p>
        ) : (
          <img
            alt={`${asset.name}当前图片`}
            src={getAssetImageMediaUrl(currentImage.id)}
          />
        )}
      </div>
      <div className="asset-gallery">
        <div className="asset-gallery-heading">
          <h4>版本画廊</h4>
          <label className="asset-upload-control">
            上传 PNG/JPEG/WebP
            <input
              accept="image/png,image/jpeg,image/webp"
              disabled={busy}
              type="file"
              onChange={handleUpload}
            />
          </label>
        </div>
        <p className="field-hint">大小由后端 UPLOAD_MAX_MB 最终裁决。</p>
        {images.length === 0 ? (
          <p className="field-hint">暂无图片版本</p>
        ) : (
          <ul className="asset-gallery-list">
            {images.map((image) => (
              <li className="asset-gallery-item" key={image.id}>
                <img
                  alt={`${asset.name}版本 ${image.id}`}
                  src={getAssetImageMediaUrl(image.id)}
                />
                <div>
                  <p>版本 {image.id}</p>
                  {image.is_current ? (
                    <p className="field-hint">当前版本不可直接删除</p>
                  ) : (
                    <div className="action-row">
                      <button
                        disabled={busy}
                        type="button"
                        onClick={() => void handleSetCurrent(image)}
                      >
                        {imageActionId === image.id ? "处理中…" : "设为当前"}
                      </button>
                      <button
                        disabled={busy}
                        type="button"
                        onClick={() => void handleDeleteImage(image)}
                      >
                        {imageActionId === image.id ? "处理中…" : "删除版本"}
                      </button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function assetTypeLabel(type: AssetType): string {
  return type === "character" ? "角色" : "场景";
}
