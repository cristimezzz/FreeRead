"""M0：对评测集逐文档运行各解析引擎，测量耗时 / 峰值内存 / 峰值显存，并规范化为 IR。

用法：
    core/.venv/Scripts/python scripts/m0_run_parsers.py [--engines pymupdf,mineru,docling,marker]
        [--docs d_xxx,d_yyy] [--timeout 1800] [--force]

输出（eval-out/ 不入库）：
    eval-out/<engine>/<doc_id>/raw/…        引擎原生输出
    eval-out/<engine>/<doc_id>/ir.json      Document IR
    eval-out/<engine>/<doc_id>/run.json     运行指标
可断点续跑：已有 run.json 且 ok 的组合会跳过（--force 重跑）。
"""

import argparse
import json
import subprocess
import threading
import time
import traceback
from collections import Counter
from pathlib import Path

import psutil
import yaml

from freeread.infra.parsers.base import RawLayout
from freeread.infra.parsers.docling import DoclingNormalizer
from freeread.infra.parsers.marker import MarkerNormalizer
from freeread.infra.parsers.mineru import MinerUNormalizer
from freeread.infra.parsers.pymupdf_fast import PyMuPDFFastNormalizer, extract
from freeread.infra.parsers.subprocess_engine import engine_command, engine_env

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "core" / "tests" / "fixtures" / "pdfs"
OUT = ROOT / "eval-out"
NORMALIZERS = {
    "pymupdf": PyMuPDFFastNormalizer(),
    "mineru": MinerUNormalizer(),
    "docling": DoclingNormalizer(),
    "marker": MarkerNormalizer(),
}
# 4GB 显存下降低 Marker（surya）的批大小，避免显存溢出到共享内存后极慢
ENGINE_EXTRA_ENV = {
    "marker": {
        "RECOGNITION_BATCH_SIZE": "16",
        "DETECTOR_BATCH_SIZE": "4",
        "LAYOUT_BATCH_SIZE": "4",
        "TABLE_REC_BATCH_SIZE": "4",
        "OCR_ERROR_BATCH_SIZE": "4",
    }
}


class Sampler:
    """以固定间隔采样进程树 RSS 与 GPU 已用显存（设备级，减去启动前基线）。"""

    def __init__(self, pid: int, interval: float = 0.5) -> None:
        self.pid = pid
        self.interval = interval
        self.peak_rss = 0
        self.peak_vram = 0
        self._stop = threading.Event()
        self._nvml = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._h = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.vram_base = pynvml.nvmlDeviceGetMemoryInfo(self._h).used
        except Exception:  # noqa: BLE001  无 NVIDIA GPU 时不采样显存
            self.vram_base = 0
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                p = psutil.Process(self.pid)
                procs = [p, *p.children(recursive=True)]
                rss = sum(_safe_rss(x) for x in procs)
                self.peak_rss = max(self.peak_rss, rss)
            except psutil.Error:
                pass
            if self._nvml:
                used = self._nvml.nvmlDeviceGetMemoryInfo(self._h).used
                self.peak_vram = max(self.peak_vram, used - self.vram_base)
            self._stop.wait(self.interval)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join()


def _safe_rss(p: psutil.Process) -> int:
    try:
        return p.memory_info().rss
    except psutil.Error:
        return 0


