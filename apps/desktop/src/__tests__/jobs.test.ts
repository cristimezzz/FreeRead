import { describe, expect, it } from "vitest";
import type { Job } from "../app/store";
import { jobRows } from "../features/jobs/jobList";

const job = (p: Partial<Job> & Pick<Job, "id">): Job => ({
  kind: "parse",
  payload: {},
  status: "queued",
  progress: 0,
  message: null,
  depends_on: null,
  attempts: 0,
  error: null,
  created_at: "2026-10-22T00:00:00",
  started_at: null,
  finished_at: null,
  ...p,
});

describe("jobRows", () => {
  it("puts running jobs first, then queued jobs in claim order with positions", () => {
    const rows = jobRows([
      job({ id: "q2", created_at: "2026-10-22T00:00:02" }),
      job({ id: "r1", kind: "translate_doc", status: "running", progress: 0.42 }),
      job({ id: "q1", kind: "sync", created_at: "2026-10-22T00:00:01" }),
    ]);
    expect(rows.map((r) => [r.job.id, r.label, r.status, r.progress])).toEqual([
      ["r1", "翻译全文", "42%", 0.42],
      ["q1", "同步 Zotero", "排队第 1 位", null],
      ["q2", "快速解析", "排队第 2 位", null],
    ]);
  });

  it("shows indeterminate progress before the first report and flags pending dependencies", () => {
    const rows = jobRows([
      job({ id: "a", status: "running" }),
      job({ id: "b", kind: "embed", depends_on: "a" }),
      job({ id: "c", depends_on: "gone" }),
    ]);
    expect(rows[0]).toMatchObject({ status: "进行中", progress: undefined });
    expect(rows[1].status).toBe("等待前置任务");
    expect(rows[2].status).toBe("排队第 2 位");
  });
});
