// 引用编号小标：悬停浮出原文片段，点击跳回原文。问答回答、总结要点、图谱出处共用。
// 小标样式是 reader.css 的 .cite；悬浮卡用 AI Elements 的 InlineCitationCard。

import { InlineCitationCard, InlineCitationCardBody, InlineCitationQuote } from "./ai-elements/inline-citation";
import { HoverCardTrigger } from "./ui/hover-card";

interface Props {
  id: string;
  /** 显示的编号 */
  n: number;
  active?: boolean;
  /** 引用块的原文；取不到时只显示编号，不出悬浮卡 */
  blockText?: (id: string) => string | undefined;
  onPick: (id: string) => void;
}

export function Citation({ id, n, active, blockText, onPick }: Props) {
  const text = blockText?.(id)?.trim();
  const button = (
    <button type="button" className={`cite${active ? " active" : ""}`} onClick={() => onPick(id)}>
      {n}
    </button>
  );
  if (!text) return button;
  return (
    <InlineCitationCard>
      <HoverCardTrigger asChild>{button}</HoverCardTrigger>
      <InlineCitationCardBody side="top" className="max-h-60 overflow-y-auto">
        <InlineCitationQuote>{text.length > 400 ? `${text.slice(0, 399)}…` : text}</InlineCitationQuote>
      </InlineCitationCardBody>
    </InlineCitationCard>
  );
}
