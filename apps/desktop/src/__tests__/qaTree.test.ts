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

  const gap = { x: 20, y: 30 };
  const overlaps = (pos: Map<string, { x: number; y: number; w: number; h: number }>) => {
    const ps = [...pos.values()];
    return ps.some((p, i) =>
      ps.some((q, j) => i < j && p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h),
    );
  };

  it("lays out equal cards with parents centred over their subtree", () => {
    const { pos, width, height } = layoutTree(tree, () => ({ w: 100, h: 40 }), gap);
    expect(pos.get("r1")).toMatchObject({ x: 60, y: 0 });
    expect(pos.get("a")).toMatchObject({ x: 0, y: 70 });
    expect(pos.get("b")).toMatchObject({ x: 120, y: 70 });
    expect(pos.get("a1")).toMatchObject({ x: 0, y: 140 });
    expect(pos.get("r2")).toMatchObject({ x: 240, y: 0 });
    expect(width).toBe(460);
    expect(height).toBe(180);
    expect(overlaps(pos)).toBe(false);
  });

  it("makes room for the expanded card: wider subtree, taller row", () => {
    const size = (id: string) => (id === "a" ? { w: 300, h: 200 } : { w: 100, h: 40 });
    const { pos } = layoutTree(tree, size, gap);
    expect(pos.get("a")).toMatchObject({ x: 0, y: 70, w: 300, h: 200 });
    expect(pos.get("a1")).toMatchObject({ x: 100, y: 300 });
    expect(pos.get("b")).toMatchObject({ x: 320 });
    expect(pos.get("r1")).toMatchObject({ x: 160 });
    expect(overlaps(pos)).toBe(false);
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
