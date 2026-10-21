// 问答卡片画布：整齐树布局（tree.ts，卡片大小不一），SVG 连线 + HTML 卡片。
// 拖动空白处平移、在空白处滚轮缩放；展开的卡片里可以选字、滚动（按住 Ctrl 滚轮仍是缩放）。
// 展开的卡片换了一张时，把它移进视野（靠上居中）。

import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { layoutTree, type Tree, type TreeItem } from "./tree";

interface Props<T extends TreeItem> {
  tree: Tree<T>;
  /** 展开的卡片（问答全文 + 输入框），其余是标题卡片 */
  expanded: string | null;
  /** 当前一支上的卡片（连线加深） */
  onPath: ReadonlySet<string>;
  renderCard: (node: T, expanded: boolean) => ReactNode;
  /** 变化时把整棵树缩放到适合窗口 */
  fitKey: number;
  /** 平移 / 缩放开始时（收起选字浮层等） */
  onViewChange?: () => void;
}

export const CARD = { w: 184, h: 48 };
export const EXPANDED_W = 460;
const GAP = { x: 24, y: 44 };
const PAD = 48;
const TOP = 72; // 工具栏下方
const MIN_K = 0.35;
const MAX_K = 1.6;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function QaCanvas<T extends TreeItem>({ tree, expanded, onPath, renderCard, fitKey, onViewChange }: Props<T>) {
  const view = useRef<HTMLDivElement>(null);
  const expandedEl = useRef<HTMLDivElement | null>(null);
  const [expandedH, setExpandedH] = useState(320);
  const [t, setT] = useState({ x: PAD, y: TOP, k: 1 });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean; id: number } | null>(null);

  const { pos, width, height } = useMemo(
    () =>
      layoutTree(tree, (id) => (id === expanded ? { w: EXPANDED_W, h: expandedH } : CARD), GAP),
    [tree, expanded, expandedH],
  );

  // 量展开卡片的实际高度，回填给布局（流式输出时会不断长高）
  useLayoutEffect(() => {
    const el = expandedEl.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setExpandedH(Math.ceil(el.offsetHeight)));
    ro.observe(el);
    setExpandedH(Math.ceil(el.offsetHeight));
    return () => ro.disconnect();
  }, [expanded]);

  // 换了一张展开的卡片：移进视野（只在切换时，不跟随流式长高，免得和用户的平移打架）
  const focused = useRef<string | null>(null);
  useLayoutEffect(() => {
    const el = view.current;
    if (!el || !expanded || focused.current === expanded) return;
    const p = pos.get(expanded);
    if (!p) return;
    focused.current = expanded;
    // 上方留出一行，让父卡片也在视野里
    const above = p.y > 0 ? CARD.h + GAP.y : 0;
    setT((cur) => {
      const vw = el.clientWidth;
      const vh = el.clientHeight;
      const sx = cur.x + p.x * cur.k;
      const sy = cur.y + (p.y - above) * cur.k;
      const fits = sx >= 16 && sx + p.w * cur.k <= vw - 16 && sy >= TOP - 8 && sy + Math.min(p.h, vh / 2) * cur.k <= vh;
      if (fits) return cur;
      const k = Math.max(cur.k, 0.8);
      return { k, x: vw / 2 - (p.x + p.w / 2) * k, y: TOP - (p.y - above) * k };
    });
  }, [expanded, pos]);

  // 适应窗口
  useLayoutEffect(() => {
    const el = view.current;
    if (!el || !fitKey) return;
    const vw = el.clientWidth;
    const vh = el.clientHeight - TOP;
    const k = clamp(Math.min((vw - PAD * 2) / Math.max(1, width), (vh - PAD) / Math.max(1, height)), MIN_K, 1);
    setT({ k, x: (vw - width * k) / 2, y: TOP });
  }, [fitKey]);

  // 滚轮：空白处或按住 Ctrl 时缩放（以指针为中心）；展开卡片里照常滚动
  useEffect(() => {
    const el = view.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const inCard = (e.target as HTMLElement).closest(".qa-card.expanded");
      if (inCard && !e.ctrlKey) return;
      e.preventDefault();
      onViewChange?.();
      const r = el.getBoundingClientRect();
      const cx = e.clientX - r.left;
      const cy = e.clientY - r.top;
      setT((cur) => {
        const k = clamp(cur.k * Math.exp(-e.deltaY * 0.0015), MIN_K, MAX_K);
        return { k, x: cx - ((cx - cur.x) * k) / cur.k, y: cy - ((cy - cur.y) * k) / cur.k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [onViewChange]);

  const edges: { id: string; d: string; on: boolean }[] = [];
  for (const n of tree.byId.values()) {
    const c = pos.get(n.id);
    const p = n.parent_id ? pos.get(n.parent_id) : undefined;
    if (!c || !p) continue;
    const x1 = p.x + p.w / 2;
    const y1 = p.y + p.h;
    const x2 = c.x + c.w / 2;
    const y2 = c.y;
    const my = (y1 + y2) / 2;
    edges.push({
      id: n.id,
      d: `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`,
      on: onPath.has(n.id) && onPath.has(n.parent_id!),
    });
  }

  return (
    <div
      ref={view}
      className={`qa-canvas${dragging ? " dragging" : ""}`}
      onPointerDown={(e) => {
        // 只有在空白处按下才平移：卡片里要能点按钮、选文字
        if (e.button !== 0 || (e.target as HTMLElement).closest(".qa-card")) return;
        drag.current = { x: e.clientX, y: e.clientY, tx: t.x, ty: t.y, moved: false, id: e.pointerId };
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d) return;
        const dx = e.clientX - d.x;
        const dy = e.clientY - d.y;
        if (!d.moved && Math.hypot(dx, dy) < 4) return;
        if (!d.moved) {
          d.moved = true;
          setDragging(true);
          onViewChange?.();
          view.current?.setPointerCapture(d.id);
        }
        setT((cur) => ({ ...cur, x: d.tx + dx, y: d.ty + dy }));
      }}
      onPointerUp={() => {
        drag.current = null;
        setDragging(false);
      }}
      onPointerCancel={() => {
        drag.current = null;
        setDragging(false);
      }}
    >
      <div
        className="qa-canvas-layer"
        style={{ width, height, transform: `translate(${t.x}px, ${t.y}px) scale(${t.k})` }}
      >
        <svg width={Math.max(1, width)} height={Math.max(1, height)} aria-hidden="true">
          {edges.map((e) => (
            <path key={e.id} d={e.d} className={e.on ? "on" : undefined} />
          ))}
        </svg>
        {[...tree.byId.values()].map((n) => {
          const p = pos.get(n.id);
          if (!p) return null;
          const isOpen = n.id === expanded;
          return (
            <div
              key={n.id}
              ref={isOpen ? expandedEl : undefined}
              className="qa-slot"
              style={{ left: p.x, top: p.y, width: p.w, height: isOpen ? undefined : p.h }}
            >
              {renderCard(n, isOpen)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
