"""列出 golden 草稿中需要复核的块（供 Claude 对照页面图像复核）。

用法：core/.venv/Scripts/python scripts/m0_review_list.py <doc_id> [--all]
"""

import json
import sys
from pathlib import Path

GOLD = Path(__file__).resolve().parents[1] / "core" / "tests" / "golden"


def main() -> None:
    doc_id = sys.argv[1]
    show_all = "--all" in sys.argv
    d = json.loads((GOLD / "draft" / f"{doc_id}.json").read_text(encoding="utf-8"))
    for p in d["pages"]:
        print(
            f"== page {p['page']}  ({p['width']:.0f}x{p['height']:.0f}, order from {p['order_engine']})"
        )
        for b in p["blocks"]:
            if b["agreed"] and not show_all:
                continue
            votes = ",".join(f"{e[0]}:{m['type'][:4]}" for e, m in b["members"].items())
            x0, y0, x1, y1 = (round(v) for v in b["bbox"])
            flag = " " if b["agreed"] else "?"
            text = (b["text"] or b.get("latex") or "").replace("\n", " ")[:70]
            print(
                f"{flag}{b['order']:>3} {b['type'][:9]:9} [{votes:16}] ({x0},{y0},{x1},{y1}) {text}"
            )


if __name__ == "__main__":
    main()
