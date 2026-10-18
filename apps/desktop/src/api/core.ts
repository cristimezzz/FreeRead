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

/** sidecar 进程退出信息，壳的 `core-terminated` 事件 / `core_status` 命令（src-tauri/src/lib.rs）。 */
export interface CoreExit {
  code: number | null;
  signal: number | null;
  stderrTail: string[];
}

/**
 * 订阅 sidecar 退出：sidecar 已经退出时也要（尽快）回调一次。返回取消订阅函数。
 * 浏览器模式下拿不到进程状态，为 undefined。
 */
export type CoreExitSource = (onExit: (exit: CoreExit) => void) => Promise<() => void>;

/** Tauri 模式：先订阅事件再查状态，订阅前就已退出的情况也不会漏掉。 */
const tauriExitSource: CoreExitSource = async (onExit) => {
  const [{ listen }, { invoke }] = await Promise.all([import("@tauri-apps/api/event"), import("@tauri-apps/api/core")]);
  let fired = false;
  const once = (exit: CoreExit) => {
    if (fired) return;
    fired = true;
    onExit(exit);
  };
  const unlisten = await listen<CoreExit>("core-terminated", (e) => once(e.payload));
  const exited = await invoke<CoreExit | null>("core_status");
  if (exited) once(exited);
  return unlisten;
};

export const defaultExitSource = (): CoreExitSource | undefined => (isTauri() ? tauriExitSource : undefined);

export function describeExit(exit: CoreExit): string {
  if (exit.code !== null) return `退出码 ${exit.code}`;
  if (exit.signal !== null) return `信号 ${exit.signal}`;
  return "原因未知";
}

export class CoreExitedError extends Error {
  constructor(readonly exit: CoreExit) {
    super(`Core Service 已退出（${describeExit(exit)}）`);
  }
}

const POLL_INTERVAL_MS = 100;
const TIMEOUT_MS = 30_000;

export interface WaitOptions {
  /** 默认：Tauri 模式订阅壳的退出事件，浏览器模式不订阅。 */
  exits?: CoreExitSource;
  timeoutMs?: number;
}

/**
 * 等 sidecar 的 /health 可用。连接被拒绝说明还没监听，继续等；401 等直接报错。
 * 同时监听 sidecar 退出：进程退出就立即以 {@link CoreExitedError} 失败，不再等到超时。
 */
export async function waitForHealth(info: CoreInfo, opts: WaitOptions = {}): Promise<void> {
  const { exits = defaultExitSource(), timeoutMs = TIMEOUT_MS } = opts;
  let exited: CoreExit | undefined;
  let rejectExit: (err: Error) => void = () => {};
  const exitPromise = new Promise<never>((_, reject) => (rejectExit = reject));
  const unsubscribe = exits?.((exit) => {
    exited = exit;
    rejectExit(new CoreExitedError(exit));
  });
  try {
    // 订阅本身失败（拿不到壳的事件）时退化成只轮询。
    await Promise.race([unsubscribe?.catch(() => undefined), exitPromise]);
    await Promise.race([pollHealth(info, timeoutMs, () => exited !== undefined), exitPromise]);
  } finally {
    unsubscribe?.then((off) => off()).catch(() => {});
  }
}

async function pollHealth(info: CoreInfo, timeoutMs: number, stopped: () => boolean): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!stopped()) {
    try {
      const resp = await fetch(`${info.baseUrl}/health`, { headers: { "X-FreeRead-Token": info.token } });
      if (resp.ok) return;
      throw new HttpStatusError(resp.status);
    } catch (err) {
      if (err instanceof HttpStatusError) throw err;
      if (Date.now() > deadline) throw new Error(`Core Service 在 ${timeoutMs / 1000}s 内未就绪`);
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    }
  }
}

class HttpStatusError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}
