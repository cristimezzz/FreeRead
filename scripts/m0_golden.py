"""M0：自动生成解析评测 golden（无人工标注）。

子命令：
  sample     为每篇文档选 3 个抽样页 → core/tests/fixtures/pdfs/golden_pages.yaml（入库）
  consensus  在抽样页上对 MinerU / Docling / Marker 的块做 IoU 聚类与多数投票 → golden/draft/<doc_id>.json
  render     把 draft 渲染成带编号框的 PNG，供 Claude 逐页复核 → golden/review/<doc_id>_p<page>.png
  merge      合并 golden/corrections/<doc_id>.yaml → golden/<doc_id>.json（最终 golden）

golden 文本取自 PDF 文本层（PyMuPDF 按 bbox 截取），与任何引擎无关；扫描页无文本层时取共识引擎文本的
medoid。LaTeX 取各引擎结果中编辑距离和最小者（medoid）。每块记录来源 consensus / claude_review。
"""

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path

import pymupdf
import yaml

from freeread.eval.metrics import PB, blocks_from_ir, iou, ned, normalize_latex, normalize_text

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "core" / "tests" / "fixtures" / "pdfs"
GOLD = ROOT / "core" / "tests" / "golden"
OUT = ROOT / "eval-out"
# Marker 已从候选中移除（4GB 显存下过慢，见 docs/m0/parser-eval.md），不参与共识
CONSENSUS_ENGINES = ("mineru", "docling")
REF_HEAD_RE = re.compile(
    r"^\s*(references?|bibliography|参考文献)\s*$", re.IGNORECASE | re.MULTILINE
)


def load_manifest() -> list[dict]:
    return yaml.safe_load((FIX / "manifest.yaml").read_text(encoding="utf-8"))["documents"]


def pdf_path(doc_id: str) -> Path:
    return FIX / "files" / f"{doc_id}.pdf"


# ---------------------------------------------------------------- sample


