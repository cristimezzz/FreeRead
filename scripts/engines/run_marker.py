"""在 .engines/marker 环境中运行 Marker（不启用 LLM），输出 JSON 块树。

用法：.engines/marker/Scripts/python scripts/engines/run_marker.py <pdf> <out_dir>
输出：out_dir/marker.json（图片 base64 已剥离到 images/）、out_dir/engine.json
"""

import argparse
import base64
import importlib.metadata
import json
from pathlib import Path


def strip_images(node: dict, img_dir: Path) -> None:
    imgs = node.get("images") or {}
    saved = {}
    for name, b64 in imgs.items():
        img_dir.mkdir(parents=True, exist_ok=True)
        p = img_dir / name.replace("/", "_")
        p.write_bytes(base64.b64decode(b64))
        saved[name] = f"images/{p.name}"
    if imgs:
        node["images"] = saved
    for c in node.get("children") or []:
        strip_images(c, img_dir)


def _plain(o):
    """把 metadata 等任意对象转换为可 JSON 序列化的结构（dict 键转字符串）。"""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_plain(v) for v in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)


def _block(b) -> dict:
    return {
        "id": str(b.id),
        "block_type": str(b.block_type),
        "html": b.html,
        "polygon": b.polygon,
        "bbox": b.bbox,
        "section_hierarchy": _plain(b.section_hierarchy),
        "images": {str(k): v for k, v in b.images.items()} if b.images else None,
        "children": [_block(c) for c in b.children] if b.children else None,
    }


def page_sizes(pdf: str) -> list[list[float]]:
    import pypdfium2

    doc = pypdfium2.PdfDocument(pdf)
    try:
        return [list(doc[i].get_size()) for i in range(len(doc))]
    finally:
        doc.close()


def parse_pages(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return sorted(set(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--pages", default=None, help="页码范围（从 0 开始），如 0,5-7；默认全部")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict

    converter = PdfConverter(
        artifact_dict=create_model_dict(),
        config={
            "output_format": "json",
            **({"page_range": parse_pages(a.pages)} if a.pages else {}),
        },
        renderer="marker.renderers.json.JSONRenderer",
    )
    rendered = converter(a.pdf)
    data = {
        "children": [_block(c) for c in rendered.children],
        "metadata": _plain(rendered.metadata),
    }
    for page in data["children"]:
        strip_images(page, out / "images")
    (out / "marker.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / "engine.json").write_text(
        json.dumps(
            {
                "engine": "marker",
                "engine_version": importlib.metadata.version("marker-pdf"),
                "pages": a.pages,
                "page_sizes": page_sizes(a.pdf),
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
