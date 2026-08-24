import type { HealthResponse } from "../api/health";

export type BackendState =
  | { status: "loading" }
  | { status: "connected"; health: HealthResponse }
  | { status: "error"; message: string };

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
        后端连接失败：{state.message}
      </section>
    );
  }

  return (
    <section
      aria-label="后端连接状态"
      className="backend-status backend-status-connected"
    >
      <strong>后端已连接</strong>
      <div className="backend-checks">
        <span>vLLM：未检查</span>
        <span>ComfyUI：未检查</span>
        <span>工作流绑定：未检查</span>
      </div>
    </section>
  );
}
