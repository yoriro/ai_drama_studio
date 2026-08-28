import type { HealthResponse } from "../api/health";

export type BackendState =
  | { status: "loading" }
  | { status: "connected"; health: HealthResponse }
  | { status: "error"; code: string; message: string };

interface BackendStatusProps {
  state: BackendState;
}

export function BackendStatus({ state }: BackendStatusProps) {
  if (state.status === "loading") {
    return (
      <section aria-label="后端连接状态" className="backend-status" role="status">
        正在连接后端…
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section
        aria-label="后端连接状态"
        className="backend-status backend-status-error"
        role="alert"
      >
        后端连接失败（{state.code}）：{state.message}
      </section>
    );
  }

  return (
    <section
      aria-label="后端连接状态"
      className={
        state.health.vllm.status === "unhealthy" ||
        state.health.comfy.status === "unhealthy"
          ? "backend-status backend-status-error"
          : "backend-status backend-status-connected"
      }
      role={
        state.health.vllm.status === "unhealthy" ||
        state.health.comfy.status === "unhealthy"
          ? "alert"
          : undefined
      }
    >
      <strong>
        {state.health.vllm.status === "unhealthy" ||
        state.health.comfy.status === "unhealthy"
          ? "外部服务诊断异常"
          : "后端已连接"}
      </strong>
      <div className="backend-checks">
        <span>vLLM：{describeComponent(state.health.vllm)}</span>
        <span>ComfyUI：{describeComponent(state.health.comfy)}</span>
        <span>Z-Image binding：{state.health.workflow_bindings.status}</span>
      </div>
    </section>
  );
}

function describeComponent(component: HealthResponse["vllm"]): string {
  if (component.status === "healthy") {
    return "healthy";
  }
  return `unhealthy（${component.message}）`;
}
