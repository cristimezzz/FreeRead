"""M0：从本地 Zotero 库构建解析评测集。

通过 Zotero 本地 API 枚举 PDF，用 PyMuPDF 计算特征并打类别标签，分层抽样后写出
core/tests/fixtures/pdfs/manifest.yaml，并把 PDF 复制到 core/tests/fixtures/pdfs/files/<doc_id>.pdf
（files/ 不入库）。

用法（需先启动 Zotero 7）：
    core/.venv/Scripts/python scripts/m0_build_eval_set.py [--target 30]
"""

import argparse
import asyncio
import hashlib
import re
import shutil
import statistics
from pathlib import Path

import pymupdf as fitz
import yaml

from freeread.domain.ir.models import doc_id_from_sha256
from freeread.infra.zotero.local_api import LocalApiConnector

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "core" / "tests" / "fixtures" / "pdfs"
CJK_RE = re.compile(r"[一-鿿]")
MATH_FONT_RE = re.compile(
    r"CMMI|CMSY|CMEX|MSBM|Math|Symbol|STIX|Cambria Math|MTMI|MTSY", re.IGNORECASE
)
TRANSLATED_RE = re.compile(r"\.zh-CN\.(mono|LR_dual|dual|mono-cut|dual-cut)\.pdf$", re.IGNORECASE)

