import { describe, expect, it } from "vitest";
import { KG_COLORS, themeVars } from "../app/theme";
import { ENTITY_TYPES, toCloudData, type KgGraph } from "../features/kg/useKg";
import {
  DEFAULT_EDGE_LABELS,
  IMPORTANT_NODES,
  boundingSphere,
  computeLayout,
  edgeLabelSet,
  nodeRadius,
} from "../features/kg/layout";

const entity = (id: string, type: string, score: number) => ({
  id,
  type,
  name: id.toUpperCase(),
  description: "",
  aliases: [],
  block_ids: ["b_0001"],
  score,
});
const relation = (id: string, src: string, dst: string, type = "uses", extra: object = {}) => ({
  id,
  type,
  src_id: src,
  src_name: src.toUpperCase(),
  dst_id: dst,
  dst_name: dst.toUpperCase(),
  attrs: {},
  block_id: "b_0001",
  evidence: "",
  confidence: 0.9,
  status: "ok",
  ...extra,
});

const graph: Pick<KgGraph, "entities" | "relations"> = {
  entities: [entity("foo", "Model", 9), entity("imagenet", "Dataset", 3), entity("acc", "Metric", 2)],
  relations: [
    relation("r1", "foo", "imagenet", "evaluated_on"),
    relation("r2", "foo", "acc", "achieves", { attrs: { metric: "top-1", value_text: "85.3%" } }),
    relation("r3", "foo", "acc", "compares_with", { status: "stale" }),
  ],
};

describe("toCloudData", () => {
  it("maps entities and relations to nodes and directed links", () => {
    const { nodes, links } = toCloudData(graph);
    expect(nodes.map((n) => [n.id, n.type, n.val])).toEqual([
      ["foo", "Model", 10],
      ["imagenet", "Dataset", 4],
      ["acc", "Metric", 3],
    ]);
    expect(links.map((l) => [l.source, l.target, l.label])).toEqual([
      ["foo", "imagenet", "评估于"],
      ["foo", "acc", "top-1 = 85.3%"],
      ["foo", "acc", "对比"],
    ]);
    expect(links.map((l) => l.stale)).toEqual([false, false, true]);
  });

  it("merges same-type relations between the same pair, but not numeric results", () => {
    const g = {
      entities: graph.entities,
      relations: [
        relation("u1", "foo", "imagenet", "uses"),
        relation("u2", "foo", "imagenet", "uses", { block_id: "b_0002", status: "stale" }),
        relation("u3", "foo", "imagenet", "uses", { block_id: "b_0003" }),
        relation("a1", "foo", "acc", "achieves", { attrs: { metric: "top-1", value_text: "85.3%" } }),
        relation("a2", "foo", "acc", "achieves", { attrs: { metric: "top-5", value_text: "97.1%" } }),
      ],
    };
    const { links } = toCloudData(g);
    expect(links.map((l) => [l.id, l.ids, l.label, l.stale])).toEqual([
      ["u1", ["u1", "u2", "u3"], "使用 ×3", false],
      ["a1", ["a1"], "top-1 = 85.3%", false],
      ["a2", ["a2"], "top-5 = 97.1%", false],
    ]);
  });

  it("drops hidden types together with their links", () => {
    const { nodes, links } = toCloudData(graph, new Set(["Metric"]));
    expect(nodes.map((n) => n.id)).toEqual(["foo", "imagenet"]);
    expect(links.map((l) => l.id)).toEqual(["r1"]);
    expect(toCloudData(null)).toEqual({ nodes: [], links: [] });
  });

  it("has a color token for every entity type in both themes", () => {
    expect(Object.keys(KG_COLORS)).toEqual(ENTITY_TYPES.map((t) => t.value));
    expect(themeVars("#D97757", false, "standard")["--kg-model"]).toBe(KG_COLORS.Model.light);
    expect(themeVars("#D97757", true, "high")["--kg-concept"]).toBe(KG_COLORS.Concept.dark);
  });
});

describe("layout", () => {
  const nodes = [
    { id: "a", name: "A", type: "Model", val: 10 },
    { id: "b", name: "B", type: "Dataset", val: 4 },
    { id: "c", name: "C", type: "Metric", val: 3 },
    { id: "d", name: "D", type: "Task", val: 2 },
    { id: "e", name: "E", type: "Concept", val: 1 },
    { id: "f", name: "F", type: "Concept", val: 1 },
  ];
  const link = (id: string, source: string, target: string) => ({
    id,
    ids: [id],
    source,
    target,
    type: "uses",
    label: "使用",
    stale: false,
  });
  const links = [link("ab", "a", "b"), link("ac", "a", "c"), link("bc", "b", "c"), link("de", "d", "e")];

  it("is deterministic, finite and keeps linked nodes closer", () => {
    const p1 = computeLayout(nodes, links);
    const p2 = computeLayout(nodes, links);
    expect([...p1.keys()]).toEqual(nodes.map((n) => n.id));
    for (const [id, p] of p1) {
      expect(Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z)).toBe(true);
      expect(p2.get(id)).toEqual(p);
    }
    const dist = (a: string, b: string) => {
      const p = p1.get(a)!;
      const q = p1.get(b)!;
      return Math.hypot(p.x - q.x, p.y - q.y, p.z - q.z);
    };
    const linked = (dist("a", "b") + dist("a", "c") + dist("d", "e")) / 3;
    const unlinked = (dist("a", "f") + dist("b", "e") + dist("c", "f")) / 3;
    expect(linked).toBeLessThan(unlinked);
  });

  it("labels important edges by default and all edges of the focused node", () => {
    expect(edgeLabelSet(nodes, links)).toEqual(new Set(["ab", "ac", "bc", "de"]));
    expect(edgeLabelSet(nodes, links, "a")).toEqual(new Set(["ab", "ac"]));
    const many = Array.from({ length: 40 }, (_, i) => ({ id: `n${i}`, name: `N${i}`, type: "Method", val: 40 - i }));
    const dense = many.flatMap((n, i) => many.slice(i + 1).map((m) => link(`${n.id}-${m.id}`, n.id, m.id)));
    const shown = edgeLabelSet(many, dense);
    expect(shown.size).toBe(DEFAULT_EDGE_LABELS);
    expect([...shown].every((id) => id.split("-").every((n) => Number(n.slice(1)) < IMPORTANT_NODES))).toBe(true);
  });

  it("sizes nodes and frames points", () => {
    expect(nodeRadius(1)).toBe(4);
    expect(nodeRadius(1000)).toBe(14);
    const { center, radius } = boundingSphere([{ x: -10, y: 0, z: 0 }, { x: 10, y: 0, z: 0 }]);
    expect(center).toEqual({ x: 0, y: 0, z: 0 });
    expect(radius).toBe(10);
    const far = boundingSphere([...Array(9).fill({ x: 1, y: 0, z: 0 }), { x: 100, y: 0, z: 0 }], 0.9);
    expect(far.radius).toBeLessThan(20); // 离群点不撑大全貌
  });
});
