import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

interface CoreInfo {
  port: number;
  token: string;
  spawnedAtMs: number;
}

type Health =
  | { state: "starting"; attempts: number }
  | { state: "ok"; body: Record<string, unknown>; readyAfterMs: number; attempts: number }
  | { state: "error"; message: string };

const POLL_INTERVAL_MS = 50;
const TIMEOUT_MS = 30_000;

async function waitForHealth(info: CoreInfo, onAttempt: (n: number) => void) {
  const url = `http://127.0.0.1:${info.port}/health`;
  const deadline = Date.now() + TIMEOUT_MS;
  for (let attempt = 1; ; attempt++) {
    onAttempt(attempt);
    try {
      const resp = await fetch(url, { headers: { "X-FreeRead-Token": info.token } });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return { body: await resp.json(), readyAfterMs: Date.now() - info.spawnedAtMs, attempt };
    } catch (err) {
      // 连接被拒绝说明 sidecar 还没监听；其他错误（401 等）直接报告
      if (err instanceof Error && err.message.startsWith("HTTP")) throw err;
      if (Date.now() > deadline) throw new Error(`sidecar 在 ${TIMEOUT_MS / 1000}s 内未就绪`);
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    }
  }
}

function App() {
  const [info, setInfo] = useState<CoreInfo | null>(null);
  const [health, setHealth] = useState<Health>({ state: "starting", attempts: 0 });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const coreInfo = await invoke<CoreInfo>("core_info");
        if (cancelled) return;
        setInfo(coreInfo);
        const result = await waitForHealth(coreInfo, (attempts) => {
          if (!cancelled) setHealth({ state: "starting", attempts });
        });
        if (!cancelled) {
          setHealth({ state: "ok", body: result.body, readyAfterMs: result.readyAfterMs, attempts: result.attempt });
        }
      } catch (err) {
        if (!cancelled) setHealth({ state: "error", message: String(err) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="container">
      <h1>FreeRead</h1>
      <p className="subtitle">M0：Tauri 2 + Python sidecar 验证</p>

      <dl>
        <dt>Core 地址</dt>
        <dd>{info ? `http://127.0.0.1:${info.port}` : "…"}</dd>
        <dt>Health</dt>
        <dd id="health-status" data-state={health.state} className={`status ${health.state}`}>
          {health.state === "starting" && `启动中…（第 ${health.attempts} 次探测）`}
          {health.state === "ok" && String(health.body.status)}
          {health.state === "error" && `错误：${health.message}`}
        </dd>
        {health.state === "ok" && (
          <>
            <dt>启动到可用</dt>
            <dd id="ready-after">{health.readyAfterMs} ms</dd>
            <dt>响应</dt>
            <dd>
              <code>{JSON.stringify(health.body)}</code>
            </dd>
          </>
        )}
      </dl>
    </main>
  );
}

export default App;
