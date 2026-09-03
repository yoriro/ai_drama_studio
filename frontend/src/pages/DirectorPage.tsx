import { useEffect, useState } from "react";

import { listAssets } from "../api/assets";
import { listClips } from "../api/clips";
import type { Clip } from "../api/clips";
import { listShots } from "../api/shots";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import {
  buildDirectorProjection,
  projectShotSelection,
  type DirectorProjection,
  type ShotSelectionProjection,
} from "../features/director/directorModel";

interface DirectorPageProps {
  projectId: number;
  episodeId: number;
}

interface DirectorData {
  projection: DirectorProjection;
  clips: Clip[];
}

type LoadState = "loading" | "error" | "ready";

export function DirectorPage({ projectId, episodeId }: DirectorPageProps) {
  const [data, setData] = useState<DirectorData | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [selectedShotIds, setSelectedShotIds] = useState<number[]>([]);
  const [selectedClipId, setSelectedClipId] = useState<number | null>(null);

  useEffect(() => {
    let disposed = false;
    setData(null);
    setLoadState("loading");
    setLoadError(null);
    setSelectedShotIds([]);
    setSelectedClipId(null);

    async function loadDirectorData(): Promise<DirectorData> {
      const [assets, shots, clips] = await Promise.all([
        listAssets(projectId),
        listShots(episodeId),
        listClips(episodeId),
      ]);
      return {
        projection: buildDirectorProjection({
          assets,
          shots,
          clips,
        }),
        clips,
      };
    }

    void loadDirectorData().then(
      (loaded) => {
        if (disposed) {
          return;
        }
        setData(loaded);
        setLoadState("ready");
      },
      (error: unknown) => {
        if (disposed) {
          return;
        }
        setLoadError(error);
        setLoadState("error");
      },
    );

    return () => {
      disposed = true;
    };
  }, [episodeId, projectId]);

  if (loadState === "loading") {
    return (
      <section aria-label="导演台" className="director-page">
        <h2>导演台</h2>
        <p>正在加载资产、分镜与片段…</p>
      </section>
    );
  }

  if (loadState === "error" || data === null) {
    return (
      <section aria-label="导演台" className="director-page">
        <h2>导演台</h2>
        <ApiErrorMessage error={loadError ?? new Error("导演台数据不存在")} />
      </section>
    );
  }

  if (data.projection.shots.length === 0) {
    return (
      <section aria-label="导演台" className="director-page">
        <h2>导演台</h2>
        <EmptyState message="暂无分镜，请先完成分镜生成" />
      </section>
    );
  }

  const selection = projectShotSelection(
    data.projection,
    selectedShotIds,
  );
  const selectedClip = data.projection.clipSpans.find(
    ({ clip }) => clip.id === selectedClipId,
  );

  function toggleShot(shotId: number): void {
    const item = selection.eligibility.find((entry) => entry.shotId === shotId);
    if (item === undefined || item.disabled) {
      return;
    }
    setSelectedClipId(null);
    setSelectedShotIds((current) =>
      current.includes(shotId)
        ? current.filter((currentShotId) => currentShotId !== shotId)
        : [...current, shotId],
    );
  }

  function selectClip(clipId: number): void {
    setSelectedShotIds([]);
    setSelectedClipId(clipId);
  }

  return (
    <section aria-label="导演台" className="director-page">
      <div className="director-heading">
        <div>
          <h2>导演台</h2>
          <p className="director-description">
            场景带、分镜轨与片段轨使用同一组分镜列；分镜勾选只用于新片段选择。
          </p>
        </div>
        <p className="director-count">{data.projection.shots.length} 个分镜</p>
      </div>

      <section aria-label="导演台轨道" className="director-tracks panel">
        <div className="director-track-group">
          <h3>场景带</h3>
          <div
            className="director-track director-scene-track"
            style={{ gridTemplateColumns: data.projection.gridTemplateColumns }}
          >
            {data.projection.sceneBands.map((band) => (
              <div
                className={[
                  "director-scene-band",
                  `director-scene-band-${band.classification.kind}`,
                  band.classification.paletteIndex === null
                    ? ""
                    : `director-scene-palette-${band.classification.paletteIndex}`,
                ].filter(Boolean).join(" ")}
                data-scene-kind={band.classification.kind}
                key={`${band.classification.key}-${band.startIndex}`}
                style={{
                  gridColumn: `${band.startIndex + 1} / ${band.endIndex + 2}`,
                }}
              >
                <strong>{band.classification.label}</strong>
                <span>{band.shotIds.length} 个分镜</span>
              </div>
            ))}
          </div>
        </div>

        <div className="director-track-group">
          <h3>分镜轨</h3>
          <div
            className="director-track director-shot-track"
            style={{ gridTemplateColumns: data.projection.gridTemplateColumns }}
          >
            {data.projection.shots.map((projectedShot) => {
              const eligibility = selection.eligibility.find(
                (item) => item.shotId === projectedShot.shot.id,
              )!;
              return (
                <div className="director-shot-cell" key={projectedShot.shot.id}>
                  <label className="director-shot-checkbox">
                    <input
                      checked={eligibility.selected}
                      disabled={eligibility.disabled}
                      onChange={() => toggleShot(projectedShot.shot.id)}
                      type="checkbox"
                    />
                    <span>镜头 {projectedShot.shot.order_index}</span>
                  </label>
                  <span className="director-shot-meta">
                    {projectedShot.shot.shot_type} · {projectedShot.shot.duration_est} 秒
                  </span>
                  {projectedShot.shot.status === "changed" && (
                    <span className="director-shot-changed">changed</span>
                  )}
                  {eligibility.reason !== null && (
                    <span className="director-shot-reason">{eligibility.reason}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="director-track-group">
          <h3>片段轨</h3>
          <div
            className="director-track director-clip-track"
            style={{ gridTemplateColumns: data.projection.gridTemplateColumns }}
          >
            {data.projection.gaps.map((gap) => (
              <div
                aria-label={`未覆盖分镜：${gap.shotIds.join(", ")}`}
                className="director-gap"
                key={`gap-${gap.startIndex}`}
                style={{ gridColumn: `${gap.startIndex + 1} / ${gap.endIndex + 2}` }}
              >
                空洞
              </div>
            ))}
            {data.projection.clipSpans.map((span) => (
              <button
                aria-pressed={selectedClipId === span.clip.id}
                className={[
                  "director-clip-bar",
                  span.status.generationClassName,
                  span.status.freshnessClassName,
                  selectedClipId === span.clip.id
                    ? "director-clip-bar-selected"
                    : "",
                ].filter(Boolean).join(" ")}
                key={span.clip.id}
                onClick={() => selectClip(span.clip.id)}
                style={{ gridColumn: `${span.startIndex + 1} / ${span.endIndex + 2}` }}
                type="button"
              >
                <strong>Clip #{span.clip.id}</strong>
                <span>{span.status.generationLabel}</span>
                <span>{span.status.freshnessLabel}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <DirectorSelectionPanel
        clips={data.clips}
        selection={selection}
        selectedClipId={selectedClip?.clip.id ?? null}
        selectedShotIds={selectedShotIds}
      />
    </section>
  );
}

interface DirectorSelectionPanelProps {
  clips: Clip[];
  selection: ShotSelectionProjection;
  selectedClipId: number | null;
  selectedShotIds: number[];
}

function DirectorSelectionPanel({
  clips,
  selection,
  selectedClipId,
  selectedShotIds,
}: DirectorSelectionPanelProps) {
  if (selectedClipId !== null) {
    const selectedClip = clips.find((clip) => clip.id === selectedClipId);
    return (
      <section aria-label="当前选择" className="director-selection-panel panel">
        <h3>已选择 Clip #{selectedClipId}</h3>
        {selectedClip !== undefined && (
          <p>
            generation_state：{selectedClip.generation_state} · freshness：{selectedClip.freshness}
          </p>
        )}
        <p className="director-selection-hint">轨道选择已更新，详情内容随权威数据加载。</p>
      </section>
    );
  }

  if (selectedShotIds.length > 0) {
    return (
      <section aria-label="新片段分镜选择" className="director-selection-panel panel">
        <h3>新片段分镜选择</h3>
        <p>已选择：{selection.selectedShotIds.join("、")}</p>
        <p className="director-selection-hint">保持当前选择以继续预检；未自动补齐或排序。</p>
      </section>
    );
  }

  return (
    <section aria-label="尚未选择" className="director-selection-panel panel">
      <h3>尚未选择</h3>
      <p>请在分镜轨勾选未占用分镜，或在片段轨选择既有 Clip。</p>
    </section>
  );
}
