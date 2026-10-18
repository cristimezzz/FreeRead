// 连接 Core Service（Python sidecar）。见 docs/01-architecture.md §3。
// 在 Tauri 里从 core_info 命令取端口和会话 token；单独用浏览器开发时
// （vite dev + 手动启动的 freeread-core）从 VITE_CORE_URL / VITE_CORE_TOKEN 读取。

export interface CoreInfo {
  baseUrl: string;
  token: string;
  spawnedAtMs?: number;
}

interface TauriCoreInfo {
  port: number;
  token: string;
  spawnedAtMs: number;
}

export const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function getCoreInfo(): Promise<CoreInfo> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const info = await invoke<TauriCoreInfo>("core_info");
    return { baseUrl: `http://127.0.0.1:${info.port}`, token: info.token, spawnedAtMs: info.spawnedAtMs };
  }
  const baseUrl = import.meta.env.VITE_CORE_URL ?? "http://127.0.0.1:8765";
  const token = import.meta.env.VITE_CORE_TOKEN ?? "";
  return { baseUrl, token };
}

const POLL_INTERVAL_MS = 100;
const TIMEOUT_MS = 30_000;

/** 等 sidecar 的 /health 可用。连接被拒绝说明还没监听，继续等；401 等直接报错。 */
export async function waitForHealth(info: CoreInfo): Promise<void> {
  const deadline = Date.now() + TIMEOUT_MS;
  for (;;) {
    try {
      const resp = await fetch(`${info.baseUrl}/health`, { headers: { "X-FreeRead-Token": info.token } });
      if (resp.ok) return;
      throw new HttpStatusError(resp.status);
    } catch (err) {
      if (err instanceof HttpStatusError) throw err;
      if (Date.now() > deadline) throw new Error(`Core Service 在 ${TIMEOUT_MS / 1000}s 内未就绪`);
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    }
  }
}

class HttpStatusError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}
