"""MinerU 常驻 worker，在 .engines/mineru 环境中运行。协议见 resident_worker.py。

.engines/mineru/Scripts/python scripts/engines/mineru_worker.py
"""

from resident_worker import serve
from run_mineru import analyze


def main() -> None:
    import mineru.backend.analyze  # noqa: F401  启动时先导入，减少首篇延迟

    serve(lambda pdf, out, opts: analyze(pdf, out, opts.get("effort", "medium")))


if __name__ == "__main__":
    main()
