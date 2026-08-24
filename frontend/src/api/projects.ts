import { requestJson, requestNoContent } from "./client";

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
  return requestJson<Project>(`/projects/${id}`);
}

export function updateProject(id: number, input: ProjectPatch): Promise<Project> {
  return requestJson<Project>(`/projects/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteProject(id: number): Promise<void> {
  return requestNoContent(`/projects/${id}`, { method: "DELETE" });
}
