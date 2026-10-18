"""测试用常驻 worker：协议同 scripts/engines/resident_worker.py。

文件名含 "bad" 的 PDF 返回错误；含 "crash" 时进程直接退出；含 "slow" 时睡 30 秒。
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts" / "engines"))

from resident_worker import serve


def analyze(pdf: Path, out: Path, options: dict) -> str:
    if "crash" in pdf.name:
        os._exit(3)
    if "bad" in pdf.name:
        raise ValueError("cannot parse")
    if "slow" in pdf.name:
        time.sleep(30)
    print("noise on stdout must not break the protocol")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps({"pid": os.getpid(), **options}))
    (out / "engine.json").write_text(json.dumps({"engine": "fake", "engine_version": "9.9"}))
    return "9.9"


if __name__ == "__main__":
    serve(analyze)
