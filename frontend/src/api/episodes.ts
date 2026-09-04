import {
  protocolError,
  requestJson,
  requestNoContent,
  requireNonNegativeSafeInteger,
  requireObjectWithKeys,
  requirePositiveSafeInteger,
  requireString,
} from "./client";

export interface Episode {
  id: number;
  project_id: number;
  seq: number;
  title: string;
  script_text: string;
  script_revision: number;
  assets_generated_script_revision: number | null;
  shots_generated_script_revision: number | null;
  created_at: string;
  updated_at: string;
}

export interface EpisodeCreate {
  seq: number;
  title: string;
  script_text?: string;
}

export interface EpisodePatch {
  seq?: number;
  title?: string;
  script_text?: string;
}

export interface GenerateAssetsResponse {
  task_id: number;
}

export interface GenerateShotsImpactResponse {
  clips_count: number;
  videos_count: number;
  confirm_token: string | null;
  expires_in: number | null;
}

export interface GenerateShotsResponse {
  task_id: number;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function parseEpisodeResponse(
  value: unknown,
  status = 200,
): Episode {
  const record = requireObjectWithKeys(
    value,
    [
      "id",
      "project_id",
      "seq",
      "title",
      "script_text",
      "script_revision",
      "assets_generated_script_revision",
      "shots_generated_script_revision",
      "created_at",
      "updated_at",
    ],
    [],
    status,
    "Episode response",
  );
  requirePositiveSafeInteger(record.id, "Episode.id", status);
  requirePositiveSafeInteger(record.project_id, "Episode.project_id", status);
  requirePositiveSafeInteger(record.seq, "Episode.seq", status);
  requireString(record.title, status, "Episode.title");
  requireString(record.script_text, status, "Episode.script_text");
  requirePositiveSafeInteger(record.script_revision, "Episode.script_revision", status);
  if (record.assets_generated_script_revision !== null) {
    requireNonNegativeSafeInteger(
      record.assets_generated_script_revision,
      "Episode.assets_generated_script_revision",
      status,
    );
  }
  if (record.shots_generated_script_revision !== null) {
    requireNonNegativeSafeInteger(
      record.shots_generated_script_revision,
      "Episode.shots_generated_script_revision",
      status,
    );
  }
  requireString(record.created_at, status, "Episode.created_at");
  requireString(record.updated_at, status, "Episode.updated_at");
  return record as unknown as Episode;
}

export function parseEpisodeListResponse(
  value: unknown,
  status = 200,
): Episode[] {
  if (!Array.isArray(value)) {
    return protocolError(status, "Episode list response must be an array");
  }
  return value.map((item) => parseEpisodeResponse(item, status));
}

export function listEpisodes(projectId: number): Promise<Episode[]> {
  return requestJson<Episode[]>(`/projects/${projectId}/episodes`);
}

export function createEpisode(
  projectId: number,
  input: EpisodeCreate,
): Promise<Episode> {
  return requestJson<Episode>(`/projects/${projectId}/episodes`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function getEpisode(id: number): Promise<Episode> {
  const episodeId = requirePositiveSafeInteger(id, "episodeId");
  return requestJson<Episode>(
    `/episodes/${episodeId}`,
    undefined,
    parseEpisodeResponse,
  );
}

export function updateEpisode(id: number, input: EpisodePatch): Promise<Episode> {
  return requestJson<Episode>(`/episodes/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function generateAssets(id: number): Promise<GenerateAssetsResponse> {
  const episodeId = requirePositiveSafeInteger(id, "episodeId");
  return requestJson<GenerateAssetsResponse>(
    `/episodes/${episodeId}/generate-assets`,
    { method: "POST" },
  );
}

export function readGenerateShotsImpact(
  id: number,
): Promise<GenerateShotsImpactResponse> {
  const episodeId = requirePositiveSafeInteger(id, "episodeId");
  return requestJson<GenerateShotsImpactResponse>(
    `/episodes/${episodeId}/generate-shots/impact`,
    { method: "POST" },
  );
}

export function generateShots(
  id: number,
  confirmToken?: string,
): Promise<GenerateShotsResponse> {
  const episodeId = requirePositiveSafeInteger(id, "episodeId");
  const body = confirmToken === undefined ? {} : { confirm_token: confirmToken };
  return requestJson<GenerateShotsResponse>(
    `/episodes/${episodeId}/generate-shots`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
  );
}

export function deleteEpisode(id: number): Promise<void> {
  const episodeId = requirePositiveSafeInteger(id, "episodeId");
  return requestNoContent(`/episodes/${episodeId}`, { method: "DELETE" });
}
