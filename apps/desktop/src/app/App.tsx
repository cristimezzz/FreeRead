import { useEffect, useState } from "react";
import { connect } from "../api/client";
import { CoreExitedError, defaultExitSource, describeExit, getCoreInfo, waitForHealth } from "../api/core";
import { ContextMenu, installDefaultMenu } from "../components/ContextMenu";
import { BrandMark } from "../components/icons";
import { Sidebar } from "../components/Sidebar";
import { Snackbar } from "../components/Snackbar";
import { Titlebar } from "../components/Titlebar";
import { Progress } from "../components/ui/progress";
import { SidebarInset, SidebarProvider } from "../components/ui/sidebar";
import { TooltipProvider } from "../components/ui/tooltip";
import { JobsBar } from "../features/jobs/JobsBar";
import { LibraryView } from "../features/library/LibraryView";
import { ReaderView } from "../features/reader/ReaderView";
import { SettingsView } from "../features/settings/SettingsView";
import { WelcomeView } from "../features/welcome/WelcomeView";
import { startEventStream, useApp } from "./store";
import { applyTheme, DEFAULT_ACCENT } from "./theme";

type Boot = { state: "starting" } | { state: "ready" } | { state: "error"; message: string; stderrTail?: string[] };

export default function App() {
  const [boot, setBoot] = useState<Boot>({ state: "starting" });
  const view = useApp((s) => s.view);
  const settings = useApp((s) => s.settings);

  useEffect(() => {
    applyTheme(DEFAULT_ACCENT, "system", "standard");
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

  // 屏蔽 WebView 默认右键菜单（启动页也一样）
  useEffect(() => installDefaultMenu((m) => useApp.getState().toast(m)), []);

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
      <>
        <Titlebar />
        <div className="text-muted-foreground flex h-full flex-col items-center justify-center gap-5 p-6 text-center text-[13px]">
          <BrandMark size={56} />
          <div className="text-foreground font-serif text-3xl font-medium tracking-tight">FreeRead</div>
          {boot.state === "starting" ? (
            <>
              <Progress className="h-1 w-44" />
              <p>正在启动 FreeRead…</p>
            </>
          ) : (
            <div className="text-foreground/80 flex max-w-3xl flex-col items-center gap-2.5 leading-relaxed">
              <h2 className="text-foreground font-serif text-xl font-medium">无法连接 Core Service</h2>
              <p>{boot.message}</p>
              {boot.stderrTail && boot.stderrTail.length > 0 && (
                <pre className="bg-card max-h-[40vh] max-w-[min(720px,90vw)] overflow-auto rounded-lg border px-3.5 py-3 text-left font-mono text-xs leading-relaxed whitespace-pre-wrap">
                  {boot.stderrTail.join("\n")}
                </pre>
              )}
              <p>如果被杀毒软件拦截，请把 FreeRead 加入信任列表后重新打开。</p>
            </div>
          )}
        </div>
      </>
    );
  }

  // 新安装：先走欢迎向导（配置大模型、解析服务，询问是否从 Zotero 导入）
  if (settings && !settings.onboarding_done) {
    return (
      <TooltipProvider delayDuration={400}>
        <Titlebar />
        <WelcomeView />
        <Snackbar />
        <ContextMenu />
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={400}>
      {/* 阅读器里侧栏收成图标栏，把宽度让给正文 */}
      <SidebarProvider open={view.name !== "reader"} className="h-full min-h-0">
        <Titlebar />
        <Sidebar />
        <SidebarInset className="min-w-0 min-h-0 pt-(--titlebar-h)">
          {view.name === "library" && <LibraryView />}
          {view.name === "reader" && <ReaderView key={view.docId} {...view} />}
          {view.name === "settings" && <SettingsView />}
          <JobsBar />
        </SidebarInset>
      </SidebarProvider>
      <Snackbar />
      <ContextMenu />
    </TooltipProvider>
  );
}
