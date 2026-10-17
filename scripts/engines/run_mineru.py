"""在 .engines/mineru 环境中运行：直接调用 MinerU 分析门面（不经 CLI / 本地服务，因此不产生遥测）。

用法：.engines/mineru/Scripts/python scripts/engines/run_mineru.py <pdf> <out_dir> [--effort medium]
输出：out_dir/middle.json、out_dir/model.json、out_dir/engine.json
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--effort", default="medium", choices=["flash", "medium", "high", "xhigh"])
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from mineru.backend.analyze import doc_analyze
    from mineru.version import __version__

    middle, model = doc_analyze(Path(a.pdf).read_bytes(), effort=a.effort, parse_mode="auto")
    middle, model = _jsonable(middle), _jsonable(model)
    counter = [0]
    _strip_images(middle, out / "images", counter)
    _strip_images(model, None, counter)
    dump = lambda o: json.dumps(o, ensure_ascii=False, default=_default)
    (out / "middle.json").write_text(dump(middle), encoding="utf-8")
    (out / "model.json").write_text(dump(model), encoding="utf-8")
    (out / "engine.json").write_text(
        json.dumps({"engine": "mineru", "engine_version": __version__, "effort": a.effort}),
        encoding="utf-8",
    )


def _jsonable(o):
    return json.loads(json.dumps(o, ensure_ascii=False, default=_default))


def _strip_images(o, img_dir: Path | None, counter: list[int]) -> None:
    """把 image_base64 写成文件（img_dir 为 None 时直接丢弃），JSON 中只保留相对路径。"""
    import base64

    if isinstance(o, dict):
        b64 = o.get("image_base64")
        if isinstance(b64, str) and b64:
            if img_dir is not None:
                img_dir.mkdir(parents=True, exist_ok=True)
                head, _, data = b64.partition(",")
                ext = "png" if "png" in head else "jpg"
                name = f"img_{counter[0]:04d}.{ext}"
                counter[0] += 1
                (img_dir / name).write_bytes(base64.b64decode(data or head))
                o["image_path"] = f"images/{name}"
            o["image_base64"] = None
        for v in o.values():
            _strip_images(v, img_dir, counter)
    elif isinstance(o, list):
        for v in o:
            _strip_images(v, img_dir, counter)


def _default(o):
    for attr in ("model_dump", "to_dict", "dict"):
        f = getattr(o, attr, None)
        if callable(f):
            return f()
    if isinstance(o, bytes):
        return None
    if hasattr(o, "__dict__"):
        return vars(o)
    return str(o)


if __name__ == "__main__":
    sys.exit(main())
