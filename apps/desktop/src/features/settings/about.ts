// 设置页「关于」：版本、检查与下载更新、贡献者。联网都在壳里做（src-tauri/src/update.rs），
// 浏览器开发模式下没有壳，这些功能不可用。

import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { isTauri } from "../../api/core";

export const REPO_URL = "https://github.com/cristimezzz/FreeRead";

export interface UpdateInfo {
  current: string;
  latest: string;
  available: boolean;
  notes: string;
  releaseUrl: string;
  publishedAt: string | null;
  asset: { name: string; size: number } | null;
  kind: InstallKind;
}

/** 当前程序的安装方式（src-tauri/src/update.rs 的 InstallKind）。 */
export type InstallKind = "nsis" | "portable" | "deb" | "rpm" | "aur" | "unknown";

/** 下载包在界面上的叫法。 */
export const ASSET_LABEL: Record<InstallKind, string> = {
  nsis: "安装包",
  portable: "便携版",
  deb: "deb 包",
  rpm: "rpm 包",
  aur: "",
  unknown: "",
};

/** 下载完成后的说明。 */
export function downloadedHint(kind: InstallKind, path: string): string {
  switch (kind) {
    case "nsis":
      return "下载完成，已通过校验。安装时 FreeRead 会关闭，装好后自动重新打开";
    case "portable":
      return `已保存到 ${path}，退出 FreeRead 后解压覆盖原目录即可`;
    case "deb":
      return `已保存到 ${path}，退出 FreeRead 后用 sudo apt install 安装这个文件`;
    case "rpm":
      return `已保存到 ${path}，退出 FreeRead 后用 sudo dnf install（或 zypper install）安装这个文件`;
    default:
      return `已保存到 ${path}`;
  }
}

export interface Contributor {
  login: string;
  avatarUrl: string;
  htmlUrl: string;
  contributions: number;
}

export const appVersion = (): Promise<string | null> => (isTauri() ? getVersion() : Promise.resolve(null));

export const checkUpdate = () => invoke<UpdateInfo>("check_update");

/** 下载最近一次检查到的包，onProgress 收到 0–1 的进度。返回保存路径。 */
export async function downloadUpdate(onProgress: (p: number) => void): Promise<string> {
  const unlisten = await listen<{ received: number; total: number }>("update-progress", (e) =>
    onProgress(e.payload.total ? e.payload.received / e.payload.total : 0),
  );
  try {
    return await invoke<string>("download_update");
  } finally {
    unlisten();
  }
}

/** 安装版运行安装包并退出应用；便携版、deb / rpm 在文件管理器里显示下载的包。 */
export const applyUpdate = () => invoke<void>("apply_update");

let contributors: Promise<Contributor[]> | null = null;

/** 贡献者列表，一次运行只取一次；失败后下次再试。 */
export function listContributors(): Promise<Contributor[]> {
  contributors ??= invoke<Contributor[]>("list_contributors").catch((e) => {
    contributors = null;
    throw e;
  });
  return contributors;
}

/** 用系统浏览器打开 GitHub 页面（shell 插件只放行 github.com 与 zotero://，见 tauri.conf.json）。 */
export async function openExternal(url: string): Promise<void> {
  if (isTauri()) await invoke("plugin:shell|open", { path: url });
  else window.open(url, "_blank", "noopener");
}

export function formatSize(bytes: number): string {
  if (bytes < 1 << 20) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1 << 20)).toFixed(1)} MB`;
}

/** GitHub 的 ISO 时间 → 2026-10-20；空值或解析不了时返回空串。 */
export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Release 说明是 Markdown，这里只按纯文本显示：去掉标题井号、粗体星号，列表符号换成圆点。 */
export const plainNotes = (md: string) =>
  md
    .replace(/\r\n/g, "\n")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/^(\s*)[-*]\s+/gm, "$1· ")
    .trim();

/** 头像缩到显示尺寸的两倍，avatar_url 已带 `?v=4`。 */
export const avatarSrc = (url: string, px: number) => `${url}${url.includes("?") ? "&" : "?"}s=${px * 2}`;
