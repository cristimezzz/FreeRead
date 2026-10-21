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

export interface LayoutPos {
  /** 列（叶子从左到右依次编号，父节点居中于首尾子节点） */
  x: number;
  /** 深度，根为 0 */
  y: number;
}

export interface TreeLayout {
  pos: Map<string, LayoutPos>;
  /** 列数（最右列 + 1）与层数 */
  cols: number;
  rows: number;
}

/** 整齐树布局（自上而下）：叶子各占一列，父节点在子节点中间；各个根依次排开。 */
export function layoutTree<T extends TreeItem>(tree: Tree<T>): TreeLayout {
  const pos = new Map<string, LayoutPos>();
  let col = 0;
  let rows = 0;
  const place = (n: T, depth: number) => {
    rows = Math.max(rows, depth + 1);
    const kids = (tree.children.get(n.id) ?? []).filter((k) => !pos.has(k.id));
    pos.set(n.id, { x: 0, y: depth }); // 先占位，防环
    if (!kids.length) {
      pos.set(n.id, { x: col++, y: depth });
      return;
    }
    for (const k of kids) place(k, depth + 1);
    const first = pos.get(kids[0].id)!.x;
    const last = pos.get(kids[kids.length - 1].id)!.x;
    pos.set(n.id, { x: (first + last) / 2, y: depth });
  };
  for (const r of tree.roots) place(r, 0);
  return { pos, cols: col, rows };
}
