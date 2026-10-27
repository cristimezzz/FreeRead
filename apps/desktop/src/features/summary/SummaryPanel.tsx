import { useEffect, useState } from "react";
import { IconButton, OptionSelect, ProgressBar } from "../../components/controls";
import { Icon } from "../../components/icons";
import { PanelFoot, PanelNote, SidePanel } from "../../components/SidePanel";
import { Button } from "../../components/ui/button";
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
    <SidePanel title="总结" aria-label="总结" actions={<IconButton icon="close" label="关闭总结" onClick={onClose} />}>
      <div className="flex items-end gap-2 px-6 pb-2">
        <OptionSelect
          className="flex-1"
          label="模板"
          value={templateId}
          options={(templates.length ? templates : [{ id: "paper", name: "论文精读" }]).map((t) => ({
            value: t.id,
            label: t.name,
          }))}
          onValue={setTemplateId}
        />
        {running ? (
          <Button variant="outline" size="sm" onClick={cancel}>
            停止
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={() => void generate(templateId)}>
            <Icon name="sync" />
            {summary ? "重新生成" : "生成"}
          </Button>
        )}
      </div>

      {running && (
        <div className="text-muted-foreground mx-6 mt-2 mb-1 flex flex-col gap-2 text-xs">
          <ProgressBar
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
      {error && <PanelNote error>{error}</PanelNote>}
      {summary?.status === "stale" && <PanelNote>原文已重新解析，部分引用已失效，可以重新生成。</PanelNote>}
      {!summary && !running && !error && (
        <PanelNote>
          按{templates.find((t) => t.id === templateId)?.description ?? "模板"}整理全文要点，每条都能点回原文。
          生成会把论文正文发送给总结所用的大模型服务（默认与翻译相同）。
        </PanelNote>
      )}

      {summary && (
        <div className="summary-body">
          {summary.sections.map((sec) => (
            <section key={sec.key}>
              <h3>{sec.name}</h3>
              {sec.points.length ? (
                <ul>
                  {sec.points.map((p, i) => (
                    <li
                      key={i}
                      className={p.untraced ? "untraced" : undefined}
                      style={{ "--i": Math.min(i, 8) } as React.CSSProperties}
                    >
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
                <PanelNote className="m-0 text-[13px]">论文未涉及</PanelNote>
              )}
            </section>
          ))}
        </div>
      )}
      {summary && (
        <PanelFoot>
          <span>{summary.model}</span>
          <span aria-hidden="true">·</span>
          <span>{fmtTime(summary.created_at)}</span>
          {coverage != null && (
            <>
              <span aria-hidden="true">·</span>
              <span>引用覆盖率 {Math.round(coverage * 100)}%</span>
            </>
          )}
        </PanelFoot>
      )}
    </SidePanel>
  );
}
