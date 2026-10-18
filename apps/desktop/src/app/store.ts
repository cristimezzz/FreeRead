// 全局状态：导航、设置、任务进度（/jobs/stream）。

import { create } from "zustand";
import { api, unwrap, type Schemas } from "../api/client";
import { streamSse } from "../api/sse";
import { applyTheme } from "./theme";

export type Settings = Schemas["AppSettings"];
export type Job = Schemas["JobOut"];
export type DocumentStatus = Schemas["DocumentOut"];

export type View =
  | { name: "library" }
  | { name: "reader"; docId: string; itemId: string; title: string }
  | { name: "settings" };

interface AppState {
  view: View;
  settings: Settings | null;
  jobs: Record<string, Job>;
  /** document 事件计数：文献库 / 阅读器据此刷新 */
  documentVersion: Record<string, number>;
  libraryVersion: number;
  snackbar: string | null;

  navigate: (view: View) => void;
  loadSettings: () => Promise<void>;
  saveSettings: (settings: Settings) => Promise<Settings>;
  toast: (message: string | null) => void;
  bumpLibrary: () => void;
}

export const useApp = create<AppState>((set, get) => ({
  view: { name: "library" },
  settings: null,
  jobs: {},
  documentVersion: {},
  libraryVersion: 0,
  snackbar: null,

  navigate: (view) => set({ view }),

  loadSettings: async () => {
    const settings = unwrap(await api().GET("/settings"));
    set({ settings });
    const a = settings.appearance;
    applyTheme(a.seed_color, a.theme_mode, a.contrast);
  },

  saveSettings: async (settings) => {
    const saved = unwrap(await api().PUT("/settings", { body: settings }));
    set({ settings: saved });
    const a = saved.appearance;
    applyTheme(a.seed_color, a.theme_mode, a.contrast);
    return saved;
  },

  toast: (message) => set({ snackbar: message }),
  bumpLibrary: () => set({ libraryVersion: get().libraryVersion + 1 }),
}));

const ACTIVE = new Set(["queued", "running"]);

export const activeJobs = (jobs: Record<string, Job>) =>
  Object.values(jobs).filter((j) => ACTIVE.has(j.status));

/** 订阅任务与文档状态推送；断开后重连。返回停止函数。 */
export function startEventStream(): () => void {
  const controller = new AbortController();
  const refreshJobs = async () => {
    const jobs = unwrap(await api().GET("/jobs", { params: { query: { limit: 200 } } }));
    useApp.setState({ jobs: Object.fromEntries(jobs.map((j) => [j.id, j])) });
  };

  const run = async () => {
    while (!controller.signal.aborted) {
      try {
        await streamSse("/jobs/stream", { signal: controller.signal }, (e) => {
          if (e.event === "ready" || e.event === "resync") {
            void refreshJobs();
          } else if (e.event === "job") {
            const job = e.data as Job;
            const prev = useApp.getState().jobs[job.id];
            useApp.setState((s) => ({ jobs: { ...s.jobs, [job.id]: job } }));
            if (job.kind === "sync" && job.status === "done" && prev?.status !== "done") {
              useApp.getState().bumpLibrary();
            }
            if (job.status === "failed" && prev?.status !== "failed") {
              useApp.getState().toast(`任务失败：${job.error ?? job.kind}`);
            }
          } else if (e.event === "document") {
            const doc = e.data as DocumentStatus;
            useApp.setState((s) => ({
              documentVersion: {
                ...s.documentVersion,
                [doc.doc_id]: (s.documentVersion[doc.doc_id] ?? 0) + 1,
              },
              libraryVersion: s.libraryVersion + 1,
            }));
          }
        });
      } catch {
        if (controller.signal.aborted) return;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
  };
  void run();
  return () => controller.abort();
}
