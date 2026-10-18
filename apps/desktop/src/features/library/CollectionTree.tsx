// 分类树（M3 没有树组件，按列表项样式自己实现）。后端返回扁平列表，这里按 parent_id 组装。

import { useMemo, useState } from "react";
import type { Schemas } from "../../api/client";
import { Icon } from "../../components/icons";

type Collection = Schemas["CollectionOut"];

export interface TreeNode {
  c: Collection;
  children: TreeNode[];
}

export function buildTree(collections: Collection[]): TreeNode[] {
  const nodes = new Map(collections.map((c) => [c.id, { c, children: [] as TreeNode[] }]));
  const roots: TreeNode[] = [];
  for (const n of nodes.values()) {
    const parent = n.c.parent_id ? nodes.get(n.c.parent_id) : undefined;
    (parent ? parent.children : roots).push(n);
  }
  const sort = (list: TreeNode[]) => {
    list.sort((a, b) => a.c.name.localeCompare(b.c.name, "zh-CN"));
    list.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

interface Props {
  collections: Collection[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}

export function CollectionTree({ collections, selected, onSelect }: Props) {
  const roots = useMemo(() => buildTree(collections), [collections]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setCollapsed((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const render = (nodes: TreeNode[], depth: number) =>
    nodes.map((n) => (
      <div
        key={n.c.id}
        role="treeitem"
        aria-expanded={n.children.length ? !collapsed.has(n.c.id) : undefined}
      >
        <button
          className="tree-node"
          style={{ "--depth": depth } as React.CSSProperties}
          aria-selected={selected === n.c.id}
          onClick={() => onSelect(n.c.id)}
        >
          <span
            className="tree-toggle"
            onClick={(e) => {
              if (!n.children.length) return;
              e.stopPropagation();
              toggle(n.c.id);
            }}
          >
            {n.children.length ? (
              <Icon name={collapsed.has(n.c.id) ? "chevronRight" : "expandMore"} size={20} />
            ) : (
              <Icon name="folder" size={18} />
            )}
          </span>
          <span className="label">{n.c.name}</span>
          <span className="count">{n.c.item_count || ""}</span>
        </button>
        {n.children.length > 0 && !collapsed.has(n.c.id) && (
          <div role="group">{render(n.children, depth + 1)}</div>
        )}
      </div>
    ));

  return (
    <div className="tree" role="tree" aria-label="分类">
      <button className="tree-node" aria-selected={selected === null} onClick={() => onSelect(null)}>
        <span className="tree-toggle">
          <Icon name="library" size={18} />
        </span>
        <span className="label">全部文献</span>
      </button>
      {render(roots, 0)}
    </div>
  );
}
