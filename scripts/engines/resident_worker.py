"""常驻解析 worker 的通用循环：模型只加载一次，按请求逐篇解析（ADR-0003 跟进：常驻 worker）。

协议（JSON Lines）：
- 启动后输出 {"event": "ready"}；
- 每行请求 {"id": str, "pdf": str, "out_dir": str, "options": {...}}；
- 每个请求的结果为 {"id", "event": "done", "engine_version"} 或 {"id", "event": "error", "message"}。
引擎和第三方库打印到 stdout 的内容会污染协议，所以协议改用复制出来的原 stdout，
sys.stdout 与文件描述符 1 都指向 stderr。
"""

import json
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

Analyze = Callable[[Path, Path, dict], str]


def serve(analyze: Analyze) -> None:
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def send(msg: dict) -> None:
        proto.write(json.dumps(msg, ensure_ascii=False) + "\n")
        proto.flush()

    send({"event": "ready"})
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        try:
            version = analyze(Path(req["pdf"]), Path(req["out_dir"]), req.get("options") or {})
        except Exception as e:  # noqa: BLE001  任何失败都要回给调用方，worker 继续服务
            traceback.print_exc()
            send({"id": req.get("id"), "event": "error", "message": f"{type(e).__name__}: {e}"})
        else:
            send({"id": req.get("id"), "event": "done", "engine_version": version})
