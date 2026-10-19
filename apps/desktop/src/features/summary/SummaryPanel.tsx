import { useEffect, useState } from "react";
import { Button, IconButton, Progress, Select } from "../../components/ui";
import type { useSummary } from "./useSummary";

interface Props {
  state: ReturnType<typeof useSummary>;
  /** 引用块的原文（悬停提示用） */
  blockText: (id: string) => string | undefined;
  onPick: (blockId: string) => void;
  onClose: () => void;
}

const fmtTime = (iso: string) => new Date(iso).toLocaleString();

export function SummaryPanel({ state, blockText, onPick, onClose }: Props) {
  const { templates, summaries, progress, running, error, generate, cancel } = state;
  const [templateId, setTemplateId] = useState("paper");
  const [active, setActive] = useState<string | null>(null);

  // 默认显示最近生成的那份总结的模板
  useEffect(() => {
    if (summaries[0] && !summaries.some((s) => s.template_id === templateId)) setTemplateId(summaries[0].template_id);
    // 只在列表首次加载时跟随
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summaries.length]);

  const summary = summaries.find((s) => s.template_id === templateId);
  const coverage = summary?.stats.coverage as number | null | undefined;

  const pick = (id: string) => {
    setActive(id);
    onPick(id);
  };

  return (
    <aside className="side-panel summary-panel" aria-label="总结">
      <div className="side-panel-head">
        <h2 className="serif">总结</h2>
        <IconButton icon="close" label="关闭总结" onClick={onClose} />
      </div>
      <div className="summary-controls">
        <Select
          label="模板"
          value={templateId}
          options={(templates.length ? templates : [{ id: "paper", name: "论文精读" }]).map((t) => ({
            value: t.id,
            label: t.name,
          }))}
          onValue={setTemplateId}
        />
        {running ? (
          <Button small onClick={cancel}>
            停止
          </Button>
        ) : (
          <Button small icon="sync" onClick={() => void generate(templateId)}>
            {summary ? "重新生成" : "生成"}
          </Button>
        )}
      </div>

      {running && (
        <div className="summary-progress">
          <Progress
            value={!progress || progress.stage === "reduce" ? undefined : progress.total ? progress.done / progress.total : 0}
          />
          <span>
            {!progress
              ? "准备中…"
              : progress.stage === "map"
                ? `正在读各章节（${progress.done} / ${progress.total}）${progress.title ? `：${progress.title}` : ""}`
                : "正在汇总…"}
          </span>
        </div>
      )}
      {error && <p className="search-note error">{error}</p>}
      {summary?.status === "stale" && (
        <p className="search-note">原文已重新解析，部分引用已失效，可以重新生成。</p>
      )}
      {!summary && !running && !error && (
        <p className="search-note">
          按{templates.find((t) => t.id === templateId)?.description ?? "模板"}整理全文要点，每条都能点回原文。
          生成会把论文正文发送给总结所用的大模型服务（默认与翻译相同）。
        </p>
      )}

      {summary && (
        <div className="summary-body">
          {summary.sections.map((sec) => (
            <section key={sec.key}>
              <h3>{sec.name}</h3>
              {sec.points.length ? (
                <ul>
                  {sec.points.map((p, i) => (
                    <li key={i} className={p.untraced ? "untraced" : undefined}>
                      {p.text}
                      {p.block_ids.map((id, j) => (
                        <button
                          type="button"
                          key={id}
                          className={`cite${id === active ? " active" : ""}`}
                          title={blockText(id)?.slice(0, 200)}
                          onClick={() => pick(id)}
                        >
                          {j + 1}
                        </button>
                      ))}
                      {p.untraced && <span className="untraced-tag">未溯源</span>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="search-note">论文未涉及</p>
              )}
            </section>
          ))}
        </div>
      )}
      {summary && (
        <div className="panel-foot">
          <span>{summary.model}</span>
          <span aria-hidden="true">·</span>
          <span>{fmtTime(summary.created_at)}</span>
          {coverage != null && (
            <>
              <span aria-hidden="true">·</span>
              <span>引用覆盖率 {Math.round(coverage * 100)}%</span>
            </>
          )}
        </div>
      )}
    </aside>
  );
}
