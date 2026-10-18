// 底部任务条：正在同步 / 解析的任务数与当前进度。

import { activeJobs, useApp } from "../../app/store";

const KIND_LABEL: Record<string, string> = {
  sync: "同步 Zotero",
  parse: "快速解析",
  parse_hq: "高质量解析",
  embed: "建立语义索引",
  model_download: "下载嵌入模型",
};

export function JobsBar() {
  const jobs = useApp((s) => s.jobs);
  const active = activeJobs(jobs);
  if (!active.length) return null;
  const running = active.filter((j) => j.status === "running");
  const current = running[0] ?? active[0];
  const label = KIND_LABEL[current.kind] ?? current.kind;
  return (
    <div className="jobs-bar" role="status" aria-live="polite">
      <md-linear-progress
        value={current.progress}
        indeterminate={current.status === "queued" || current.progress === 0 || undefined}
      />
      <span>
        {label}
        {current.message ? `：${current.message}` : ""}
      </span>
      <span>
        {running.length} 个进行中，{active.length - running.length} 个排队
      </span>
    </div>
  );
}
