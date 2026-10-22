// 底部任务条：正在同步 / 解析的任务数与当前进度；点开浮窗列出全部进行中与排队的任务。

import { useEffect, useId, useRef, useState } from "react";
import { activeJobs, useApp } from "../../app/store";
import { usePresence } from "../../components/motion";
import { Progress } from "../../components/ui";
import { jobRows, KIND_LABEL } from "./jobList";

export function JobsBar() {
  const jobs = useApp((s) => s.jobs);
  const active = activeJobs(jobs);
  const [open, setOpen] = useState(false);
  const shown = open && active.length > 0;
  const { mounted, closing } = usePresence(shown);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  // 任务全部结束后收起，下次出现任务时不自动展开
  useEffect(() => {
    if (!active.length) setOpen(false);
  }, [active.length]);

  // 点外部或按 Esc 关闭；Esc 时焦点回到任务条
  useEffect(() => {
    if (!shown) return;
    const outside = (e: Event) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      setOpen(false);
      button.current?.focus({ preventScroll: true });
    };
    const close = () => setOpen(false);
    window.addEventListener("pointerdown", outside, true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("blur", close);
    return () => {
      window.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", close);
    };
  }, [shown]);

  if (!active.length) return null;
  const running = active.filter((j) => j.status === "running");
  const current = running[0] ?? active[0];
  const label = KIND_LABEL[current.kind] ?? current.kind;
  return (
    <div ref={wrap} className="jobs">
      {mounted && (
        <div
          id={panelId}
          className="jobs-pop"
          role="dialog"
          aria-label="任务列表"
          data-state={closing ? "closing" : "open"}
        >
          <div className="jobs-pop-head">
            <span>任务</span>
            <span className="jobs-pop-count">
              {running.length} 进行中 · {active.length - running.length} 排队
            </span>
          </div>
          <ul className="jobs-list">
            {jobRows(active).map((r) => (
              <li key={r.job.id} className="jobs-row" data-status={r.job.status}>
                <div className="jobs-row-line">
                  <span className="jobs-row-label">{r.label}</span>
                  <span className="jobs-row-status">{r.status}</span>
                </div>
                {r.job.message && <div className="jobs-row-msg">{r.job.message}</div>}
                {r.progress !== null && <Progress className="jobs-row-bar" value={r.progress} />}
              </li>
            ))}
          </ul>
        </div>
      )}
      <button
        ref={button}
        type="button"
        className="jobs-bar"
        aria-expanded={shown}
        aria-controls={shown ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        <Progress value={current.status === "queued" || current.progress === 0 ? undefined : current.progress} />
        <span className="jobs-label" role="status" aria-live="polite">
          {label}
          {current.message ? `：${current.message}` : ""}
        </span>
        <span className="jobs-count">
          {running.length} 个进行中，{active.length - running.length} 个排队
        </span>
      </button>
    </div>
  );
}
