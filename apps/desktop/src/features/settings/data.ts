// 设置页「数据」：统计与删除应用数据。删除在壳里做（src-tauri/src/app_data.rs）：
// 先停 sidecar、删文件、清钥匙串，再重启应用。浏览器开发模式下没有壳，不可用。

import { invoke } from "@tauri-apps/api/core";

export interface DataUsage {
  /** 数据目录 */
  root: string;
  /** 「文献、笔记与设置」占用字节 */
  library: number;
  /** 「本机解析引擎与模型」占用字节 */
  engines: number;
}

export interface DeleteScope {
  library: boolean;
  keys: boolean;
  engines: boolean;
}

export const DEFAULT_SCOPE: DeleteScope = { library: true, keys: true, engines: false };

export const SCOPE_ITEMS: { key: keyof DeleteScope; label: string; desc: string }[] = [
  {
    key: "library",
    label: "文献、笔记与设置",
    desc: "导入的文档与解析结果，翻译、总结、问答、图谱、标注，Zotero 快照、日志和全部设置",
  },
  { key: "keys", label: "API Key", desc: "系统钥匙串里保存的大模型服务与解析服务密钥" },
  { key: "engines", label: "本机解析引擎与模型", desc: "应用内安装的 MinerU / Docling 与嵌入模型，删除后需重新下载" },
];

export const appDataUsage = () => invoke<DataUsage>("app_data_usage");

/** 成功时应用会重启，这个 Promise 不会 resolve；失败时 reject 原因。 */
export const deleteAppData = (scope: DeleteScope) => invoke<void>("delete_app_data", { ...scope });

export const restartApp = () => invoke<void>("restart_app");

export const nothingSelected = (s: DeleteScope) => !s.library && !s.keys && !s.engines;

/** 占用大小：GB 以上保留一位小数。 */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 KB";
  if (bytes < 1 << 20) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1 << 30) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  return `${(bytes / (1 << 30)).toFixed(1)} GB`;
}

/** 确认对话框里的说明：要删什么、删后会怎样。 */
export function deleteSummary(s: DeleteScope): string {
  const picked = SCOPE_ITEMS.filter((i) => s[i.key]).map((i) => i.label);
  if (!picked.length) return "请至少勾选一项。";
  return `将删除：${picked.join("、")}。删除后无法恢复，FreeRead 会自动重启。`;
}
