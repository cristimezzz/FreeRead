// 任务浮窗的排序与状态文字：进行中在前，排队的按 worker 取任务的顺序（created_at, id）。

import type { Job } from "../../app/store";

export const KIND_LABEL: Record<string, string> = {
  sync: "同步 Zotero",
  parse: "快速解析",
  parse_hq: "高质量解析",
  embed: "建立语义索引",
  model_download: "下载嵌入模型",
  translate_doc: "翻译全文",
  glossary_extract: "抽取术语",
  kg_extract: "抽取图谱",
};

export interface JobRow {
  job: Job;
  label: string;
  /** 进度条取值；undefined 表示不定进度，null 表示不显示进度条（排队中） */
  progress: number | null | undefined;
  /** 右侧状态：百分比、「进行中」、「排队第 N 位」或「等待前置任务」 */
  status: string;
}

const byQueueOrder = (a: Job, b: Job) =>
  a.created_at === b.created_at ? (a.id < b.id ? -1 : 1) : a.created_at < b.created_at ? -1 : 1;

/** 只接收进行中 / 排队的任务。 */
export function jobRows(active: Job[]): JobRow[] {
  const running = active
    .filter((j) => j.status === "running")
    .sort((a, b) => ((a.started_at ?? "") < (b.started_at ?? "") ? -1 : 1));
  const queued = active.filter((j) => j.status === "queued").sort(byQueueOrder);
  const pending = new Set(active.map((j) => j.id));
  return [
    ...running.map((job) => ({
      job,
      label: KIND_LABEL[job.kind] ?? job.kind,
      progress: job.progress > 0 ? job.progress : undefined,
      status: job.progress > 0 ? `${Math.round(job.progress * 100)}%` : "进行中",
    })),
    ...queued.map((job, i) => ({
      job,
      label: KIND_LABEL[job.kind] ?? job.kind,
      progress: null,
      status: job.depends_on && pending.has(job.depends_on) ? "等待前置任务" : `排队第 ${i + 1} 位`,
    })),
  ];
}
