import { useEffect, useMemo, useRef, useState } from "react";

import { listAssets } from "../api/assets";
import {
  createClip,
  deleteClip,
  getClip,
  listClipSlots,
  listClipVideos,
  listClips,
  previewClips,
  updateClip,
} from "../api/clips";
import type { Clip } from "../api/clips";
import { listShots } from "../api/shots";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { EmptyState } from "../components/EmptyState";
import {
  applyDirectorPreview,
  buildDirectorProjection,
  clearDirectorPreview,
  createDirectorPreviewState,
  failDirectorPreview,
  invalidateDirectorPreview,
  preserveDirectorPreviewAfterCreateError,
  projectClipCreateRequest,
  projectDirectorClipSettingsPatch,
  projectDirectorGenerationGate,
  projectReferenceSelection,
  projectShotSelection,
  startDirectorPreview,
  type DirectorPreviewState,
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
        readClipDetail: async (clipId) => {
          const [clip, slots, videos] = await Promise.all([
            getClip(clipId),
            listClipSlots(clipId),
            listClipVideos(clipId),
          ]);
          return { clip, slots, videos };
        },
      }),
    [episodeId, projectId],
  );
  const [syncState, setSyncState] = useState<DirectorSyncState>(() =>
    sync.getState(),
  );
  const [selectedShotIds, setSelectedShotIds] = useState<number[]>([]);
  const [previewState, setPreviewState] = useState<DirectorPreviewState>(() =>
    createDirectorPreviewState(),
  );
  const [createdClipId, setCreatedClipId] = useState<number | null>(null);
  const [settingsActionError, setSettingsActionError] = useState<unknown | null>(
    null,
  );
  const [settingsNotice, setSettingsNotice] = useState<string | null>(null);
  const [settingsSavingClipId, setSettingsSavingClipId] = useState<number | null>(
    null,
  );
  const [pendingDeleteClipId, setPendingDeleteClipId] = useState<number | null>(
    null,
  );
  const previewGeneration = useRef(0);
  const previousSelectedClipId = useRef<number | null>(null);

  useEffect(() => {
    setSelectedShotIds([]);
    const unsubscribe = sync.subscribe(setSyncState);
    sync.start();
    return () => {
      unsubscribe();
      sync.dispose();
    };
  }, [sync]);

  useEffect(() => {
    if (
      createdClipId === null ||
      syncState.pagePhase !== "ready" ||
      syncState.pageSnapshot === null ||
      !syncState.pageSnapshot.clips.some((clip) => clip.id === createdClipId)
    ) {
      return;
    }
    sync.selectClip(createdClipId);
    setSelectedShotIds([]);
    setPreviewState(clearDirectorPreview());
    setCreatedClipId(null);
  }, [createdClipId, sync, syncState.pagePhase, syncState.pageSnapshot]);

  useEffect(() => {
    if (pendingDeleteClipId === null) {
      return;
    }
    if (
      syncState.pagePhase !== "ready" ||
      syncState.pageSnapshot === null ||
      syncState.pageSnapshot.clips.some(
        (clip) => clip.id === pendingDeleteClipId,
      )
    ) {
      return;
    }
    setPendingDeleteClipId(null);
    setSettingsNotice(`Clip #${pendingDeleteClipId} 已删除`);
  }, [pendingDeleteClipId, syncState.pagePhase, syncState.pageSnapshot]);

  useEffect(() => {
    if (previousSelectedClipId.current === syncState.selectedClipId) {
      return;
    }
    previousSelectedClipId.current = syncState.selectedClipId;
    setSettingsActionError(null);
    setSettingsNotice(null);
    setSettingsSavingClipId(null);
  }, [syncState.selectedClipId]);

  useEffect(() => {
    if (settingsSavingClipId === null) {
      return;
    }
    if (
      syncState.selectedClipId !== settingsSavingClipId ||
      syncState.detailPhase === "error" ||
      syncState.pagePhase === "error"
    ) {
      setSettingsSavingClipId(null);
      return;
    }
    if (
      syncState.detailPhase === "ready" &&
      syncState.clipDraft !== null &&
      !syncState.clipDraft.dirtyUserNote &&
      !syncState.clipDraft.dirtyRequestedDuration
    ) {
      setSettingsSavingClipId(null);
      setSettingsNotice(`Clip #${settingsSavingClipId} 设置已保存`);
    }
  }, [
    settingsSavingClipId,
    syncState.clipDraft,
    syncState.detailPhase,
    syncState.pagePhase,
    syncState.selectedClipId,
  ]);

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

  const createProjection = projectClipCreateRequest(previewState);
  const settingsProjection =
    syncState.clipDraft === null
      ? null
      : projectDirectorClipSettingsPatch(syncState.clipDraft);
  const generationGate =
    syncState.clipDraft === null
      ? null
      : projectDirectorGenerationGate(syncState.clipDraft);

  function toggleShot(shotId: number): void {
    const item = selection.eligibility.find((entry) => entry.shotId === shotId);
    if (item === undefined || item.disabled) {
      return;
    }
    previewGeneration.current += 1;
    sync.selectClip(null);
    setSelectedShotIds((current) =>
      current.includes(shotId)
        ? current.filter((currentShotId) => currentShotId !== shotId)
        : [...current, shotId],
    );
    setPreviewState((current) =>
      invalidateDirectorPreview(
        current.selectedShotIds.includes(shotId)
          ? current.selectedShotIds.filter(
              (currentShotId) => currentShotId !== shotId,
            )
          : [...current.selectedShotIds, shotId],
      ),
    );
  }

  function selectClip(clipId: number): void {
    if (pendingDeleteClipId !== null) {
      return;
    }
    previewGeneration.current += 1;
    setSelectedShotIds([]);
    setPreviewState(invalidateDirectorPreview([]));
    sync.selectClip(clipId);
  }

  function updateSelectedClipDraft(patch: {
    userNote?: string | null;
    requestedDuration?: string;
  }): void {
    if (syncState.selectedClipId === null || syncState.clipDraft === null) {
      return;
    }
    setSettingsActionError(null);
    setSettingsNotice(null);
    sync.updateClipDraft(patch);
  }

  function handleSaveSettings(): void {
    const clipId = syncState.selectedClipId;
    const draft = syncState.clipDraft;
    if (
      clipId === null ||
      draft === null ||
      syncState.detailPhase !== "ready" ||
      settingsSavingClipId !== null ||
      pendingDeleteClipId !== null
    ) {
      return;
    }
    const projected = projectDirectorClipSettingsPatch(draft);
    if (projected.input === null) {
      if (projected.validationMessage !== null) {
        setSettingsActionError(new Error(projected.validationMessage));
      }
      return;
    }
    setSettingsActionError(null);
    setSettingsNotice(null);
    setSettingsSavingClipId(clipId);
    void updateClip(clipId, projected.input).then(
      () => {
        sync.refreshPage({ refreshSelectedClip: true });
      },
      (error: unknown) => {
        setSettingsSavingClipId(null);
        setSettingsActionError(error);
      },
    );
  }

  function handleDeleteClip(): void {
    const clipId = syncState.selectedClipId;
    if (
      clipId === null ||
      pendingDeleteClipId !== null ||
      settingsSavingClipId !== null
    ) {
      return;
    }
    if (!window.confirm(`确定删除 Clip #${clipId}？`)) {
      return;
    }
    setSettingsActionError(null);
    setSettingsNotice(null);
    setPendingDeleteClipId(clipId);
    void deleteClip(clipId).then(
      () => {
        sync.refreshPage();
      },
      (error: unknown) => {
        setPendingDeleteClipId(null);
        setSettingsActionError(error);
      },
    );
  }

  function startPreview(): void {
    const requestedShotIds = [...selectedShotIds];
    const generation = ++previewGeneration.current;
    setPreviewState(startDirectorPreview(requestedShotIds));
    void previewClips(episodeId, { shot_ids: requestedShotIds }).then(
      (response) => {
        if (generation !== previewGeneration.current) {
          return;
        }
        setPreviewState((current) => applyDirectorPreview(current, response));
      },
      (error: unknown) => {
        if (generation !== previewGeneration.current) {
          return;
        }
        setPreviewState((current) => failDirectorPreview(current, error));
      },
    );
  }

  function toggleReference(assetId: number): void {
    setPreviewState((current) => {
      if (current.response === null || current.phase === "creating") {
        return current;
      }
      const selected = new Set(current.selectedReferenceAssetIds);
      if (selected.has(assetId)) {
        selected.delete(assetId);
      } else {
        selected.add(assetId);
      }
      const projected = projectReferenceSelection(
        current.response,
        [...selected],
      );
      return {
        ...current,
        selectedReferenceAssetIds: projected.selectedReferenceAssetIds,
        error: null,
      };
    });
  }

  function handleRequestedDurationChange(requestedDuration: string): void {
    setPreviewState((current) => ({
      ...current,
      requestedDuration,
      error: null,
    }));
  }

  function handleCreate(): void {
    if (createProjection.input === null || previewState.phase !== "ready") {
      return;
    }
    setPreviewState((current) => ({ ...current, phase: "creating", error: null }));
    void createClip(episodeId, createProjection.input).then(
      (created) => {
        setCreatedClipId(created.id);
        sync.refreshPage({
          notice: {
            kind: "mutation-success",
            message: `Clip #${created.id} 已创建`,
          },
        });
      },
      (error: unknown) => {
        setPreviewState((current) =>
          preserveDirectorPreviewAfterCreateError(current, error),
        );
      },
    );
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
      {syncState.notices.length > 0 && (
        <p className="director-success" role="status">
          {syncState.notices[syncState.notices.length - 1].message}
        </p>
      )}
      {settingsNotice !== null && (
        <p className="director-success" role="status">
          {settingsNotice}
        </p>
      )}

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

      <DirectorPreviewPanel
        createProjection={createProjection}
        onCreate={handleCreate}
        onPreview={startPreview}
        onReferenceToggle={toggleReference}
        onRequestedDurationChange={handleRequestedDurationChange}
        state={previewState}
      />

      <DirectorSelectionPanel
        clips={syncState.pageSnapshot.clips}
        detailPhase={syncState.detailPhase}
        detailError={syncState.detailError}
        generationGate={generationGate}
        onClearNote={() => updateSelectedClipDraft({ userNote: null })}
        onDelete={handleDeleteClip}
        onSave={handleSaveSettings}
        onUserNoteChange={(userNote) => updateSelectedClipDraft({ userNote })}
        onRequestedDurationChange={(requestedDuration) =>
          updateSelectedClipDraft({ requestedDuration })
        }
        selection={selection}
        settingsActionError={settingsActionError}
        settingsProjection={settingsProjection}
        settingsSaving={settingsSavingClipId !== null}
        deleting={pendingDeleteClipId !== null}
        clipDraft={syncState.clipDraft}
        selectedClipId={syncState.selectedClipId}
        selectedShotIds={selectedShotIds}
      />
    </section>
  );
}

