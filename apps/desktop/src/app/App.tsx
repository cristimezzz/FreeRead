import { useEffect, useState } from "react";
import { connect } from "../api/client";
import { getCoreInfo, waitForHealth } from "../api/core";
import { NavigationRail } from "../components/m3/NavigationRail";
import { Snackbar } from "../components/m3/Snackbar";
import { JobsBar } from "../features/jobs/JobsBar";
import { LibraryView } from "../features/library/LibraryView";
import { ReaderView } from "../features/reader/ReaderView";
import { SettingsView } from "../features/settings/SettingsView";
import { startEventStream, useApp } from "./store";
import { applyTheme } from "./theme";

type Boot = { state: "starting" } | { state: "ready" } | { state: "error"; message: string };

export default function App() {
  const [boot, setBoot] = useState<Boot>({ state: "starting" });
  const view = useApp((s) => s.view);
  const settings = useApp((s) => s.settings);

  useEffect(() => {
    applyTheme("#6750A4", "system", "standard");
    let stop: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      try {
        const info = await getCoreInfo();
        await waitForHealth(info);
        connect(info);
        await useApp.getState().loadSettings();
        if (cancelled) return;
        stop = startEventStream();
        setBoot({ state: "ready" });
      } catch (err) {
        if (!cancelled) setBoot({ state: "error", message: String(err) });
      }
    })();
    return () => {
      cancelled = true;
      stop?.();
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
