// 3D 链接云图：节点是实体（颜色 = 类型，大小 = 重要性），连线是带方向的关系。
// 3d-force-graph / three 体积大，打开图谱时才懒加载。颜色读 theme.ts 写入的 --kg-* 等令牌，换主题时重新上色。

import { useEffect, useRef, useState } from "react";
import type { ForceGraph3DInstance } from "3d-force-graph";
import { exitMs } from "../../components/motion";
import type { CloudLink, CloudNode } from "./useKg";

export type Selection = { kind: "node" | "link"; id: string } | null;

interface Props {
  nodes: CloudNode[];
  links: CloudLink[];
  selected: Selection;
  onSelect: (s: Selection) => void;
}

type GNode = CloudNode & { x?: number; y?: number; z?: number };
type GLink = Omit<CloudLink, "source" | "target"> & { source: string | GNode; target: string | GNode };
type Graph = ForceGraph3DInstance<GNode, GLink>;

const LABELLED = 20;

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** 把颜色和背景按比例混合（变淡未选中的节点）；three 不认 color-mix，只能自己算。 */
function fade(hex: string, bg: string, keep: number): string {
  const rgb = (h: string) => {
    const m = /^#?([0-9a-f]{6})$/i.exec(h);
    const n = m ? parseInt(m[1], 16) : 0x888888;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const a = rgb(hex);
  const b = rgb(bg);
  return `rgb(${a.map((v, i) => Math.round(v * keep + b[i] * (1 - keep))).join(",")})`;
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function KgCloud({ nodes, links, selected, onSelect }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const spriteRef = useRef<typeof import("three-spritetext").default | null>(null);
  const cache = useRef(new Map<string, GNode>()); // 节点对象复用：切换类型筛选时位置不跳
  const fitted = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "light");

  // 换主题（data-theme 变化）时重新上色
  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(document.documentElement.dataset.theme ?? "light"));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style"] });
    return () => obs.disconnect();
  }, []);

  // 创建实例（只一次）
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    if (!webglAvailable()) {
      setError("这台设备不支持 WebGL，无法显示 3D 图谱。");
      return;
    }
    let disposed = false;
    let ro: ResizeObserver | null = null;
    void Promise.all([import("3d-force-graph"), import("three-spritetext")])
      .then(([{ default: ForceGraph3D }, { default: SpriteText }]) => {
        if (disposed) return;
        spriteRef.current = SpriteText;
        const reduced = exitMs() === 0;
        const g = new ForceGraph3D(el, { controlType: "orbit" }) as unknown as Graph;
        g.showNavInfo(false)
          .backgroundColor("rgba(0,0,0,0)")
          .width(el.clientWidth)
          .height(el.clientHeight)
          .nodeRelSize(3)
          .nodeOpacity(0.92)
          .nodeThreeObjectExtend(true)
          .linkOpacity(0.55)
          .linkDirectionalArrowLength(3)
          .linkDirectionalArrowRelPos(1)
          .linkCurvature(0.08)
          .linkLabel((l) => escapeHtml(l.label))
          .nodeLabel((n) => escapeHtml(n.name))
          .cooldownTicks(reduced ? 40 : 160)
          .onNodeClick((n) => onSelectRef.current({ kind: "node", id: n.id }))
          .onLinkClick((l) => onSelectRef.current({ kind: "link", id: l.id }))
          .onBackgroundClick(() => {
            // 取消选中时镜头退回全貌
            if (selectedRef.current) g.zoomToFit(reduced ? 0 : 600, 24);
            onSelectRef.current(null);
          })
          .onEngineStop(() => {
            if (!fitted.current && g.graphData().nodes.length) {
              fitted.current = true;
              g.zoomToFit(reduced ? 0 : 400, 24);
            }
          });
        graphRef.current = g;        ro = new ResizeObserver(() => g.width(el.clientWidth).height(el.clientHeight));
        ro.observe(el);
        setReady(true);
      })
      .catch((e) => setError(`加载 3D 图谱失败：${e instanceof Error ? e.message : e}`));
    return () => {
      disposed = true;
      ro?.disconnect();
      graphRef.current?._destructor();
      graphRef.current = null;
      el.replaceChildren();
    };
  }, []);

  // 数据
  useEffect(() => {
    const g = graphRef.current;
    if (!g || !ready) return;
    const seen = new Set<string>();
    const gNodes = nodes.map((n) => {
      seen.add(n.id);
      const prev = cache.current.get(n.id);
      const node = prev ? Object.assign(prev, n) : { ...n };
      cache.current.set(n.id, node);
      return node;
    });
    for (const id of [...cache.current.keys()]) if (!seen.has(id)) cache.current.delete(id);
    if (!gNodes.length) fitted.current = false;
    g.graphData({ nodes: gNodes, links: links.map((l) => ({ ...l })) });
    if (fitted.current || !gNodes.length) return;
    // 布局还在展开时先粗略对准一次，模拟停下后（onEngineStop）再精确对准
    const t = setTimeout(() => g.zoomToFit(0, 24), 1200);
    return () => clearTimeout(t);
  }, [nodes, links, ready]);

  // 颜色、标签与选中高亮
  useEffect(() => {
    const g = graphRef.current;
    const SpriteText = spriteRef.current;
    if (!g || !ready || !SpriteText) return;
    const bg = token("--bg") || "#FAF9F5";
    const ink = token("--ink2") || "#3D3D3A";
    const line = token("--ink3") || "#65645E";
    const accent = token("--accent") || "#D97757";
    const font = (token("--font-ui") || "system-ui, sans-serif").replace(/\s+/g, " ");
    const typeColor = (t: string) => token(`--kg-${t.toLowerCase()}`) || line;

    // 选中节点：它和一跳邻居保持原色，其余变淡；选中连线：两端点
    let focus: Set<string> | null = null;
    let focusLinks: Set<string> | null = null;
    if (selected?.kind === "node") {
      focus = new Set([selected.id]);
      focusLinks = new Set();
      for (const l of links)
        if (l.source === selected.id || l.target === selected.id) {
          focus.add(l.source);
          focus.add(l.target);
          focusLinks.add(l.id);
        }
    } else if (selected?.kind === "link") {
      const l = links.find((x) => x.id === selected.id);
      focusLinks = new Set(l ? [l.id] : []);
      focus = new Set(l ? [l.source, l.target] : []);
    }
    const lit = (id: string) => !focus || focus.has(id);
    const litLink = (id: string) => !focusLinks || focusLinks.has(id);
    // 文字标签只给最重要的 LABELLED 个和选中的部分，否则几十个标签挤成一团；其余悬停可见
    const top = new Set(
      [...nodes]
        .sort((a, b) => b.val - a.val)
        .slice(0, LABELLED)
        .map((n) => n.id),
    );

    g.nodeColor((n) => (lit(n.id) ? typeColor(n.type) : fade(typeColor(n.type), bg, 0.25)))
      .nodeThreeObject((n) => {
        const label = new SpriteText(n.name.length > 28 ? `${n.name.slice(0, 27)}…` : n.name);
        label.color = lit(n.id) ? ink : fade(ink, bg, 0.3);
        label.fontFace = font;
        label.textHeight = 5 + Math.min(4, Math.sqrt(n.val) / 2);
        label.center.y = -0.7; // 文字放在球的下方
        label.visible = focus ? focus.has(n.id) : top.has(n.id);
        return label;
      })
      .linkColor((l) => (selected && litLink(l.id) ? accent : l.stale ? fade(line, bg, 0.4) : line))
      .linkWidth((l) => (selected && litLink(l.id) ? 1.2 : 0.4))
      .linkDirectionalArrowColor((l) => (selected && litLink(l.id) ? accent : line));
  }, [selected, nodes, links, ready, theme]);

  // 选中节点时镜头飞过去
  useEffect(() => {
    const g = graphRef.current;
    if (!g || selected?.kind !== "node") return;
    const n = cache.current.get(selected.id);
    if (!n || n.x == null || n.y == null || n.z == null) return;
    const dist = 70;
    const len = Math.hypot(n.x, n.y, n.z) || 1;
    const k = 1 + dist / len;
    g.cameraPosition({ x: n.x * k, y: n.y * k, z: n.z * k }, { x: n.x, y: n.y, z: n.z }, exitMs() === 0 ? 0 : 700);
  }, [selected]);

  return (
    <div className="kg-cloud" role="img" aria-label={`知识图谱云图：${nodes.length} 个实体、${links.length} 条关系`}>
      <div className="kg-cloud-canvas" ref={box} />
      {error && <p className="search-note error kg-cloud-note">{error}</p>}
      {!ready && !error && <p className="search-note kg-cloud-note">正在加载 3D 图谱…</p>}
    </div>
  );
}
