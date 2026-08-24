import { requestJson, requestNoContent } from "./client";

export interface Style {
  id: number;
  name: string;
  prompt_fragment: string;
  created_at: string;
  updated_at: string;
}

export interface StyleCreate {
  name: string;
  prompt_fragment: string;
}

export interface StylePatch {
  name?: string;
  prompt_fragment?: string;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function listStyles(): Promise<Style[]> {
  return requestJson<Style[]>("/styles");
}

export function createStyle(input: StyleCreate): Promise<Style> {
  return requestJson<Style>("/styles", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function getStyle(id: number): Promise<Style> {
  return requestJson<Style>(`/styles/${id}`);
}

export function updateStyle(id: number, input: StylePatch): Promise<Style> {
  return requestJson<Style>(`/styles/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteStyle(id: number): Promise<void> {
  return requestNoContent(`/styles/${id}`, { method: "DELETE" });
}
