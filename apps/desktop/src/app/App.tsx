import { useEffect, useState } from "react";
import { connect } from "../api/client";
import { CoreExitedError, defaultExitSource, describeExit, getCoreInfo, waitForHealth } from "../api/core";
import { NavigationRail } from "../components/m3/NavigationRail";
import { Snackbar } from "../components/m3/Snackbar";
import { JobsBar } from "../features/jobs/JobsBar";
import { LibraryView } from "../features/library/LibraryView";
import { ReaderView } from "../features/reader/ReaderView";
import { SettingsView } from "../features/settings/SettingsView";
import { startEventStream, useApp } from "./store";
import { applyTheme } from "./theme";

type Boot = { state: "starting" } | { state: "ready" } | { state: "error"; message: string; stderrTail?: string[] };

export default function App() {
  const [boot, setBoot] = useState<Boot>({ state: "starting" });
  const view = useApp((s) => s.view);
  const settings = useApp((s) => s.settings);

  useEffect(() => {
    applyTheme("#6750A4", "system", "standard");
    let stop: (() => void) | undefined;
    let unwatch: Promise<() => void> | undefined;
    let cancelled = false;
    (async () => {
      try {
        const info = await getCoreInfo();
        await waitForHealth(info);
        connect(info);
        await useApp.getState().loadSettings();
        if (cancelled) return;
        stop = startEventStream();
        // 运行中 sidecar 退出：后续请求都会失败，停掉推送重连，常驻提示用户重新打开。
        unwatch = defaultExitSource()?.((exit) => {
          stop?.();
          useApp
            .getState()
            .toast(`Core Service 已退出（${describeExit(exit)}），请重新打开 FreeRead`, { sticky: true });
        });
        unwatch?.catch((err) => console.warn("watch core exit failed", err));
        setBoot({ state: "ready" });
      } catch (err) {
        if (cancelled) return;
        const stderrTail = err instanceof CoreExitedError ? err.exit.stderrTail : undefined;
        setBoot({ state: "error", message: err instanceof Error ? err.message : String(err), stderrTail });
      }
    })();
    return () => {
      cancelled = true;
      stop?.();
      unwatch?.then((off) => off()).catch(() => {});
    };
  }, []);

  // 跟随系统深浅色
  useEffect(() => {
    if (!settings || settings.appearance.theme_mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const a = settings.appearance;
    const onChange = () => applyTheme(a.seed_color, a.theme_mode, a.contrast);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [settings]);

  if (boot.state !== "ready") {
    return (
      <div className="boot">
        {boot.state === "starting" ? (
          <div>
            <md-circular-progress indeterminate />
            <p>正在启动 FreeRead…</p>
          </div>
        ) : (
          <div>
            <h2>无法连接 Core Service</h2>
            <p>{boot.message}</p>
            {boot.stderrTail && boot.stderrTail.length > 0 && (
              <pre className="boot-log">{boot.stderrTail.join("\n")}</pre>
            )}
            <p>如果被杀毒软件拦截，请把 FreeRead 加入信任列表后重新打开。</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="app">
      <NavigationRail />
      <main className="main">
        {view.name === "library" && <LibraryView />}
        {view.name === "reader" && <ReaderView key={view.docId} {...view} />}
        {view.name === "settings" && <SettingsView />}
        <JobsBar />
      </main>
      <Snackbar />
    </div>
  );
}
