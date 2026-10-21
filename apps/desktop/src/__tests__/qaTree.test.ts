import { describe, expect, it } from "vitest";
import { buildTree, latestLeaf, layoutTree, pathTo, siblings } from "../features/qa/tree";
import { anchorRanges } from "../features/qa/anchors";

const n = (id: string, parent_id: string | null = null) => ({ id, parent_id });

//      r1            r2
//    a    b
//   a1    (b 是叶子)
const nodes = [n("r1"), n("a", "r1"), n("b", "r1"), n("a1", "a"), n("r2"), n("orphan", "gone")];

describe("qa tree", () => {
  const tree = buildTree(nodes);

  it("builds children, roots and treats orphans as roots", () => {
    expect(tree.roots.map((x) => x.id)).toEqual(["r1", "r2", "orphan"]);
    expect(tree.children.get("r1")?.map((x) => x.id)).toEqual(["a", "b"]);
  });

  it("paths, siblings and latest leaf", () => {
    expect(pathTo(tree, "a1").map((x) => x.id)).toEqual(["r1", "a", "a1"]);
    expect(pathTo(tree, null)).toEqual([]);
    expect(siblings(tree, "b").map((x) => x.id)).toEqual(["a", "b"]);
    expect(siblings(tree, "r2").map((x) => x.id)).toEqual(["r1", "r2", "orphan"]);
    expect(latestLeaf(tree, "r1")).toBe("b");
    expect(latestLeaf(tree, "a")).toBe("a1");
  });

  it("lays out leaves in columns with parents centred and no overlaps", () => {
    const { pos, cols, rows } = layoutTree(tree);
    expect(cols).toBe(4);
    expect(rows).toBe(3);
    expect(pos.get("a1")).toEqual({ x: 0, y: 2 });
    expect(pos.get("a")).toEqual({ x: 0, y: 1 });
    expect(pos.get("b")).toEqual({ x: 1, y: 1 });
    expect(pos.get("r1")).toEqual({ x: 0.5, y: 0 });
    const seen = new Set([...pos.values()].map((p) => `${p.x},${p.y}`));
    expect(seen.size).toBe(pos.size);
  });

  it("finds anchors in the answer ignoring citation markers and whitespace", () => {
    const answer = "根据原文，第一点见此处[b_0001]。另外\n还有一点[b_0002]。";
    const ranges = anchorRanges(answer, [
      { id: "c1", text: "第一点见此处。另外 还有" },
      { id: "c2", text: "不存在" },
    ]);
    expect(ranges).toEqual([{ id: "c1", start: 5, end: 25 }]);
    expect(answer.slice(5, 25)).toBe("第一点见此处[b_0001]。另外\n还有");
  });
});
