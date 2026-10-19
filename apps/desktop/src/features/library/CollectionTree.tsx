// 分类树（显示在侧栏里，样式同侧栏导航项）。后端返回扁平列表，这里按 parent_id 组装。

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
  /** 全部文献的总数；未知时不显示 */
  total?: number | null;
  onSelect: (id: string | null) => void;
}

export function CollectionTree({ collections, selected, total, onSelect }: Props) {
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
    nodes.map((n) => {
      const open = !collapsed.has(n.c.id);
      return (
        <div key={n.c.id} role="treeitem" aria-expanded={n.children.length ? open : undefined} aria-selected={selected === n.c.id}>
          <button
            type="button"
            className={`nav tree-node${selected === n.c.id ? " on" : ""}`}
            style={{ "--depth": depth } as React.CSSProperties}
            onClick={() => onSelect(n.c.id)}
          >
            {n.children.length ? (
              <span
                className="tree-toggle"
                role="button"
                aria-label={open ? "收起" : "展开"}
                onClick={(e) => {
                  e.stopPropagation();
                  toggle(n.c.id);
                }}
              >
                <Icon name={open ? "expandMore" : "chevronRight"} size={14} strokeWidth={2} />
              </span>
            ) : (
              <Icon name="folder" />
            )}
            <span className="label">{n.c.name}</span>
            {n.c.item_count > 0 && <span className="count">{n.c.item_count}</span>}
          </button>
          {n.children.length > 0 && open && <div role="group">{render(n.children, depth + 1)}</div>}
        </div>
      );
    });

  return (
    <div className="tree" role="tree" aria-label="分类">
      <div role="treeitem" aria-selected={selected === null}>
        <button type="button" className={`nav tree-node${selected === null ? " on" : ""}`} onClick={() => onSelect(null)}>
          <Icon name="all" />
          <span className="label">全部文献</span>
          {total != null && <span className="count">{total}</span>}
        </button>
      </div>
      {render(roots, 0)}
    </div>
  );
}
