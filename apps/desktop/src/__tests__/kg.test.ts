import { describe, expect, it } from "vitest";
import { KG_COLORS, themeVars } from "../app/theme";
import { ENTITY_TYPES, toCloudData, type KgGraph } from "../features/kg/useKg";

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
