import { useEffect, useMemo, useState } from "react";

import { listAssets } from "../api/assets";
import { listClips } from "../api/clips";
import type { Clip } from "../api/clips";
import { listShots } from "../api/shots";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import {
  buildDirectorProjection,
  projectShotSelection,
  type ShotSelectionProjection,
} from "../features/director/directorModel";
import {
  createDirectorSync,
  type DirectorSyncState,
} from "../features/director/directorSync";

interface DirectorPageProps {
  projectId: number;
  episodeId: number;
}

export function DirectorPage({ projectId, episodeId }: DirectorPageProps) {
  const sync = useMemo(
    () =>
      createDirectorSync({
        readPageSnapshot: async () => {
          const [assets, shots, clips] = await Promise.all([
            listAssets(projectId),
            listShots(episodeId),
            listClips(episodeId),
          ]);
          buildDirectorProjection({ assets, shots, clips });
          return { assets, shots, clips };
        },
      }),
    [episodeId, projectId],
  );
  const [syncState, setSyncState] = useState<DirectorSyncState>(() =>
    sync.getState(),
  );
  const [selectedShotIds, setSelectedShotIds] = useState<number[]>([]);

  useEffect(() => {
    setSelectedShotIds([]);
    const unsubscribe = sync.subscribe(setSyncState);
    sync.start();
    return () => {
      unsubscribe();
      sync.dispose();
    };
  }, [sync]);

  if (
    syncState.pagePhase === "connecting" ||
    syncState.pagePhase === "snapshot-loading"
  ) {
    return (
      <section aria-label="导演台" className="director-page">
        <h2>导演台</h2>
        <p>正在加载资产、分镜与片段…</p>
      </section>
    );
  }

  if (syncState.pagePhase === "error" || syncState.pageSnapshot === null) {
    return (
      <section aria-label="导演台" className="director-page">
        <h2>导演台</h2>
        <ApiErrorMessage
          error={syncState.error ?? new Error("导演台数据不存在")}
        />
      </section>
    );
  }

  const projection = buildDirectorProjection(syncState.pageSnapshot);

  if (projection.shots.length === 0) {
    return (
      <section aria-label="导演台" className="director-page">
        <h2>导演台</h2>
        <EmptyState message="暂无分镜，请先完成分镜生成" />
      </section>
    );
  }

  const selection = projectShotSelection(
    projection,
    selectedShotIds,
  );

  function toggleShot(shotId: number): void {
    const item = selection.eligibility.find((entry) => entry.shotId === shotId);
    if (item === undefined || item.disabled) {
      return;
    }
    sync.selectClip(null);
    setSelectedShotIds((current) =>
      current.includes(shotId)
        ? current.filter((currentShotId) => currentShotId !== shotId)
        : [...current, shotId],
    );
  }

  function selectClip(clipId: number): void {
    setSelectedShotIds([]);
    sync.selectClip(clipId);
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
        <p className="director-count">{projection.shots.length} 个分镜</p>
      </div>

      <section aria-label="导演台轨道" className="director-tracks panel">
        <div className="director-track-group">
          <h3>场景带</h3>
          <div
            className="director-track director-scene-track"
            style={{ gridTemplateColumns: projection.gridTemplateColumns }}
          >
            {projection.sceneBands.map((band) => (
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
            style={{ gridTemplateColumns: projection.gridTemplateColumns }}
          >
            {projection.shots.map((projectedShot) => {
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
            style={{ gridTemplateColumns: projection.gridTemplateColumns }}
          >
            {projection.gaps.map((gap) => (
              <div
                aria-label={`未覆盖分镜：${gap.shotIds.join(", ")}`}
                className="director-gap"
                key={`gap-${gap.startIndex}`}
                style={{ gridColumn: `${gap.startIndex + 1} / ${gap.endIndex + 2}` }}
              >
                空洞
              </div>
            ))}
            {projection.clipSpans.map((span) => (
              <button
                aria-pressed={syncState.selectedClipId === span.clip.id}
                className={[
                  "director-clip-bar",
                  span.status.generationClassName,
                  span.status.freshnessClassName,
                  syncState.selectedClipId === span.clip.id
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
        clips={syncState.pageSnapshot.clips}
        selection={selection}
        selectedClipId={syncState.selectedClipId}
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