interface DirectorPreviewPanelProps {
  createProjection: ReturnType<typeof projectClipCreateRequest>;
  onCreate: () => void;
  onPreview: () => void;
  onReferenceToggle: (assetId: number) => void;
  onRequestedDurationChange: (requestedDuration: string) => void;
  state: DirectorPreviewState;
}

function DirectorPreviewPanel({
  createProjection,
  onCreate,
  onPreview,
  onReferenceToggle,
  onRequestedDurationChange,
  state,
}: DirectorPreviewPanelProps) {
  const response = state.response;
  const referenceSelection =
    response === null
      ? null
      : projectReferenceSelection(response, state.selectedReferenceAssetIds);
  const previewInFlight =
    state.phase === "previewing" || state.phase === "creating";
  const canCreate =
    state.phase === "ready" && createProjection.input !== null;

  return (
    <section aria-label="预检与创建" className="director-preview-panel panel">
      <h3>预检与创建</h3>
      <button
        disabled={state.selectedShotIds.length === 0 || previewInFlight}
        onClick={onPreview}
        type="button"
      >
        {state.phase === "previewing" ? "预检中…" : "预检当前分镜"}
      </button>
      {state.selectedShotIds.length === 0 && (
        <p className="director-preview-hint">请先选择分镜</p>
      )}
      {state.error !== null && <ApiErrorMessage error={state.error} />}
      {response !== null && referenceSelection !== null && (
        <>
          <dl className="director-preview-summary">
            <div>
              <dt>分镜</dt>
              <dd>{response.shot_ids.join("、")}</dd>
            </div>
            <div>
              <dt>估算总时长</dt>
              <dd>{response.duration_est_total} 秒</dd>
            </div>
            <div>
              <dt>建议请求时长</dt>
              <dd>{response.suggested_requested_duration} 秒</dd>
            </div>
          </dl>

          {response.violations.length > 0 && (
            <div className="director-preview-messages director-preview-violations">
              <strong>违规</strong>
              <ul>
                {response.violations.map((violation, index) => (
                  <li key={`${violation.code}-${index}`}>{violation.message}</li>
                ))}
              </ul>
            </div>
          )}
          {response.warnings.length > 0 && (
            <div className="director-preview-messages director-preview-warnings">
              <strong>提示</strong>
              <ul>
                {response.warnings.map((warning, index) => (
                  <li key={`${warning.code}-${index}`}>{warning.message}</li>
                ))}
              </ul>
            </div>
          )}

          <fieldset
            className="director-reference-candidates"
            disabled={state.phase === "creating"}
          >
            <legend>
              参考资产（最多 {referenceSelection.maxSelectableReferenceAssets} 个）
            </legend>
            {response.reference_candidates.map((candidate) => {
              const checked = state.selectedReferenceAssetIds.includes(
                candidate.asset_id,
              );
              const atLimit =
                !checked &&
                state.selectedReferenceAssetIds.length >=
                  referenceSelection.maxSelectableReferenceAssets;
              return (
                <label
                  className="director-reference-candidate"
                  key={candidate.asset_id}
                >
                  <input
                    checked={checked}
                    disabled={atLimit}
                    onChange={() => onReferenceToggle(candidate.asset_id)}
                    type="checkbox"
                  />
                  <span>
                    {candidate.asset_name} · {candidate.asset_type} · 首次镜头 {candidate.first_shot_id}（顺序 {candidate.first_order_index}）
                  </span>
                  {candidate.selected_by_default && (
                    <small>默认</small>
                  )}
                </label>
              );
            })}
          </fieldset>

          <label className="director-requested-duration">
            请求时长（秒）
            <input
              onChange={(event) =>
                onRequestedDurationChange(event.target.value)
              }
              value={state.requestedDuration}
            />
          </label>
          {createProjection.validationMessage !== null &&
            state.phase === "ready" && (
              <p className="director-preview-hint">
                {createProjection.validationMessage}
              </p>
            )}
          <button disabled={!canCreate} onClick={onCreate} type="button">
            {state.phase === "creating" ? "创建中…" : "创建 Clip"}
          </button>
        </>
      )}
    </section>
  );
}

