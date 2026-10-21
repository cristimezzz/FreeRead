// 问答树（docs/m3/qa-tree.md）：节点按 parent_id 组成树，一个对话可以有多个根。
// 这里只有纯函数：建树、取路径 / 兄弟 / 最新叶子、整齐树布局。节点按创建时间排好序传进来。

export interface TreeItem {
  id: string;
  parent_id: string | null;
}

export interface Tree<T extends TreeItem> {
  byId: Map<string, T>;
  /** 父节点 → 子节点（创建先后）；null 键是根 */
  children: Map<string | null, T[]>;
  roots: T[];
}

export function buildTree<T extends TreeItem>(nodes: readonly T[]): Tree<T> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const children = new Map<string | null, T[]>();
  for (const n of nodes) {
    // 父节点找不到（被删或数据不完整）时当作根
    const key = n.parent_id && byId.has(n.parent_id) ? n.parent_id : null;
    const list = children.get(key);
    if (list) list.push(n);
    else children.set(key, [n]);
  }
  return { byId, children, roots: children.get(null) ?? [] };
}

export function parentOf<T extends TreeItem>(tree: Tree<T>, id: string): string | null {
  const p = tree.byId.get(id)?.parent_id ?? null;
  return p && tree.byId.has(p) ? p : null;
}

/** 从根到 id 的路径（含 id）；id 为 null 或不存在时为空。 */
export function pathTo<T extends TreeItem>(tree: Tree<T>, id: string | null): T[] {
  const out: T[] = [];
  const seen = new Set<string>();
  let cur = id ? tree.byId.get(id) : undefined;
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    out.push(cur);
    const p = parentOf(tree, cur.id);
    cur = p ? tree.byId.get(p) : undefined;
  }
  return out.reverse();
}

/** 同一父节点下的节点（含自己），按创建先后。 */
export function siblings<T extends TreeItem>(tree: Tree<T>, id: string): T[] {
  if (!tree.byId.has(id)) return [];
  return tree.children.get(parentOf(tree, id)) ?? [];
}

/** 沿最新的子节点一路走到叶子：切换到另一支时接着读它最近的内容。 */
export function latestLeaf<T extends TreeItem>(tree: Tree<T>, id: string): string {
  let cur = id;
  const seen = new Set<string>();
  for (;;) {
    seen.add(cur);
    const kids = tree.children.get(cur);
    const next = kids?.[kids.length - 1];
    if (!next || seen.has(next.id)) return cur;
    cur = next.id;
  }
}

export interface Size {
  w: number;
  h: number;
}

export interface LayoutPos extends Size {
  /** 卡片左上角（像素） */
  x: number;
  y: number;
}

export interface TreeLayout {
  pos: Map<string, LayoutPos>;
  width: number;
  height: number;
}

/**
 * 整齐树布局（自上而下，像素）：卡片大小各不相同（展开的那张更宽更高）。
 * 子树宽 = max(自身宽, 子树宽之和 + 间距)；节点居中于自己的子树，子节点在其下居中排开；
 * 每一层的高度取这一层最高的卡片，各个根依次排开。
 */
export function layoutTree<T extends TreeItem>(
  tree: Tree<T>,
  size: (id: string) => Size,
  gap: { x: number; y: number } = { x: 20, y: 36 },
): TreeLayout {
  const kids = new Map<string, T[]>();
  const span = new Map<string, number>();
  const seen = new Set<string>();
  // 先算子树宽（顺带去环）
  const measure = (n: T): number => {
    seen.add(n.id);
    const ks = (tree.children.get(n.id) ?? []).filter((k) => !seen.has(k.id));
    kids.set(n.id, ks);
    const inner = ks.reduce((sum, k) => sum + measure(k), 0) + gap.x * Math.max(0, ks.length - 1);
    const s = Math.max(size(n.id).w, inner);
    span.set(n.id, s);
    return s;
  };
  const roots = tree.roots.filter((r) => !seen.has(r.id));
  for (const r of roots) measure(r);

  const pos = new Map<string, LayoutPos>();
  const rowH: number[] = [];
  const depthOf = new Map<string, number>();
  const place = (n: T, left: number, depth: number) => {
    const s = span.get(n.id)!;
    const { w, h } = size(n.id);
    pos.set(n.id, { x: left + (s - w) / 2, y: 0, w, h });
    depthOf.set(n.id, depth);
    rowH[depth] = Math.max(rowH[depth] ?? 0, h);
    const ks = kids.get(n.id)!;
    const inner = ks.reduce((sum, k) => sum + span.get(k.id)!, 0) + gap.x * Math.max(0, ks.length - 1);
    let x = left + (s - inner) / 2;
    for (const k of ks) {
      place(k, x, depth + 1);
      x += span.get(k.id)! + gap.x;
    }
  };
  let left = 0;
  for (const r of roots) {
    place(r, left, 0);
    left += span.get(r.id)! + gap.x;
  }
  const rowY: number[] = [];
  let y = 0;
  for (let d = 0; d < rowH.length; d++) {
    rowY[d] = y;
    y += rowH[d] + gap.y;
  }
  for (const [id, p] of pos) p.y = rowY[depthOf.get(id)!];
  return { pos, width: Math.max(0, left - gap.x), height: Math.max(0, y - gap.y) };
}
