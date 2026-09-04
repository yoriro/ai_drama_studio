import {
  protocolError,
  requestJson,
  requestNoContent,
  requireObjectWithKeys,
  requirePositiveSafeInteger,
  requireString,
} from "./client";

export interface Project {
  id: number;
  name: string;
  style_id: number;
  created_at: string;
}

export interface ProjectCreate {
  name: string;
  style_id: number;
}

export interface ProjectPatch {
  name?: string;
  style_id?: number;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function parseProjectResponse(
  value: unknown,
  status = 200,
): Project {
  const record = requireObjectWithKeys(
    value,
    ["id", "name", "style_id", "created_at"],
    [],
    status,
    "Project response",
  );
  requirePositiveSafeInteger(record.id, "Project.id", status);
  requirePositiveSafeInteger(record.style_id, "Project.style_id", status);
  requireString(record.name, status, "Project.name");
  requireString(record.created_at, status, "Project.created_at");
  return record as unknown as Project;
}

export function parseProjectListResponse(
  value: unknown,
  status = 200,
): Project[] {
  if (!Array.isArray(value)) {
    return protocolError(status, "Project list response must be an array");
  }
  return value.map((item) => parseProjectResponse(item, status));
}

export function listProjects(): Promise<Project[]> {
  return requestJson<Project[]>("/projects");
}

export function createProject(input: ProjectCreate): Promise<Project> {
  return requestJson<Project>("/projects", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function getProject(id: number): Promise<Project> {
  const projectId = requirePositiveSafeInteger(id, "projectId");
  return requestJson<Project>(
    `/projects/${projectId}`,
    undefined,
    parseProjectResponse,
  );
}

export function updateProject(id: number, input: ProjectPatch): Promise<Project> {
  return requestJson<Project>(`/projects/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteProject(id: number): Promise<void> {
  const projectId = requirePositiveSafeInteger(id, "projectId");
  return requestNoContent(`/projects/${projectId}`, { method: "DELETE" });
}
