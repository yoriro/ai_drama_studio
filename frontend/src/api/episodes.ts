import { requestJson, requestNoContent } from "./client";

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

const jsonHeaders = { "Content-Type": "application/json" };

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
  return requestJson<Episode>(`/episodes/${id}`);
}

export function updateEpisode(id: number, input: EpisodePatch): Promise<Episode> {
  return requestJson<Episode>(`/episodes/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function generateAssets(id: number): Promise<GenerateAssetsResponse> {
  return requestJson<GenerateAssetsResponse>(
    `/episodes/${id}/generate-assets`,
    { method: "POST" },
  );
}

export function deleteEpisode(id: number): Promise<void> {
  return requestNoContent(`/episodes/${id}`, { method: "DELETE" });
}
