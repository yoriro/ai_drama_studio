import { ApiProtocolError, requestJson } from "./client";

export interface HealthComponent {
  status: "not_checked";
}

export interface WorkflowBindings extends HealthComponent {
  hashes: Record<string, string>;
}

export interface HealthResponse {
  vllm: HealthComponent;
  comfy: HealthComponent;
  workflow_bindings: WorkflowBindings;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isHealthComponent(value: unknown): value is HealthComponent {
  return isRecord(value) && value.status === "not_checked";
}

function isWorkflowBindings(value: unknown): value is WorkflowBindings {
  if (!isRecord(value) || !isHealthComponent(value) || !isRecord(value.hashes)) {
    return false;
  }

  return Object.values(value.hashes).every((hash) => typeof hash === "string");
}

function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    isRecord(value) &&
    isHealthComponent(value.vllm) &&
    isHealthComponent(value.comfy) &&
    isWorkflowBindings(value.workflow_bindings)
  );
}

export async function getHealth(): Promise<HealthResponse> {
  const payload = await requestJson<unknown>("/system/health");
  if (!isHealthResponse(payload)) {
    throw new ApiProtocolError(200, "Health response did not match its schema");
  }
  return payload;
}
