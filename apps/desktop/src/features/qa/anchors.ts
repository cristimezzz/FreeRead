// "就此追问"选中的文字在父节点回答里的位置。选区取的是去掉引用编号的纯文本，空白也可能被折叠，
// 所以在去掉 [b_xxxx] 标记的文本上按"词之间任意空白"匹配，再换算回原答案的下标。

const MARKER = /\[(b_\d+)\]/g;

export interface AnchorRange {
  id: string;
  /** 原答案（含引用标记）里的 [start, end) */
  start: number;
  end: number;
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** 每个 anchor 取第一次出现；与前面已找到的区间重叠的跳过。 */
export function anchorRanges(answer: string, anchors: { id: string; text: string }[]): AnchorRange[] {
  // 纯文本下标 → 原答案下标
  const map: number[] = [];
  let plain = "";
  let last = 0;
  const copy = (from: number, to: number) => {
    for (let i = from; i < to; i++) map.push(i);
    plain += answer.slice(from, to);
  };
  for (const m of answer.matchAll(MARKER)) {
    copy(last, m.index ?? 0);
    last = (m.index ?? 0) + m[0].length;
  }
  copy(last, answer.length);

  const out: AnchorRange[] = [];
  for (const a of anchors) {
    const words = a.text.split(/\s+/).filter(Boolean);
    if (!words.length) continue;
    const m = new RegExp(words.map(escape).join("\\s*")).exec(plain);
    if (!m || !m[0].length) continue;
    const start = map[m.index];
    const end = map[m.index + m[0].length - 1] + 1;
    if (out.some((r) => start < r.end && r.start < end)) continue;
    out.push({ id: a.id, start, end });
  }
  return out.sort((x, y) => x.start - y.start);
}