CATEGORIES = ("two_column", "formula", "table_heavy", "scanned", "chinese", "long_appendix")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def features(pdf: Path) -> dict:
    doc = fitz.open(pdf)
    n = doc.page_count
    sample = list(range(n)) if n <= 12 else sorted({0, 1, 2, *range(3, n, max(1, n // 10))})
    chars, cjk, math_spans, spans, two_col_pages, tables = [], 0, 0, 0, 0, 0
    for i in sample:
        page = doc[i]
        w = page.rect.width
        d = page.get_text("dict")
        text_chars = 0
        centers = []
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            bw = b["bbox"][2] - b["bbox"][0]
            btxt = ""
            for line in b["lines"]:
                for s in line["spans"]:
                    spans += 1
                    btxt += s["text"]
                    if MATH_FONT_RE.search(s["font"]):
                        math_spans += 1
            text_chars += len(btxt)
            cjk += len(CJK_RE.findall(btxt))
            if len(btxt) > 80 and bw < w * 0.55:
                centers.append((b["bbox"][0] + b["bbox"][2]) / 2 / w)
        chars.append(text_chars)
        left = sum(1 for c in centers if c < 0.45)
        right = sum(1 for c in centers if c > 0.55)
        if left >= 2 and right >= 2:
            two_col_pages += 1
        try:
            tables += len(page.find_tables().tables)
        except Exception:  # noqa: BLE001, S110  表格检测失败不影响其他特征
            pass
    total_chars = sum(chars) or 1
    return {
        "page_count": n,
        "chars_per_page": round(statistics.mean(chars)) if chars else 0,
        "min_chars_page": min(chars) if chars else 0,
        "cjk_ratio": round(cjk / total_chars, 3),
        "math_span_ratio": round(math_spans / max(spans, 1), 4),
        "two_column_ratio": round(two_col_pages / len(sample), 2),
        "tables_per_page": round(tables / len(sample), 2),
        "page_size": [round(doc[0].rect.width, 1), round(doc[0].rect.height, 1)],
    }


def tag(f: dict, translated: bool) -> list[str]:
    tags = []
    if f["two_column_ratio"] >= 0.5:
        tags.append("two_column")
    if f["math_span_ratio"] >= 0.02:
        tags.append("formula")
    if f["tables_per_page"] >= 0.3:
        tags.append("table_heavy")
    if f["chars_per_page"] < 200:
        tags.append("scanned")
    if translated or f["cjk_ratio"] > 0.2:
        tags.append("chinese")
    if f["page_count"] >= 25:
        tags.append("long_appendix")
    return tags


def make_synthetic_scan(src: Path, dst: Path, dpi: int = 150, max_pages: int = 8) -> None:
    """把数字 PDF 栅格化为纯图片 PDF（无文本层），模拟扫描版。"""
    s = fitz.open(src)
    out = fitz.open()
    for i in range(min(s.page_count, max_pages)):
        page = s[i]
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        np = out.new_page(width=page.rect.width, height=page.rect.height)
        np.insert_image(np.rect, pixmap=pix)
    out.save(dst, deflate=True)


async def collect() -> list[dict]:
    rows = []
    async with LocalApiConnector() as z:
        cols = {c.key: c.name for c in await z.list_collections()}
        for item in await z.list_items():
            for att in item.attachments:
                if att.content_type != "application/pdf":
                    continue
                path = await z.resolve_attachment(item, att)
                if path is None:
                    continue
                m = TRANSLATED_RE.search(path.name)
                rows.append(
                    {
                        "item": item,
                        "att": att,
                        "path": path,
                        "variant": m.group(1) if m else "original",
                        "collections": [cols.get(k, k) for k in item.collection_keys],
                    }
                )
    return rows


def display_title(r: dict) -> str:
    t = r["item"].title
    if not t or t.startswith("[No title"):
        t = Path(r["path"]).stem
    return re.sub(r"<[^>]+>", "", t)


def norm_title(r: dict) -> str:
    return re.sub(r"[^a-z0-9]", "", display_title(r).lower())[:60]


def select(rows: list[dict], target: int) -> list[dict]:
    """每个条目最多一份原文；另取少量 zh-CN.mono 译本作为中文类别。"""
    originals: dict[str, dict] = {}
    seen_sha: set[str] = set()
    for r in rows:
        if r["variant"] != "original" or r["sha"] in seen_sha:
            continue
        seen_sha.add(r["sha"])
        # 同一论文可能出现在多个条目中，按规范化标题去重
        k = norm_title(r)
        # 同一条目多个原文时取页数最多的（通常是带附录的完整版）
        if k not in originals or r["f"]["page_count"] > originals[k]["f"]["page_count"]:
            originals[k] = r
    mono = {}
    for r in rows:
        if r["variant"] == "mono" and norm_title(r) not in mono:
            mono[norm_title(r)] = r

    chosen: list[dict] = []
    pool = sorted(originals.values(), key=lambda r: r["item"].key)
    # 先保证稀缺类别
    for cat, quota in (("formula", 5), ("long_appendix", 4), ("table_heavy", 6), ("two_column", 8)):
        ranked = sorted(
            (r for r in pool if cat in r["tags"] and r not in chosen),
            key=lambda r: (
                -(
                    r["f"]["math_span_ratio"]
                    if cat == "formula"
                    else r["f"]["page_count"]
                    if cat == "long_appendix"
                    else r["f"]["tables_per_page"]
                    if cat == "table_heavy"
                    else r["f"]["two_column_ratio"]
                )
            ),
        )
        have = sum(1 for r in chosen if cat in r["tags"])
        chosen.extend(ranked[: max(0, quota - have)])
    n_cn = min(6, len(mono))
    rest = [r for r in pool if r not in chosen]
    # 按年份分散补足
    rest.sort(key=lambda r: r["item"].year or 0)
    need = max(0, target - n_cn - len(chosen))
    step = max(1, len(rest) // max(need, 1))
    chosen.extend(rest[::step][:need])
    chosen.extend(sorted(mono.values(), key=lambda r: r["item"].key)[:n_cn])
    return chosen


def main(target: int) -> None:
    rows = asyncio.run(collect())
    for r in rows:
        r["f"] = features(r["path"])
        r["tags"] = tag(r["f"], r["variant"] != "original")
        r["sha"] = sha256_file(r["path"])
    chosen = select(rows, target)

    files = FIX / "files"
    files.mkdir(parents=True, exist_ok=True)
    docs = []

    def add(r: dict, src: Path, tags: list[str], f: dict, note: str | None = None) -> None:
        sha = sha256_file(src)
        doc_id = doc_id_from_sha256(sha)
        dst = files / f"{doc_id}.pdf"
        if src != dst:
            shutil.copyfile(src, dst)
        it = r["item"]
        docs.append(
            {
                "doc_id": doc_id,
                "sha256": sha,
                "zotero_item_key": it.key,
                "zotero_attachment_key": r["att"].key,
                "variant": r["variant"] if note is None else note,
                "title": display_title(r),
                "year": it.year,
                "collections": r["collections"],
                "language": "zh" if "chinese" in tags else "en",
                "tags": tags,
                "features": f,
            }
        )

    for r in chosen:
        add(r, r["path"], r["tags"], r["f"])

    # 扫描版：库中若无，取两篇较老的原文栅格化
    if not any("scanned" in d["tags"] for d in docs):
        old = sorted(
            (r for r in chosen if r["variant"] == "original"), key=lambda r: r["item"].year or 9999
        )[:2]
        for r in old:
            tmp = files / f"_scan_{r['att'].key}.pdf"
            make_synthetic_scan(r["path"], tmp)
            sha = sha256_file(tmp)
            final = files / f"{doc_id_from_sha256(sha)}.pdf"
            tmp.replace(final)
            f = features(final)
            add(r, final, ["scanned", "synthetic_scan"], f, note="synthetic_scan")

    counts = {c: sum(1 for d in docs if c in d["tags"]) for c in CATEGORIES}
    manifest = {
        "version": 1,
        "source": "local Zotero library via Zotero 7 local API",
        "notes": "PDF 文件不入库；用 scripts/m0_build_eval_set.py 重新生成 files/。",
        "category_counts": counts,
        "documents": docs,
    }
    out = FIX / "manifest.yaml"
    out.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"{len(docs)} documents -> {out}")
    print(counts)
    for d in docs:
        print(
            f"  {d['doc_id']} p={d['features']['page_count']:>3} {','.join(d['tags']):40} {d['title'][:60]}"
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=30)
    main(ap.parse_args().target)
