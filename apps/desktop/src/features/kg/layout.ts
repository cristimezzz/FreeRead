// 图谱云图的布局与"哪些关系要标字"（纯函数，供 KgScene 使用，可单测）。
// 布局一次算完（静态），不做持续的力导向动画：画面不抖，展开 / 收起、筛选类型时位置不变。

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  forceZ,
  type SimNode,
} from "d3-force-3d";
import type { CloudLink, CloudNode } from "./useKg";

export type Vec3 = { x: number; y: number; z: number };

const TICKS = 300;
const LINK_DISTANCE = 90;
const CHARGE = -450;
const LABEL_GAP = 12;
const GRAVITY = 0.06; // 把不相连的小块拉回中心附近，避免全貌被远处的孤点撑大

/** 节点球半径：按重要性（val = 1 + score），有上限。 */
export function nodeRadius(val: number): number {
  return Math.min(14, 4 + 2.2 * Math.sqrt(Math.max(0, val - 1)));
}

/** 字符串 → [0, 1) 的稳定哈希（FNV-1a），用来确定初始位置，同一张图每次布局相同。 */
function hash01(s: string, salt: number): number {
  let h = 0x811c9dc5 ^ salt;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 0x100000000;
}

/** 所有节点（包括被筛掉的类型）一起布局；返回 id → 位置。 */
export function computeLayout(nodes: CloudNode[], links: CloudLink[]): Map<string, Vec3> {
  type N = SimNode & { r: number };
  const sim: N[] = nodes.map((n) => {
    // 初始位置：球面上按哈希分布，半径随节点数增长
    const u = hash01(n.id, 1) * 2 - 1;
    const t = hash01(n.id, 2) * Math.PI * 2;
    const r = 40 + 8 * Math.sqrt(nodes.length);
    const s = Math.sqrt(1 - u * u);
    return { id: n.id, r: nodeRadius(n.val), x: r * s * Math.cos(t), y: r * s * Math.sin(t), z: r * u };
  });
  const ids = new Set(nodes.map((n) => n.id));
  const simLinks = links
    .filter((l) => ids.has(l.source) && ids.has(l.target))
    .map((l) => ({ source: l.source, target: l.target }));
  const simulation = forceSimulation<N>(sim, 3)
    .force(
      "link",
      forceLink<N, (typeof simLinks)[number]>(simLinks)
        .id((n) => n.id)
        .distance(LINK_DISTANCE),
    )
    .force("charge", forceManyBody().strength(CHARGE).distanceMax(600))
    .force("collide", forceCollide<N>((n) => n.r + LABEL_GAP))
    .force("center", forceCenter(0, 0, 0))
    .force("x", forceX(0).strength(GRAVITY))
    .force("y", forceY(0).strength(GRAVITY))
    .force("z", forceZ(0).strength(GRAVITY))
    .stop();
  simulation.tick(TICKS);
  return new Map(sim.map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0, z: n.z ?? 0 }]));
}

export const DEFAULT_EDGE_LABELS = 25;
export const IMPORTANT_NODES = 12;

/**
 * 哪些连线显示关系名：有焦点节点时是它的全部连线；
 * 没有焦点时是两端都在最重要的 IMPORTANT_NODES 个节点里的连线，最多 limit 条（画布小时调用方给更小的值）。
 */
export function edgeLabelSet(
  nodes: CloudNode[],
  links: CloudLink[],
  focusId: string | null = null,
  limit = DEFAULT_EDGE_LABELS,
): Set<string> {
  if (focusId) return new Set(links.filter((l) => l.source === focusId || l.target === focusId).map((l) => l.id));
  const val = new Map(nodes.map((n) => [n.id, n.val]));
  const top = new Set(
    [...nodes]
      .sort((a, b) => b.val - a.val)
      .slice(0, IMPORTANT_NODES)
      .map((n) => n.id),
  );
  return new Set(
    links
      .filter((l) => top.has(l.source) && top.has(l.target))
      .sort((a, b) => (val.get(b.source) ?? 0) + (val.get(b.target) ?? 0) - (val.get(a.source) ?? 0) - (val.get(a.target) ?? 0))
      .slice(0, limit)
      .map((l) => l.id),
  );
}

/** 画布能容下多少标签：侧栏里少一些，展开后多一些。 */
export function labelBudget(width: number, height: number): { nodes: number; edges: number } {
  const area = width * height;
  return {
    nodes: Math.round(Math.min(20, Math.max(8, area / 10000))),
    edges: Math.round(Math.min(DEFAULT_EDGE_LABELS, Math.max(6, area / 14000))),
  };
}

/** 关系类型 → 线型（与图例说明一致）。 */
export const LINE_STYLE: Record<string, "solid" | "dashed" | "dotted"> = {
  proposes: "solid",
  improves_on: "solid",
  achieves: "solid",
  uses: "dashed",
  part_of: "dashed",
  evaluated_on: "dashed",
  compares_with: "dotted",
};

/**
 * 包围球（中心与半径），用于把镜头对准全部 / 部分节点。
 * coverage < 1 时半径取到第 coverage 分位的距离：少数离群点可以在画面边缘外，大部分节点更大。
 */
export function boundingSphere(points: Vec3[], coverage = 1): { center: Vec3; radius: number } {
  if (!points.length) return { center: { x: 0, y: 0, z: 0 }, radius: 1 };
  const c = points.reduce((a, p) => ({ x: a.x + p.x, y: a.y + p.y, z: a.z + p.z }), { x: 0, y: 0, z: 0 });
  const center = { x: c.x / points.length, y: c.y / points.length, z: c.z / points.length };
  const ds = points.map((p) => Math.hypot(p.x - center.x, p.y - center.y, p.z - center.z)).sort((a, b) => a - b);
  const radius = Math.max(1, ds[Math.min(ds.length - 1, Math.ceil(coverage * ds.length) - 1)]);
  return { center, radius };
}
