import { useEffect, useMemo, useRef, useState } from "react";

import {
  listAssets,
  parseAssetListResponse,
} from "../api/assets";
import {
  createClip,
  getClip,
  listClipSlots,
  listClipVideos,
  listClips,
  parseClipResponse,
  parseClipPreviewResponse,
  parseClipSlotMutationResponse,
  parseClipSlotsResponse,
  parseClipVideosResponse,
  previewClips,
} from "../api/clips";
import type { Clip, GenerateClipVideoResponse } from "../api/clips";
import { listShots, parseShotListResponse } from "../api/shots";
import { protocolError } from "../api/client";
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
  projectDirectorSlots,
  projectDirectorTakes,
  projectReferenceSelection,
  projectShotSelection,
  startDirectorPreview,
  type DirectorPreviewState,
  type ShotSelectionProjection,
} from "../features/director/directorModel";
import {
  createDirectorSync,
  createDirectorGenerationRequester,
  createDirectorMutationAdapter,
  projectDirectorVisibleSyncErrors,
  resolveDirectorClipSave,
  type DirectorClipSaveAction,
  type DirectorMutationAction,
  type DirectorSyncState,
} from "../features/director/directorSync";
import type { Task, TaskEvent } from "../api/tasks";

interface DirectorPageProps {
  projectId: number;
  episodeId: number;
}

interface DirectorSlotMediaProps {
  alt: string;
  className: string;
  imageUrl: string;
}

export function DirectorSlotMedia({
  alt,
  className,
  imageUrl,
}: DirectorSlotMediaProps) {
  return <img alt={alt} className={className} src={imageUrl} />;
}

interface DirectorTakeMediaProps {
  mediaUrl: string;
  onError: () => void;
}

export function DirectorTakeMedia({
  mediaUrl,
  onError,
}: DirectorTakeMediaProps) {
  return <video controls onError={onError} src={mediaUrl} />;
}

