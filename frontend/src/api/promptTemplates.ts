import { requestJson } from "./client";

export interface PromptTemplate {
  id: number;
  key: string;
  content: string;
  updated_at: string;
}

export interface PromptTemplatePatch {
  content: string;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function listPromptTemplates(): Promise<PromptTemplate[]> {
  return requestJson<PromptTemplate[]>("/prompt-templates");
}

export function updatePromptTemplate(
  key: string,
  input: PromptTemplatePatch,
): Promise<PromptTemplate> {
  return requestJson<PromptTemplate>(`/prompt-templates/${key}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}