interface DirectorSelectionPanelProps {
  clips: Clip[];
  clipDraft: DirectorSyncState["clipDraft"];
  deleting: boolean;
  detailError: unknown | null;
  detailPhase: DirectorSyncState["detailPhase"];
  generationGate: ReturnType<typeof projectDirectorGenerationGate> | null;
  onClearNote: () => void;
  onDelete: () => void;
  onRequestedDurationChange: (requestedDuration: string) => void;
  onSave: () => void;
  onUserNoteChange: (userNote: string) => void;
  selection: ShotSelectionProjection;
  selectedClipId: number | null;
  selectedShotIds: number[];
  settingsActionError: unknown | null;
  settingsProjection: ReturnType<typeof projectDirectorClipSettingsPatch> | null;
  settingsSaving: boolean;
}

function describeDirectorNote(note: string | null): string {
  if (note === null) {
    return "未填写（null）";
  }
  if (note === "") {
    return "空字符串";
  }
  return "string（原始空白保留）";
}

function DirectorSelectionPanel({
  clips,
  clipDraft,
  deleting,
  detailError,
  detailPhase,
  generationGate,
  onClearNote,
  onDelete,
  onRequestedDurationChange,
  onSave,
  onUserNoteChange,
  selection,
  selectedClipId,
  selectedShotIds,
  settingsActionError,
  settingsProjection,
  settingsSaving,
}: DirectorSelectionPanelProps) {
  if (selectedClipId !== null) {
    const selectedClip = clips.find((clip) => clip.id === selectedClipId);
    const settingsReady =
      detailPhase === "ready" &&
      clipDraft !== null &&
      settingsProjection !== null &&
      generationGate !== null;
    const canSave =
      settingsReady &&
      settingsProjection.input !== null &&
      !settingsSaving &&
      !deleting;
    return (
      <section aria-label="当前选择" className="director-selection-panel panel">
        <h3>已选择 Clip #{selectedClipId}</h3>
        {selectedClip !== undefined && (
          <p>
            generation_state：{selectedClip.generation_state} · freshness：{selectedClip.freshness}
          </p>
        )}
        {detailPhase === "loading" && (
          <p className="director-selection-hint">正在加载 Clip 详情…</p>
        )}
        {detailPhase === "error" && detailError !== null && (
          <ApiErrorMessage error={detailError} />
        )}
        {settingsActionError !== null && (
          <ApiErrorMessage error={settingsActionError} />
        )}
        {settingsReady && clipDraft !== null && settingsProjection !== null && (
          <div className="director-clip-settings">
            <label className="director-clip-note">
              片段意见
              <textarea
                aria-label="片段意见"
                onChange={(event) => onUserNoteChange(event.target.value)}
                value={clipDraft.userNote ?? ""}
              />
            </label>
            <p className="director-settings-note-state">
              当前语义：{describeDirectorNote(clipDraft.userNote)}
            </p>
            <button
              disabled={clipDraft.userNote === null || settingsSaving || deleting}
              onClick={onClearNote}
              type="button"
            >
              清空为未填写
            </button>

            <label className="director-clip-duration">
              请求时长（秒）
              <input
                aria-invalid={settingsProjection.validationMessage !== null}
                inputMode="numeric"
                onChange={(event) =>
                  onRequestedDurationChange(event.target.value)
                }
                type="text"
                value={clipDraft.requestedDuration}
              />
            </label>
            {settingsProjection.validationMessage !== null && (
              <p className="director-preview-hint">
                {settingsProjection.validationMessage}
              </p>
            )}
            {generationGate !== null && generationGate.message !== null && (
              <p className="director-preview-hint">{generationGate.message}</p>
            )}

            <div className="director-settings-actions">
              <button disabled={!canSave} onClick={onSave} type="button">
                {settingsSaving ? "保存中…" : "保存设置"}
              </button>
              <button
                className="director-danger-button"
                disabled={settingsSaving || deleting}
                onClick={onDelete}
                type="button"
              >
                {deleting ? "删除中…" : "删除 Clip"}
              </button>
            </div>
          </div>
        )}
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