export function DirectorPage({ projectId, episodeId }: DirectorPageProps) {
  const sync = useMemo(
    () =>
      createDirectorSync({
        readPageSnapshot: async () => {
          const [rawAssets, rawShots, rawClips] = await Promise.all([
            listAssets(projectId),
            listShots(episodeId),
            listClips(episodeId),
          ]);
          const assets = parseAssetListResponse(rawAssets);
          const shots = parseShotListResponse(rawShots);
          const clips = rawClips.map((clip) => parseClipResponse(clip));
          if (assets.some((asset) => asset.project_id !== projectId)) {
            return protocolError(
              200,
              "Director assets response contains an asset from another project",
            );
          }
          if (shots.some((shot) => shot.episode_id !== episodeId)) {
            return protocolError(
              200,
              "Director shots response contains a shot from another episode",
            );
          }
          if (clips.some((clip) => clip.episode_id !== episodeId)) {
            return protocolError(
              200,
              "Director clips response contains a clip from another episode",
            );
          }
          buildDirectorProjection({ assets, shots, clips });
          return { assets, shots, clips };
        },
        readClipDetail: async (clipId) => {
          const [rawClip, rawSlots, rawVideos] = await Promise.all([
            getClip(clipId),
            listClipSlots(clipId),
            listClipVideos(clipId),
          ]);
          const clip = parseClipResponse(rawClip);
          const slots = parseClipSlotsResponse(rawSlots);
          const videos = parseClipVideosResponse(rawVideos);
          if (clip.id !== clipId) {
            return protocolError(
              200,
              `Director Clip detail targeted Clip ${clip.id}, expected ${clipId}`,
            );
          }
          if (slots.clip_id !== clipId) {
            return protocolError(
              200,
              `Director slot response targeted Clip ${slots.clip_id}, expected ${clipId}`,
            );
          }
          if (slots.items.some((slot) => slot.clip_id !== clipId)) {
            return protocolError(
              200,
              "Director slot response contains a slot from another clip",
            );
          }
          if (videos.some((video) => video.clip_id !== clipId)) {
            return protocolError(
              200,
              "Director video response contains a video from another clip",
            );
          }
          return { clip, slots, videos };
        },
      }),
    [episodeId, projectId],
  );
  const generationRequester = useMemo(
    () => createDirectorGenerationRequester(),
    [],
  );
  const mutationAdapter = useMemo(
    () =>
      createDirectorMutationAdapter({
        refreshPage: (options) => sync.refreshPage(options),
        refreshSelectedClip: () => sync.refreshSelectedClip(),
        submitGenerateVideo: (clipId, input) =>
          generationRequester.submit(clipId, input),
      }),
    [generationRequester, sync],
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
  const [slotMutationKey, setSlotMutationKey] = useState<string | null>(null);
  const [slotMutationRefreshing, setSlotMutationRefreshing] = useState(false);
  const [slotMutationError, setSlotMutationError] = useState<unknown | null>(
    null,
  );
  const [takeMutationKey, setTakeMutationKey] = useState<string | null>(null);
  const [takeMutationRefreshing, setTakeMutationRefreshing] = useState(false);
  const [takeMutationError, setTakeMutationError] = useState<unknown | null>(
    null,
  );
  const [mediaErrors, setMediaErrors] = useState<Record<number, string>>({});
  const [generationRequestInFlight, setGenerationRequestInFlight] =
    useState(false);
  const [generationTaskIds, setGenerationTaskIds] = useState<number[]>([]);
  const [generationActionError, setGenerationActionError] =
    useState<unknown | null>(null);
  const previewGeneration = useRef(0);
  const previousSelectedClipId = useRef<number | null>(null);
  const saveActionGeneration = useRef(0);
  const selectionGeneration = useRef(0);
  const pendingMutationNotice = useRef<{
    message: string;
    baselineNoticeCount: number;
  } | null>(null);

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
    selectionGeneration.current += 1;
    pendingMutationNotice.current = null;
    setSettingsActionError(null);
    setSettingsNotice(null);
    setSettingsSavingClipId(null);
    setSlotMutationError(null);
    setTakeMutationError(null);
    setMediaErrors({});
    setGenerationTaskIds([]);
    setGenerationActionError(null);
  }, [syncState.selectedClipId]);

  useEffect(() => {
    const pending = pendingMutationNotice.current;
    if (
      pending === null ||
      syncState.notices.length <= pending.baselineNoticeCount
    ) {
      return;
    }
    const notice = syncState.notices
      .slice(pending.baselineNoticeCount)
      .find(
        (candidate) =>
          candidate.kind === "mutation-success" &&
          candidate.message === pending.message,
      );
    if (notice === undefined) {
      return;
    }
    pendingMutationNotice.current = null;
    if (settingsSavingClipId !== null) {
      setSettingsSavingClipId(null);
    }
    if (slotMutationKey !== null || slotMutationRefreshing) {
      setSlotMutationKey(null);
      setSlotMutationRefreshing(false);
    }
  }, [settingsSavingClipId, slotMutationKey, slotMutationRefreshing, syncState.notices]);

  useEffect(() => {
    if (settingsSavingClipId === null) {
      return;
    }
    if (
      syncState.selectedClipId !== settingsSavingClipId ||
      syncState.detailPhase === "error" ||
      syncState.pagePhase === "error"
    ) {
      pendingMutationNotice.current = null;
      setSettingsSavingClipId(null);
      return;
    }
  }, [
    settingsSavingClipId,
    syncState.detailPhase,
    syncState.pagePhase,
    syncState.selectedClipId,
  ]);

  useEffect(() => {
    if (slotMutationKey === null || !slotMutationRefreshing) {
      return;
    }
    if (
      syncState.selectedClipId === null ||
      syncState.detailPhase === "error" ||
      syncState.pagePhase === "error"
    ) {
      pendingMutationNotice.current = null;
      setSlotMutationKey(null);
      setSlotMutationRefreshing(false);
      return;
    }
  }, [
    syncState.detailPhase,
    syncState.pagePhase,
    syncState.selectedClipId,
    slotMutationKey,
    slotMutationRefreshing,
  ]);

  useEffect(() => {
    if (takeMutationKey === null || !takeMutationRefreshing) {
      return;
    }
    if (
      syncState.selectedClipId === null ||
      syncState.detailPhase === "error" ||
      syncState.pagePhase === "error"
    ) {
      setTakeMutationKey(null);
      setTakeMutationRefreshing(false);
      return;
    }
    if (syncState.detailPhase === "ready" && syncState.clipDetail !== null) {
      setTakeMutationKey(null);
      setTakeMutationRefreshing(false);
      setSettingsNotice("视频 take 已按最新快照更新");
    }
  }, [
    syncState.clipDetail,
    syncState.detailPhase,
    syncState.pagePhase,
    syncState.selectedClipId,
    takeMutationKey,
    takeMutationRefreshing,
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
  const visibleSyncErrors = projectDirectorVisibleSyncErrors(syncState);

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
  const slotsProjection =
    syncState.clipDetail === null
      ? null
      : projectDirectorSlots(syncState.clipDetail.slots);
  const takesProjection =
    syncState.clipDetail === null
      ? null
      : projectDirectorTakes(syncState.clipDetail.videos);

  function toggleShot(shotId: number): void {
    if (slotMutationKey !== null || takeMutationKey !== null) {
      return;
    }
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
    if (
      pendingDeleteClipId !== null ||
      slotMutationKey !== null ||
      takeMutationKey !== null
    ) {
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
    const action: DirectorClipSaveAction = {
      clipId,
      actionGeneration: ++saveActionGeneration.current,
      selectionGeneration: selectionGeneration.current,
    };
    void mutationAdapter.run<unknown>(
      { kind: "save", clipId, input: projected.input },
      {
        setError: (error) => {
          setSettingsSavingClipId(null);
          setSettingsActionError(error);
        },
        onSuccess: (updated) => {
          parseClipResponse(updated);
          const resolution = resolveDirectorClipSave(action, {
            selectedClipId: sync.getState().selectedClipId,
            latestActionGeneration: saveActionGeneration.current,
            selectionGeneration: selectionGeneration.current,
          });
          if (resolution.notice !== null) {
            pendingMutationNotice.current = {
              message: resolution.notice.message,
              baselineNoticeCount: sync.getState().notices.length,
            };
            sync.refreshPage({
              notice: resolution.notice,
              noticeAfterDetail: true,
              refreshSelectedClip: true,
            });
            return;
          }
          sync.refreshPage();
        },
      },
    );
  }

  function handleDeleteClip(): void {
    const clipId = syncState.selectedClipId;
    if (
      clipId === null ||
      pendingDeleteClipId !== null ||
      settingsSavingClipId !== null ||
      takeMutationKey !== null
    ) {
      return;
    }
    if (!window.confirm(`确定删除 Clip #${clipId}？`)) {
      return;
    }
    setSettingsActionError(null);
    setSettingsNotice(null);
    setPendingDeleteClipId(clipId);
    void mutationAdapter.run<void>(
      { kind: "delete", clipId },
      {
        setError: (error) => {
          setPendingDeleteClipId(null);
          setSettingsActionError(error);
        },
        onSuccess: () => {
          sync.refreshPage();
        },
      },
    );
  }

  function handleSlotMutation(
    key: string,
    action: DirectorMutationAction,
  ): void {
    const clipId = syncState.selectedClipId;
    if (
      clipId === null ||
      slotMutationKey !== null ||
      pendingDeleteClipId !== null ||
      settingsSavingClipId !== null
    ) {
      return;
    }
    setSlotMutationError(null);
    setSlotMutationKey(key);
    setSlotMutationRefreshing(false);
    void mutationAdapter.run<unknown>(action, {
      setError: (error) => {
        setSlotMutationKey(null);
        setSlotMutationRefreshing(false);
        setSlotMutationError(error);
      },
      onSuccess: (response) => {
        parseClipSlotMutationResponse(response);
        setSlotMutationRefreshing(true);
        const message = "槽位已按最新快照更新";
        pendingMutationNotice.current = {
          message,
          baselineNoticeCount: sync.getState().notices.length,
        };
        sync.refreshPage({
          notice: { kind: "mutation-success", message },
          noticeAfterDetail: true,
          refreshSelectedClip: true,
        });
      },
    });
  }

  function handleSlotEnabledChange(slotNo: number, enabled: boolean): void {
    const clipId = syncState.selectedClipId;
    if (clipId === null) {
      return;
    }
    handleSlotMutation(`enabled:${slotNo}`, {
      kind: "slot-enabled",
      clipId,
      slotNo,
      enabled,
    });
  }

  function handleSlotUpload(slotNo: number, file: File): void {
    const clipId = syncState.selectedClipId;
    if (clipId === null) {
      return;
    }
    handleSlotMutation(`upload:${slotNo}`, {
      kind: "slot-upload",
      clipId,
      slotNo,
      file,
    });
  }

  function handleSlotClear(slotNo: number): void {
    const clipId = syncState.selectedClipId;
    if (clipId === null || !window.confirm(`确定清除槽位 ${slotNo} 的 override？`)) {
      return;
    }
    handleSlotMutation(`clear:${slotNo}`, {
      kind: "slot-clear",
      clipId,
      slotNo,
    });
  }

  function handleTakeMutation(
    key: string,
    action: DirectorMutationAction,
  ): void {
    const clipId = syncState.selectedClipId;
    if (
      clipId === null ||
      takeMutationKey !== null ||
      slotMutationKey !== null ||
      pendingDeleteClipId !== null ||
      settingsSavingClipId !== null
    ) {
      return;
    }
    setTakeMutationError(null);
    setTakeMutationKey(key);
    setTakeMutationRefreshing(false);
    void mutationAdapter.run<unknown>(action, {
      setError: (error) => {
        setTakeMutationKey(null);
        setTakeMutationRefreshing(false);
        setTakeMutationError(error);
      },
      onSuccess: (response) => {
        if (response !== undefined) {
          parseClipVideosResponse([response]);
        }
        setTakeMutationRefreshing(true);
        sync.refreshSelectedClip();
      },
    });
  }

  function handleSetCurrentTake(videoId: number): void {
    const clipId = syncState.selectedClipId;
    if (clipId === null) {
      return;
    }
    handleTakeMutation(`current:${videoId}`, {
      kind: "take-current",
      clipId,
      videoId,
    });
  }

  function handleDeleteTake(videoId: number, isCurrent: boolean): void {
    if (isCurrent || !window.confirm(`确定删除 take #${videoId}？`)) {
      return;
    }
    handleTakeMutation(`delete:${videoId}`, {
      kind: "take-delete",
      videoId,
    });
  }

  function handleGenerateVideo(): void {
    const clipId = syncState.selectedClipId;
    const draft = syncState.clipDraft;
    if (
      clipId === null ||
      draft === null ||
      syncState.detailPhase !== "ready" ||
      generationGate === null ||
      !generationGate.allowed ||
      generationRequestInFlight
    ) {
      return;
    }
    const input = draft.dirtyUserNote
      ? { user_note: draft.userNote }
      : {};
    const pending = mutationAdapter.run<GenerateClipVideoResponse>(
      { kind: "generate", clipId, input },
      {
        setError: setGenerationActionError,
        onSuccess: ({ task_id }) => {
          sync.trackTask(task_id);
          if (sync.getState().selectedClipId === clipId) {
            setGenerationTaskIds((current) => [...current, task_id]);
          }
          sync.refreshPage({
            resetSelectedClipDraft: true,
            refreshSelectedClip:
              sync.getState().selectedClipId === clipId,
          });
        },
      },
    );
    if (pending === null) {
      return;
    }
    setGenerationActionError(null);
    setGenerationRequestInFlight(true);
    void pending.finally(() => {
      setGenerationRequestInFlight(false);
    });
  }

  function startPreview(): void {
    const requestedShotIds = [...selectedShotIds];
    const generation = ++previewGeneration.current;
    setPreviewState(startDirectorPreview(requestedShotIds));
    void previewClips(episodeId, { shot_ids: requestedShotIds })
      .then((response) => {
        if (generation !== previewGeneration.current) {
          return;
        }
        const validated = parseClipPreviewResponse(response);
        if (validated.episode_id !== episodeId) {
          return protocolError(
            200,
            `Director preview targeted Episode ${validated.episode_id}, expected ${episodeId}`,
          );
        }
        setPreviewState((current) => applyDirectorPreview(current, validated));
      })
      .catch((error: unknown) => {
        if (generation !== previewGeneration.current) {
          return;
        }
        setPreviewState((current) => failDirectorPreview(current, error));
      });
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
    void createClip(episodeId, createProjection.input)
      .then((created) => {
        const validated = parseClipResponse(created);
        if (validated.episode_id !== episodeId) {
          return protocolError(
            200,
            `Director created Clip targeted Episode ${validated.episode_id}, expected ${episodeId}`,
          );
        }
        setCreatedClipId(validated.id);
        sync.refreshPage({
          notice: {
            kind: "mutation-success",
            message: `Clip #${created.id} 已创建`,
          },
        });
      })
      .catch((error: unknown) => {
        setPreviewState((current) =>
          preserveDirectorPreviewAfterCreateError(current, error),
        );
      });
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
      {visibleSyncErrors.length > 0 && (
        <div aria-label="导演台同步错误" className="director-sync-errors">
          {visibleSyncErrors.map(({ kind, error }) => (
            <ApiErrorMessage error={error} key={kind} />
          ))}
        </div>
      )}
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
        generationActionError={generationActionError}
        generationRequestInFlight={generationRequestInFlight}
        generationTaskIds={generationTaskIds}
        taskDetails={syncState.taskDetails}
        taskEvents={syncState.taskEvents}
        taskError={syncState.taskError}
        onGenerate={handleGenerateVideo}
        onClearNote={() => updateSelectedClipDraft({ userNote: null })}
        onDelete={handleDeleteClip}
        onSave={handleSaveSettings}
        onUserNoteChange={(userNote) => updateSelectedClipDraft({ userNote })}
        onRequestedDurationChange={(requestedDuration) =>
          updateSelectedClipDraft({ requestedDuration })
        }
        onSlotClear={handleSlotClear}
        onSlotEnabledChange={handleSlotEnabledChange}
        onSlotUpload={handleSlotUpload}
        selection={selection}
        settingsActionError={settingsActionError}
        settingsProjection={settingsProjection}
        settingsSaving={settingsSavingClipId !== null}
        slotMutationError={slotMutationError}
        slotMutationKey={slotMutationKey}
        slotsProjection={slotsProjection}
        takeMutationError={takeMutationError}
        takeMutationKey={takeMutationKey}
        takesProjection={takesProjection}
        mediaErrors={mediaErrors}
        onDeleteTake={handleDeleteTake}
        onSetCurrentTake={handleSetCurrentTake}
        onMediaError={(videoId) =>
          setMediaErrors((current) => ({
            ...current,
            [videoId]: "视频媒体加载失败",
          }))
        }
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

interface DirectorGenerationPanelProps {
  actionError: unknown | null;
  detailPhase: DirectorSyncState["detailPhase"];
  generationGate: ReturnType<typeof projectDirectorGenerationGate> | null;
  inFlight: boolean;
  onGenerate: () => void;
  taskDetails: Task[];
  taskEvents: TaskEvent[];
  taskIds: number[];
  taskError: unknown | null;
}

function DirectorGenerationPanel({
  actionError,
  detailPhase,
  generationGate,
  inFlight,
  onGenerate,
  taskDetails,
  taskEvents,
  taskIds,
  taskError,
}: DirectorGenerationPanelProps) {
  const canGenerate =
    detailPhase === "ready" &&
    generationGate !== null &&
    generationGate.allowed &&
    !inFlight;

  return (
    <section aria-label="视频生成" className="director-generation-panel">
      <h4>视频生成</h4>
      {actionError !== null && <ApiErrorMessage error={actionError} />}
      {detailPhase !== "ready" && (
        <p className="director-preview-hint">详情加载完成后才可生成</p>
      )}
      <button disabled={!canGenerate} onClick={onGenerate} type="button">
        {inFlight ? "提交生成任务…" : "生成视频"}
      </button>
      {taskIds.map((taskId) => {
        const task = taskDetails.find((candidate) => candidate.id === taskId);
        const event = taskEvents.find(
          (candidate) => candidate.task_id === taskId,
        );
        const status = task?.status ?? event?.status ?? null;
        const progress = task?.progress ?? event?.progress ?? null;
        const failed = status === "failed";
        return (
          <article className="director-generation-task" key={taskId}>
            <p className="director-generation-submitted" role="status">
              任务已提交：#{taskId}
            </p>
            {status !== null && (
              <p className="director-generation-status">
                状态：{status}
                {progress !== null ? ` · 进度：${progress}` : ""}
              </p>
            )}
            {event?.message !== undefined && event.message.length > 0 && (
              <p className="director-generation-message">{event.message}</p>
            )}
            {task?.error_msg !== null && task?.error_msg !== undefined && (
              <p className="error-message" role="alert">
                {task.error_msg}
              </p>
            )}
            {failed && task === undefined && taskError !== null && (
              <ApiErrorMessage error={taskError} />
            )}
          </article>
        );
      })}
    </section>
  );
}

interface DirectorSlotsPanelProps {
  mutationError: unknown | null;
  mutationKey: string | null;
  onClear: (slotNo: number) => void;
  onEnabledChange: (slotNo: number, enabled: boolean) => void;
  onUpload: (slotNo: number, file: File) => void;
  projection: ReturnType<typeof projectDirectorSlots>;
}

function DirectorSlotsPanel({
  mutationError,
  mutationKey,
  onClear,
  onEnabledChange,
  onUpload,
  projection,
}: DirectorSlotsPanelProps) {
  return (
    <section aria-label="片段槽位" className="director-slots-panel">
      <h4>参考槽位</h4>
      {mutationError !== null && <ApiErrorMessage error={mutationError} />}
      {projection.warnings.length > 0 && (
        <div className="director-slot-warnings">
          <strong>槽位提示</strong>
          <ul>
            {projection.warnings.map((warning, index) => (
              <li key={`${warning.code}-${index}`}>{warning.message}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="director-slot-list">
        {projection.slots.map((slot) => {
          const enabledAction = slot.enabled ? "disable" : "enable";
          return (
            <article className="director-slot-row" key={slot.slotId}>
              <div className="director-slot-heading">
                <strong>
                  槽位 {slot.slotNo} · {slot.assetNameSnapshot} · {slot.assetTypeSnapshot}
                </strong>
                {slot.assetDeleted && (
                  <span className="director-slot-deleted">原资产已删除</span>
                )}
              </div>
              <p className="director-slot-state">
                {slot.enabled ? "启用" : "停用"} · 图片来源：{slot.sourceLabel} · {slot.imageStatusLabel}
              </p>
              {slot.imageUrl !== null ? (
                <DirectorSlotMedia
                  alt={`槽位 ${slot.slotNo} 参考图`}
                  className="director-slot-image"
                  imageUrl={slot.imageUrl}
                />
              ) : (
                <p className="director-slot-missing">缺图</p>
              )}
              <div className="director-slot-actions">
                {slot.actions.includes(enabledAction) && (
                  <button
                    disabled={mutationKey !== null}
                    onClick={() =>
                      onEnabledChange(slot.slotNo, !slot.enabled)
                    }
                    type="button"
                  >
                    {slot.enabled ? "停用槽位" : "启用槽位"}
                  </button>
                )}
                {slot.actions.includes("upload_override") && (
                  <label className="director-slot-upload">
                    上传 override
                    <input
                      accept=".png,.jpg,.jpeg,.webp"
                      disabled={mutationKey !== null}
                      onChange={(event) => {
                        const file = event.currentTarget.files?.[0];
                        if (file !== undefined) {
                          onUpload(slot.slotNo, file);
                        }
                      }}
                      type="file"
                    />
                  </label>
                )}
                {slot.actions.includes("clear_override") && (
                  <button
                    disabled={mutationKey !== null}
                    onClick={() => onClear(slot.slotNo)}
                    type="button"
                  >
                    清除 override
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

interface DirectorTakesPanelProps {
  mediaErrors: Record<number, string>;
  mutationError: unknown | null;
  mutationKey: string | null;
  onDelete: (videoId: number, isCurrent: boolean) => void;
  onMediaError: (videoId: number) => void;
  onSetCurrent: (videoId: number) => void;
  projection: ReturnType<typeof projectDirectorTakes>;
}

function DirectorTakesPanel({
  mediaErrors,
  mutationError,
  mutationKey,
  onDelete,
  onMediaError,
  onSetCurrent,
  projection,
}: DirectorTakesPanelProps) {
  return (
    <section aria-label="视频 take" className="director-takes-panel">
      <h4>视频 take</h4>
      {mutationError !== null && <ApiErrorMessage error={mutationError} />}
      {projection.length === 0 ? (
        <p className="director-selection-hint">暂无 take</p>
      ) : (
        <div className="director-take-list">
          {projection.map((take) => {
            const currentAction = take.actions.find(
              (action) => action.kind === "set_current",
            );
            const deleteAction = take.actions.find(
              (action) => action.kind === "delete",
            );
            return (
              <article className="director-take-row" key={take.id}>
                <div className="director-take-heading">
                  <strong>take #{take.id}</strong>
                  {take.isCurrent && (
                    <span className="director-take-current">current</span>
                  )}
                </div>
                <dl className="director-take-summary">
                  <div>
                    <dt>请求时长</dt>
                    <dd>{take.requestedDurationLabel}</dd>
                  </div>
                  <div>
                    <dt>实际时长</dt>
                    <dd>{take.actualDurationLabel}</dd>
                  </div>
                  <div>
                    <dt>seed</dt>
                    <dd>{take.seed}</dd>
                  </div>
                  <div>
                    <dt>创建时间</dt>
                    <dd>{take.createdAt}</dd>
                  </div>
                </dl>
                <DirectorTakeMedia
                  onError={() => onMediaError(take.id)}
                  mediaUrl={take.mediaUrl}
                />
                {mediaErrors[take.id] !== undefined && (
                  <p className="error-message" role="alert">
                    {mediaErrors[take.id]}
                  </p>
                )}
                <div className="director-take-actions">
                  <button
                    disabled={mutationKey !== null || currentAction?.disabled === true}
                    onClick={() => onSetCurrent(take.id)}
                    type="button"
                  >
                    {currentAction?.label}
                  </button>
                  <button
                    disabled={mutationKey !== null || deleteAction?.disabled === true}
                    onClick={() => onDelete(take.id, take.isCurrent)}
                    title={deleteAction?.disabled ? deleteAction.label : undefined}
                    type="button"
                  >
                    {deleteAction?.label}
                  </button>
                </div>
                {take.debug !== null && (
                  <details className="director-take-debug">
                    <summary>DEBUG</summary>
                    <dl>
                      <div>
                        <dt>built_prompt</dt>
                        <dd>
                          <pre>{take.debug.builtPrompt ?? "null"}</pre>
                        </dd>
                      </div>
                      <div>
                        <dt>input_snapshot</dt>
                        <dd>
                          <pre>
                            {take.debug.inputSnapshot === null
                              ? "null"
                              : JSON.stringify(
                                  take.debug.inputSnapshot,
                                  null,
                                  2,
                                )}
                          </pre>
                        </dd>
                      </div>
                    </dl>
                  </details>
                )}
              </article>
            );
          })}
        </div>
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
  generationActionError: unknown | null;
  generationGate: ReturnType<typeof projectDirectorGenerationGate> | null;
  generationRequestInFlight: boolean;
  generationTaskIds: number[];
  onClearNote: () => void;
  onDelete: () => void;
  onGenerate: () => void;
  onRequestedDurationChange: (requestedDuration: string) => void;
  onSlotClear: (slotNo: number) => void;
  onSlotEnabledChange: (slotNo: number, enabled: boolean) => void;
  onSlotUpload: (slotNo: number, file: File) => void;
  onDeleteTake: (videoId: number, isCurrent: boolean) => void;
  onMediaError: (videoId: number) => void;
  onSetCurrentTake: (videoId: number) => void;
  onSave: () => void;
  onUserNoteChange: (userNote: string) => void;
  selection: ShotSelectionProjection;
  selectedClipId: number | null;
  selectedShotIds: number[];
  settingsActionError: unknown | null;
  settingsProjection: ReturnType<typeof projectDirectorClipSettingsPatch> | null;
  settingsSaving: boolean;
  slotMutationError: unknown | null;
  slotMutationKey: string | null;
  slotsProjection: ReturnType<typeof projectDirectorSlots> | null;
  takeMutationError: unknown | null;
  takeMutationKey: string | null;
  takesProjection: ReturnType<typeof projectDirectorTakes> | null;
  taskDetails: Task[];
  taskEvents: TaskEvent[];
  taskError: unknown | null;
  mediaErrors: Record<number, string>;
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
  generationActionError,
  generationGate,
  generationRequestInFlight,
  generationTaskIds,
  onClearNote,
  onDelete,
  onGenerate,
  onRequestedDurationChange,
  onSlotClear,
  onSlotEnabledChange,
  onSlotUpload,
  onDeleteTake,
  onMediaError,
  onSetCurrentTake,
  onSave,
  onUserNoteChange,
  selection,
  selectedClipId,
  selectedShotIds,
  settingsActionError,
  settingsProjection,
  settingsSaving,
  slotMutationError,
  slotMutationKey,
  slotsProjection,
  takeMutationError,
  takeMutationKey,
  takesProjection,
  taskDetails,
  taskEvents,
  taskError,
  mediaErrors,
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
        <DirectorGenerationPanel
          actionError={generationActionError}
          detailPhase={detailPhase}
          generationGate={generationGate}
          inFlight={generationRequestInFlight}
          onGenerate={onGenerate}
          taskDetails={taskDetails}
          taskEvents={taskEvents}
          taskIds={generationTaskIds}
          taskError={taskError}
        />
        {detailPhase === "ready" && slotsProjection !== null && (
          <DirectorSlotsPanel
            mutationError={slotMutationError}
            mutationKey={slotMutationKey}
            onClear={onSlotClear}
            onEnabledChange={onSlotEnabledChange}
            onUpload={onSlotUpload}
            projection={slotsProjection}
          />
        )}
        {detailPhase === "ready" && takesProjection !== null && (
          <DirectorTakesPanel
            mediaErrors={mediaErrors}
            mutationError={takeMutationError}
            mutationKey={takeMutationKey}
            onDelete={onDeleteTake}
            onMediaError={onMediaError}
            onSetCurrent={onSetCurrentTake}
            projection={takesProjection}
          />
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
