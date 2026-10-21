// 问答树画布：整齐树布局（tree.ts），SVG 连线 + HTML 卡片；拖动平移、滚轮缩放、点卡片切换到那一支。
// 侧栏顶部是一条矮画布，展开后铺满阅读区（同一个组件，见 QaPanel）。

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { layoutTree, type Tree, type TreeItem } from "./tree";

export interface CanvasItem extends TreeItem {
  question: string;
  anchored?: boolean;
  pending?: boolean;
}

interface Props {
  tree: Tree<CanvasItem>;
  active: string | null;
  /** 当前路径上的节点（阅读区显示的那一支） */
  onPath: ReadonlySet<string>;
  onPick: (id: string) => void;
  className?: string;
}

const W = 128;
const H = 38;
const COL = W + 16;
const ROW = H + 30;
const PAD = 16;
const LABEL = 22;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const label = (q: string) => {
  const s = q.replace(/\s+/g, " ").trim();
  return s.length > LABEL ? `${s.slice(0, LABEL - 1)}…` : s;
};

export function QaCanvas({ tree, active, onPath, onPick, className }: Props) {
  const { pos, cols, rows } = useMemo(() => layoutTree(tree), [tree]);
  const view = useRef<HTMLDivElement>(null);
  const [t, setT] = useState({ x: PAD, y: PAD, k: 1 });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean; id: number } | null>(null);
  const suppressClick = useRef(false);

  const width = Math.max(1, cols) * COL - (COL - W) + PAD * 2;
  const height = Math.max(1, rows) * ROW - (ROW - H) + PAD * 2;
  const at = (id: string) => {
    const p = pos.get(id);
    return p ? { x: PAD + p.x * COL, y: PAD + p.y * ROW } : null;
  };

  // 刚出现时：整棵树放得下就居中；否则（以及之后当前节点移出视野时）把当前节点移到中间（保持缩放）
  const focusId = active && pos.has(active) ? active : null;
  const mounted = useRef(false);
  useLayoutEffect(() => {
    const el = view.current;
    if (!el) return;
    const first = !mounted.current;
    mounted.current = true;
    setT((cur) => {
      const p = focusId ? at(focusId) : null;
      const vw = el.clientWidth;
      const vh = el.clientHeight;
      if (first && width * cur.k <= vw && height * cur.k <= vh)
        return { k: cur.k, x: (vw - width * cur.k) / 2, y: Math.min((vh - height * cur.k) / 2, vh * 0.2) };
      if (!p) return { x: Math.max(PAD, (vw - width * cur.k) / 2), y: 0, k: cur.k };
      const sx = cur.x + (p.x + W / 2) * cur.k;
      const sy = cur.y + (p.y + H / 2) * cur.k;
      const margin = 24;
      if (sx > margin && sx < vw - margin && sy > margin && sy < vh - margin) return cur;
      return { k: cur.k, x: vw / 2 - (p.x + W / 2) * cur.k, y: clamp(vh / 2 - (p.y + H / 2) * cur.k, vh - height * cur.k, 0) };
    });
  }, [focusId, cols, rows]);

  // 滚轮缩放（以指针为中心）；需要非 passive 监听才能阻止页面滚动
  useEffect(() => {
    const el = view.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const cx = e.clientX - r.left;
      const cy = e.clientY - r.top;
      setT((cur) => {
        const k = clamp(cur.k * Math.exp(-e.deltaY * 0.0015), 0.4, 2);
        return { k, x: cx - ((cx - cur.x) * k) / cur.k, y: cy - ((cy - cur.y) * k) / cur.k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const edges: { id: string; d: string; on: boolean }[] = [];
  for (const n of tree.byId.values()) {
    const c = at(n.id);
    const p = n.parent_id ? at(n.parent_id) : null;
    if (!c || !p || !tree.byId.has(n.parent_id!)) continue;
    const x1 = p.x + W / 2;
    const y1 = p.y + H;
    const x2 = c.x + W / 2;
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
      className={`qa-canvas${dragging ? " dragging" : ""}${className ? ` ${className}` : ""}`}
      role="tree"
      aria-label="问答树"
      onPointerDown={(e) => {
        if (e.button !== 0) return;
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
          view.current?.setPointerCapture(d.id);
        }
        setT((cur) => ({ ...cur, x: d.tx + dx, y: d.ty + dy }));
      }}
      onPointerUp={() => {
        suppressClick.current = Boolean(drag.current?.moved);
        drag.current = null;
        setDragging(false);
      }}
      onPointerCancel={() => {
        drag.current = null;
        setDragging(false);
      }}
      onClickCapture={(e) => {
        if (suppressClick.current) {
          e.stopPropagation();
          suppressClick.current = false;
        }
      }}
    >
      <div className="qa-canvas-layer" style={{ width, height, transform: `translate(${t.x}px, ${t.y}px) scale(${t.k})` }}>
        <svg width={width} height={height} aria-hidden="true">
          {edges.map((e) => (
            <path key={e.id} d={e.d} className={e.on ? "on" : undefined} />
          ))}
        </svg>
        {[...tree.byId.values()].map((n) => {
          const p = at(n.id)!;
          const cls = [
            "qa-node",
            n.id === active && "active",
            onPath.has(n.id) && "onpath",
            n.anchored && "anchored",
            n.pending && "pending",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              key={n.id}
              type="button"
              role="treeitem"
              aria-current={n.id === active || undefined}
              className={cls}
              style={{ left: p.x, top: p.y, width: W, height: H }}
              title={n.question}
              disabled={n.pending}
              onClick={() => onPick(n.id)}
            >
              {label(n.question)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