def sample_pages(pdf: Path) -> list[int]:
    doc = pymupdf.open(pdf)
    n = doc.page_count
    if n <= 3:
        return list(range(n))
    picks = [0, n // 2]
    best, best_score = None, 0.0
    for i in range(1, n):
        if i in picks:
            continue
        page = doc[i]
        try:
            tables = len(page.find_tables().tables)
        except Exception:  # noqa: BLE001
            tables = 0
        text = page.get_text()
        score = (
            tables * 2
            + (1.5 if REF_HEAD_RE.search(text) else 0)
            + (0.5 if len(page.get_images()) else 0)
        )
        if score > best_score:
            best, best_score = i, score
    if best is None:
        best = 1 if n // 2 != 1 else n - 1
    picks.append(best)
    return sorted(set(picks))


def cmd_sample(_a) -> None:
    out = {d["doc_id"]: sample_pages(pdf_path(d["doc_id"])) for d in load_manifest()}
    (FIX / "golden_pages.yaml").write_text(
        "# 每篇文档参与 golden 评测的页（从 0 开始），由 scripts/m0_golden.py sample 生成\n"
        + yaml.safe_dump(out, sort_keys=False),
        encoding="utf-8",
    )
    print(f"{len(out)} docs, {sum(len(v) for v in out.values())} pages")


def load_pages() -> dict[str, list[int]]:
    return yaml.safe_load((FIX / "golden_pages.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- consensus


def load_engine_blocks(engine: str, doc_id: str) -> list[PB] | None:
    f = OUT / engine / doc_id / "ir.json"
    if not f.exists():
        return None
    return blocks_from_ir(json.loads(f.read_text(encoding="utf-8")))


def text_in_bbox(page: pymupdf.Page, bbox) -> str:
    words = page.get_text("words", clip=pymupdf.Rect(*bbox))
    # 只保留中心落在 bbox 内的词，按行排序
    x0, y0, x1, y1 = bbox
    keep = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    keep.sort(key=lambda w: (w[5], w[6], w[7]))
    return " ".join(w[4] for w in keep)


def medoid(strs: list[str], norm=lambda s: s) -> str:
    strs = [s for s in strs if s]
    if not strs:
        return ""
    if len(strs) <= 2:
        return max(strs, key=len)
    best = min(strs, key=lambda s: sum(ned(norm(s), norm(o)) for o in strs))
    return best


def consensus_page(engine_blocks: dict[str, list[PB]], page: int, thr: float = 0.5) -> list[dict]:
    """把多个引擎同页的块聚类：贪心地把每个块并入 IoU 最高的现有簇（每簇每引擎至多一块）。"""
    clusters: list[dict] = []
    for engine, blocks in engine_blocks.items():
        for b in (x for x in blocks if x.page == page):
            best, best_v = None, thr
            for c in clusters:
                if engine in c["members"]:
                    continue
                v = iou(c["bbox"], b.bbox)
                if v >= best_v:
                    best, best_v = c, v
            if best is None:
                clusters.append({"bbox": b.bbox, "members": {engine: b}})
            else:
                best["members"][engine] = b
                boxes = [m.bbox for m in best["members"].values()]
                best["bbox"] = tuple(statistics.median(bx[k] for bx in boxes) for k in range(4))
    out = []
    n_eng = len(engine_blocks)
    for c in clusters:
        votes = Counter(m.type for m in c["members"].values())
        typ, cnt = votes.most_common(1)[0]
        support = len(c["members"])
        agree = cnt >= 2 or n_eng == 1
        out.append(
            {
                "bbox": [round(v, 2) for v in c["bbox"]],
                "type": typ,
                "support": support,
                "type_votes": dict(votes),
                "agreed": bool(agree and support >= 2),
                "members": {
                    e: {"id": m.id, "type": m.type, "order": m.order}
                    for e, m in c["members"].items()
                },
                "_texts": [m.text for m in c["members"].values()],
                "_latex": [m.latex for m in c["members"].values() if m.latex],
                "_orders": {e: m.order for e, m in c["members"].items()},
            }
        )
    return out


def order_clusters(clusters: list[dict], engine_blocks: dict[str, list[PB]]) -> str:
    """阅读顺序初值：选与其他引擎排序最一致的引擎（两两 Kendall τ 之和最大），按其顺序排列；
    该引擎缺失的簇按中心位置插入。返回所选引擎名。"""
    from freeread.eval.metrics import kendall_tau

    engines = [e for e in engine_blocks]
    best_e, best_score = engines[0], float("-inf")
    for e in engines:
        score = 0.0
        for o in engines:
            if o == e:
                continue
            both = [c for c in clusters if e in c["_orders"] and o in c["_orders"]]
            both.sort(key=lambda c: c["_orders"][e])
            tau, n = kendall_tau([c["_orders"][o] for c in both])
            score += tau * n
        if score > best_score:
            best_e, best_score = e, score
    have = sorted(
        (c for c in clusters if best_e in c["_orders"]), key=lambda c: c["_orders"][best_e]
    )
    missing = [c for c in clusters if best_e not in c["_orders"]]
    for c in missing:
        # 插到 y 方向上最近的已排序簇之后（同栏优先）
        cx = (c["bbox"][0] + c["bbox"][2]) / 2
        pos = len(have)
        for i, h in enumerate(have):
            hx = (h["bbox"][0] + h["bbox"][2]) / 2
            same_col = abs(hx - cx) < 150
            if same_col and h["bbox"][1] > c["bbox"][1]:
                pos = i
                break
        have.insert(pos, c)
    for i, c in enumerate(have):
        c["order"] = i
    clusters[:] = have
    return best_e


def cmd_consensus(a) -> None:
    pages = load_pages()
    draft_dir = GOLD / "draft"
    draft_dir.mkdir(parents=True, exist_ok=True)
    for d in load_manifest():
        doc_id = d["doc_id"]
        if a.docs and doc_id not in a.docs.split(","):
            continue
        eb = {
            e: blk for e in CONSENSUS_ENGINES if (blk := load_engine_blocks(e, doc_id)) is not None
        }
        if len(eb) < 2:
            print(f"skip {doc_id}: only {list(eb)}")
            continue
        pdf = pymupdf.open(pdf_path(doc_id))
        scanned = "scanned" in d["tags"]
        out_pages = []
        for pg in pages[doc_id]:
            clusters = consensus_page(eb, pg)
            # 只保留至少两个引擎支持的簇；单引擎簇作为"候选"留给复核
            ref_engine = order_clusters(clusters, eb)
            blocks = []
            for c in clusters:
                bbox = c["bbox"]
                text = "" if scanned else text_in_bbox(pdf[pg], bbox)
                if not text:
                    text = medoid(c["_texts"], normalize_text)
                latex = medoid(c["_latex"], normalize_latex) or None
                blocks.append(
                    {
                        "order": c["order"],
                        "type": c["type"],
                        "bbox": bbox,
                        "text": text if c["type"] not in ("figure", "equation") else "",
                        "latex": latex if c["type"] == "equation" else None,
                        "support": c["support"],
                        "agreed": c["agreed"],
                        "type_votes": c["type_votes"],
                        "members": c["members"],
                        "source": "consensus" if c["agreed"] else "candidate",
                    }
                )
            out_pages.append(
                {
                    "page": pg,
                    "width": pdf[pg].rect.width,
                    "height": pdf[pg].rect.height,
                    "order_engine": ref_engine,
                    "blocks": blocks,
                }
            )
        draft = {"doc_id": doc_id, "engines": list(eb), "pages": out_pages}
        (draft_dir / f"{doc_id}.json").write_text(
            json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        n = sum(len(p["blocks"]) for p in out_pages)
        dis = sum(1 for p in out_pages for b in p["blocks"] if not b["agreed"])
        print(f"{doc_id}: {n} blocks, {dis} need review, engines={list(eb)}")


# ---------------------------------------------------------------- render

COLORS = {
    "title": (0.8, 0.0, 0.0),
    "heading": (0.9, 0.3, 0.0),
    "paragraph": (0.0, 0.4, 0.9),
    "abstract": (0.0, 0.6, 0.6),
    "list_item": (0.3, 0.3, 0.9),
    "caption": (0.6, 0.0, 0.8),
    "equation": (0.0, 0.6, 0.0),
    "figure": (0.5, 0.5, 0.0),
    "table": (0.0, 0.5, 0.3),
    "footnote": (0.5, 0.5, 0.5),
    "reference_entry": (0.6, 0.3, 0.1),
    "code": (0.2, 0.2, 0.2),
    "other": (0.7, 0.7, 0.7),
}


def cmd_render(a) -> None:
    rev = GOLD / "review"
    rev.mkdir(parents=True, exist_ok=True)
    for f in sorted((GOLD / "draft").glob("*.json")):
        draft = json.loads(f.read_text(encoding="utf-8"))
        doc_id = draft["doc_id"]
        if a.docs and doc_id not in a.docs.split(","):
            continue
        pdf = pymupdf.open(pdf_path(doc_id))
        for p in draft["pages"]:
            page = pdf[p["page"]]
            shape = page.new_shape()
            for b in p["blocks"]:
                r = pymupdf.Rect(*b["bbox"])
                col = COLORS.get(b["type"], (0, 0, 0))
                shape.draw_rect(r)
                shape.finish(
                    color=col,
                    width=1.6 if b["agreed"] else 0.8,
                    dashes=None if b["agreed"] else "[3] 0",
                )
                tag = f"{b['order']}{b['type'][:3]}{'' if b['agreed'] else '?'}"
                page.insert_text((r.x0 + 1, r.y0 + 7), tag, fontsize=7, color=col)
            shape.commit()
            pix = page.get_pixmap(dpi=a.dpi)
            pix.save(rev / f"{doc_id}_p{p['page']}.png")
        print(doc_id)


# ---------------------------------------------------------------- merge


def apply_corrections(draft: dict, corr: dict) -> dict:
    """corrections YAML 格式（按页）：
    pages:
      3:
        drop: [5, 9]                 # 删除的簇（按 draft order）
        type: {4: heading, 7: caption}
        latex: {12: "a+b"}
        order: [0, 1, 3, 2, ...]     # 可选：按 draft order 给出新的完整顺序（不含 drop）
        add: [{type: paragraph, bbox: [x0,y0,x1,y1], after: 6}]
        exclude: true                # 该页不进入 golden（无法可靠标注）
    """
    pages_corr = {int(k): v for k, v in (corr.get("pages") or {}).items()}
    out_pages = []
    for p in draft["pages"]:
        c = pages_corr.get(p["page"], {})
        if c.get("exclude"):
            continue  # 页面无法可靠标注（如文本层与渲染错位），不进入 golden
        by_order = {b["order"]: dict(b) for b in p["blocks"]}
        # 规则 1（GUIDELINES.md）：一方判为参考文献、另一方判为列表项的块统一为 reference_entry
        for b in by_order.values():
            if set(b.get("type_votes", {})) == {"list_item", "reference_entry"}:
                b["type"] = "reference_entry"
                b["source"] = "rule"
        for i in c.get("drop", []):
            by_order.pop(i, None)
        for i, t in (c.get("type") or {}).items():
            if int(i) in by_order:
                by_order[int(i)]["type"] = t
                by_order[int(i)]["source"] = "claude_review"
        for i, lx in (c.get("latex") or {}).items():
            if int(i) in by_order:
                by_order[int(i)]["latex"] = lx
                by_order[int(i)]["source"] = "claude_review"
        reviewed = p["page"] in pages_corr
        for b in by_order.values():
            if b["source"] == "candidate" and reviewed:
                b["source"] = "claude_review"  # 复核后保留的候选簇
        seq = (
            [by_order[i] for i in c["order"] if i in by_order]
            if c.get("order")
            else sorted(by_order.values(), key=lambda b: b["order"])
        )
        for add in c.get("add") or []:
            nb = {
                "type": add["type"],
                "bbox": add["bbox"],
                "text": add.get("text", ""),
                "latex": add.get("latex"),
                "source": "claude_review",
            }
            if "before" in add:
                idx = next(
                    (k for k, b in enumerate(seq) if b.get("order") == add["before"]), len(seq)
                )
            else:
                idx = next(
                    (k + 1 for k, b in enumerate(seq) if b.get("order") == add.get("after")),
                    len(seq),
                )
            seq.insert(idx, nb)
        blocks = []
        for k, b in enumerate(seq):
            blocks.append(
                {
                    "order": k,
                    "type": b["type"],
                    "bbox": b["bbox"],
                    "text": b.get("text", ""),
                    "latex": b.get("latex"),
                    "source": b["source"]
                    if reviewed or b["source"] != "candidate"
                    else "candidate",
                }
            )
        out_pages.append(
            {
                "page": p["page"],
                "width": p["width"],
                "height": p["height"],
                "reviewed": reviewed,
                "blocks": blocks,
            }
        )
    return {"doc_id": draft["doc_id"], "golden_version": 1, "pages": out_pages}


def cmd_merge(a) -> None:
    for f in sorted((GOLD / "draft").glob("*.json")):
        draft = json.loads(f.read_text(encoding="utf-8"))
        cf = GOLD / "corrections" / f"{draft['doc_id']}.yaml"
        corr = yaml.safe_load(cf.read_text(encoding="utf-8")) if cf.exists() else {}
        g = apply_corrections(draft, corr or {})
        pdf = pymupdf.open(pdf_path(draft["doc_id"]))
        # 未复核页上的候选簇（仅一个引擎支持）不进入 golden
        for p in g["pages"]:
            for b in p["blocks"]:
                if not b["text"] and b["type"] not in ("figure", "equation", "table"):
                    b["text"] = text_in_bbox(pdf[p["page"]], b["bbox"])
            if not p["reviewed"]:
                p["blocks"] = [b for b in p["blocks"] if b["source"] != "candidate"]
                for k, b in enumerate(p["blocks"]):
                    b["order"] = k
        (GOLD / f"{draft['doc_id']}.json").write_text(
            json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        src = Counter(b["source"] for p in g["pages"] for b in p["blocks"])
        print(draft["doc_id"], dict(src))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    for name in ("consensus", "render", "merge"):
        sp = sub.add_parser(name)
        sp.add_argument("--docs", default="")
        if name == "render":
            sp.add_argument("--dpi", type=int, default=80)
    a = ap.parse_args()
    {"sample": cmd_sample, "consensus": cmd_consensus, "render": cmd_render, "merge": cmd_merge}[
        a.cmd
    ](a)


if __name__ == "__main__":
    main()