def run_engine(
    engine: str, pdf: Path, raw_dir: Path, timeout: int, pages: list[int] | None = None
) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    if engine == "pymupdf":
        import pymupdf

        t0 = time.perf_counter()
        data = extract(pdf)
        wall = time.perf_counter() - t0
        (raw_dir / "pymupdf.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "wall_s": wall,
            "peak_rss_mb": psutil.Process().memory_info().rss / 2**20,
            "peak_vram_mb": 0.0,
            "engine_version": pymupdf.VersionBind,
        }
    env = engine_env() | ENGINE_EXTRA_ENV.get(engine, {})
    with open(raw_dir / "engine.log", "wb") as log:
        t0 = time.perf_counter()
        extra = ["--pages", ",".join(map(str, pages))] if pages else []
        proc = subprocess.Popen(
            engine_command(engine, pdf, raw_dir, extra),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        with Sampler(proc.pid) as s:
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                for c in psutil.Process(proc.pid).children(recursive=True):
                    c.kill()
                proc.kill()
                proc.wait()
                raise TimeoutError(f"{engine} timed out after {timeout}s") from None
        wall = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(f"{engine} exited with {rc}")
    info = json.loads((raw_dir / "engine.json").read_text(encoding="utf-8"))
    return {
        "wall_s": wall,
        "peak_rss_mb": s.peak_rss / 2**20,
        "peak_vram_mb": s.peak_vram / 2**20,
        "engine_version": info["engine_version"],
    }


def renormalize(engine: str, d: dict, out: Path, run_file: Path) -> None:
    rec = json.loads(run_file.read_text(encoding="utf-8"))
    if not rec.get("ok") and "wall_s" not in rec:
        return  # 引擎本身失败，没有 raw
    try:
        raw = RawLayout(
            engine=engine, engine_version=str(rec["engine_version"]), raw_dir=out / "raw", data=None
        )
        doc, problems = NORMALIZERS[engine].normalize(raw, d["sha256"])
        (out / "ir.json").write_text(doc.model_dump_json(indent=1), encoding="utf-8")
        rec.update(
            ok=True,
            error=None,
            n_blocks=len(doc.blocks),
            n_sections=len(doc.sections),
            n_references=len(doc.references),
            n_problems=len(problems),
            problems=problems[:50],
            type_counts=dict(Counter(b.type.value for b in doc.blocks)),
        )
    except Exception as e:  # noqa: BLE001
        rec.update(
            ok=False,
            error=f"normalize: {type(e).__name__}: {e}",
            traceback=traceback.format_exc()[-3000:],
        )
    run_file.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"[{engine}] {d['doc_id']} renormalized: {'ok' if rec['ok'] else rec['error']}", flush=True
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="pymupdf,mineru,docling")
    ap.add_argument("--docs", default="")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--renormalize", action="store_true", help="不运行引擎，只用已有 raw 重新生成 IR"
    )
    ap.add_argument(
        "--golden-pages-only",
        default="marker",
        help="只处理 golden 抽样页的引擎（逗号分隔）。Marker 在 4GB 显存上整篇运行过慢。",
    )
    a = ap.parse_args()
    golden_pages = yaml.safe_load((FIX / "golden_pages.yaml").read_text(encoding="utf-8"))
    partial = set(filter(None, a.golden_pages_only.split(",")))

    manifest = yaml.safe_load((FIX / "manifest.yaml").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    if a.docs:
        want = set(a.docs.split(","))
        docs = [d for d in docs if d["doc_id"] in want]

    for engine in a.engines.split(","):
        for d in docs:
            doc_id = d["doc_id"]
            out = OUT / engine / doc_id
            run_file = out / "run.json"
            if a.renormalize:
                if run_file.exists():
                    renormalize(engine, d, out, run_file)
                continue
            if run_file.exists() and not a.force:
                prev = json.loads(run_file.read_text(encoding="utf-8"))
                if prev.get("ok"):
                    continue
            pdf = FIX / "files" / f"{doc_id}.pdf"
            sel = golden_pages[doc_id] if engine in partial else None
            pages = len(sel) if sel else d["features"]["page_count"]
            rec = {
                "engine": engine,
                "doc_id": doc_id,
                "pages": pages,
                "page_subset": sel,
                "ok": False,
            }
            print(f"[{engine}] {doc_id} ({pages}p) …", flush=True)
            try:
                rec.update(run_engine(engine, pdf, out / "raw", a.timeout, sel))
                rec["s_per_page"] = rec["wall_s"] / pages
                raw = RawLayout(
                    engine=engine,
                    engine_version=str(rec["engine_version"]),
                    raw_dir=out / "raw",
                    data=None,
                )
                t0 = time.perf_counter()
                doc, problems = NORMALIZERS[engine].normalize(raw, d["sha256"])
                rec["normalize_s"] = time.perf_counter() - t0
                (out / "ir.json").write_text(doc.model_dump_json(indent=1), encoding="utf-8")
                rec.update(
                    ok=True,
                    n_blocks=len(doc.blocks),
                    n_sections=len(doc.sections),
                    n_references=len(doc.references),
                    n_problems=len(problems),
                    problems=problems[:50],
                    type_counts=dict(Counter(b.type.value for b in doc.blocks)),
                )
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
                rec["traceback"] = traceback.format_exc()[-3000:]
            out.mkdir(parents=True, exist_ok=True)
            run_file.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            status = "ok" if rec["ok"] else rec["error"]
            print(
                f"    {status}  wall={rec.get('wall_s', 0):.1f}s  vram={rec.get('peak_vram_mb', 0):.0f}MB",
                flush=True,
            )


if __name__ == "__main__":
    main()
