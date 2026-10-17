"""M0：验证 Zotero 7 本地 API 能取到条目、分类和附件路径。

用法（需先启动 Zotero 7）：
    core/.venv/Scripts/python scripts/m0_zotero_check.py [--json out.json]
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from freeread.infra.zotero.local_api import LocalApiConnector


async def main(out: str | None) -> None:
    t0 = time.perf_counter()
    async with LocalApiConnector() as z:
        cols = await z.list_collections()
        items = await z.list_items()
        pdfs = [(i, a) for i in items for a in i.attachments if a.content_type == "application/pdf"]
        resolved = [(i, a, await z.resolve_attachment(i, a)) for i, a in pdfs]
    elapsed = time.perf_counter() - t0

    ok = [r for r in resolved if r[2] is not None]
    via_href = sum(1 for _, a, p in ok if a.href and a.href.startswith("file:"))
    summary = {
        "collections": len(cols),
        "items": len(items),
        "items_in_collections": sum(1 for i in items if i.collection_keys),
        "pdf_attachments": len(pdfs),
        "pdf_resolved": len(ok),
        "pdf_resolved_via_enclosure_href": via_href,
        "unresolved": [f"{i.key}/{a.key} {a.filename}" for i, a, p in resolved if p is None],
        "elapsed_s": round(elapsed, 2),
    }
    print("分类：")
    for c in cols:
        print(f"  {c.key}  {c.name}  parent={c.parent_key}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if out:
        Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    asyncio.run(main(ap.parse_args().json))
