import { ApiProtocolError, requestJson } from "./client";

export interface HealthComponent {
  status: "healthy" | "unhealthy";
  message: string | null;
}

export interface WorkflowBindings {
  status: "valid";
  message: null;
  hashes: {
    zimage: string;
  };
}

export interface HealthResponse {
  vllm: HealthComponent;
  comfy: HealthComponent;
  workflow_bindings: WorkflowBindings;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actualKeys = Object.keys(value);
  return (
    actualKeys.length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function isHealthComponent(value: unknown): value is HealthComponent {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["status", "message"]) ||
    (value.status !== "healthy" && value.status !== "unhealthy")
  ) {
    return false;
  }

  if (value.status === "healthy") {
    return value.message === null;
  }

  return typeof value.message === "string" && value.message.length > 0;
}

function isWorkflowBindings(value: unknown): value is WorkflowBindings {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["status", "message", "hashes"]) ||
    value.status !== "valid" ||
    value.message !== null ||
    !isRecord(value.hashes) ||
    !hasExactKeys(value.hashes, ["zimage"])
  ) {
    return false;
  }

  return (
    typeof value.hashes.zimage === "string" &&
    /^[0-9a-f]{64}$/.test(value.hashes.zimage)
  );
}

function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["vllm", "comfy", "workflow_bindings"]) &&
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
