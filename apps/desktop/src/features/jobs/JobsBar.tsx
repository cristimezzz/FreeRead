// 底部任务条：正在同步 / 解析的任务数与当前进度；点开浮窗（Popover）列出全部进行中与排队的任务。

import { useEffect, useState } from "react";
import { activeJobs, useApp } from "../../app/store";
import {
  Queue,
  QueueItem,
  QueueItemContent,
  QueueItemDescription,
  QueueItemIndicator,
  QueueList,
  QueueSection,
  QueueSectionContent,
  QueueSectionLabel,
  QueueSectionTrigger,
} from "../../components/ai-elements/queue";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import { Progress } from "../../components/ui/progress";
import { cn } from "../../lib/utils";
import { jobRows, KIND_LABEL } from "./jobList";

export function JobsBar() {
  const jobs = useApp((s) => s.jobs);
  const active = activeJobs(jobs);
  const [open, setOpen] = useState(false);

  // 任务全部结束后收起，下次出现任务时不自动展开
  useEffect(() => {
    if (!active.length) setOpen(false);
  }, [active.length]);

  // 窗口失焦时收起
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("blur", close);
    return () => window.removeEventListener("blur", close);
  }, [open]);

  if (!active.length) return null;
  const running = active.filter((j) => j.status === "running");
  const current = running[0] ?? active[0];
  const label = KIND_LABEL[current.kind] ?? current.kind;
  const rows = jobRows(active);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="text-foreground/80 hover:bg-accent aria-expanded:bg-accent focus-visible:outline-ring flex min-h-11 w-full flex-none flex-wrap items-center gap-3.5 border-t px-12 text-left text-[13px] transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 max-[900px]:px-6 [&>[data-slot=progress]]:w-28"
        >
          <Progress value={current.status === "queued" || current.progress === 0 ? undefined : current.progress * 100} />
          <span className="min-w-0 truncate" role="status" aria-live="polite">
            {label}
            {current.message ? `：${current.message}` : ""}
          </span>
          <span className="text-muted-foreground ml-auto">
            {running.length} 个进行中，{active.length - running.length} 个排队
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        sideOffset={8}
        alignOffset={40}
        aria-label="任务列表"
        className="flex max-h-[min(420px,60vh)] w-[min(400px,calc(100vw-80px))] flex-col p-0 text-[13px]"
      >
        <div className="flex items-baseline justify-between px-4 pt-3 pb-2 font-medium">
          <span>任务</span>
          <span className="text-muted-foreground text-xs font-normal">
            {running.length} 进行中 · {active.length - running.length} 排队
          </span>
        </div>
        <Queue className="overflow-y-auto px-1.5 pb-1.5">
          {[
            { key: "running", label: "进行中", rows: rows.filter((r) => r.job.status === "running") },
            { key: "queued", label: "排队", rows: rows.filter((r) => r.job.status !== "running") },
          ]
            .filter((g) => g.rows.length)
            .map((g) => (
              <QueueSection key={g.key}>
                <QueueSectionTrigger>
                  <QueueSectionLabel label={g.label} count={g.rows.length} />
                </QueueSectionTrigger>
                <QueueSectionContent>
                  <QueueList>
                    {g.rows.map((r) => (
                      <QueueItem key={r.job.id}>
                        <div className="flex items-baseline gap-2">
                          <QueueItemIndicator />
                          <QueueItemContent className="min-w-0 flex-1 truncate">{r.label}</QueueItemContent>
                          <span
                            className={cn(
                              "flex-none tabular-nums",
                              r.job.status === "running" ? "text-brand-ink" : "text-muted-foreground",
                            )}
                          >
                            {r.status}
                          </span>
                        </div>
                        {r.job.message && (
                          <QueueItemDescription className="truncate">{r.job.message}</QueueItemDescription>
                        )}
                        {r.progress !== null && (
                          <Progress value={r.progress === undefined ? undefined : r.progress * 100} />
                        )}
                      </QueueItem>
                    ))}
                  </QueueList>
                </QueueSectionContent>
              </QueueSection>
            ))}
        </Queue>
      </PopoverContent>
    </Popover>
  );
}
