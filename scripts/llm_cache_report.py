"""大模型调用的缓存命中报告：本地 llm_cache 命中率与服务商前缀缓存（prompt cache）命中率。

用法（在 core/ 下）：
    .venv/Scripts/python ../scripts/llm_cache_report.py                 # 应用数据目录里的库，全部调用
    .venv/Scripts/python ../scripts/llm_cache_report.py --since 2026-11-10 --doc d_0123456789abcdef
    .venv/Scripts/python ../scripts/llm_cache_report.py --db path/to/freeread.db

两种命中率：
- 本地命中：整条请求与以前完全相同，直接从 llm_cache 返回，不调用服务商（llm_calls.cache_hit）；
- 前缀命中：请求发给了服务商，输入 token 中有多少命中了服务商的前缀缓存
  （cached_input_tokens / input_tokens，只统计真正发出的请求）。服务商不报告缓存 token 时为 0。
改提示词结构前后各跑一次，用 --since 截取各自的时间段对比。
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from freeread.config import DataPaths, default_data_dir

QUERY = """
SELECT task_kind,
       COALESCE(prompt_id, '') AS prompt_id,
       COUNT(*) AS calls,
       SUM(cache_hit) AS local_hits,
       SUM(input_tokens) AS input_tokens,
       SUM(cached_input_tokens) AS cached_tokens,
       SUM(output_tokens) AS output_tokens
FROM llm_calls
WHERE task_kind != 'embed' {filters}
GROUP BY task_kind, prompt_id
ORDER BY task_kind, prompt_id
"""


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "    –"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--db", type=Path, default=DataPaths(default_data_dir()).db)
    parser.add_argument("--since", help="只统计这个时间（UTC，ISO 格式，如 2026-11-10）之后的调用")
    parser.add_argument("--doc", help="只统计这个 doc_id")
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"找不到数据库：{args.db}", file=sys.stderr)
        return 1

    filters, params = "", []
    if args.since:
        filters += " AND created_at >= ?"
        params.append(args.since)
    if args.doc:
        filters += " AND doc_id = ?"
        params.append(args.doc)
    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(QUERY.format(filters=filters), params).fetchall()
    except sqlite3.OperationalError as e:
        print(f"读取失败（数据库需要先由新版本的应用打开一次以完成迁移）：{e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    if not rows:
        print("没有符合条件的调用记录")
        return 0

    header = (
        f"{'任务':<12}{'提示词':<22}{'调用':>6}{'本地命中':>10}"
        f"{'输入 token':>12}{'前缀命中':>10}{'输出 token':>12}"
    )
    print(header)
    print("-" * 86)
    total = [0, 0, 0, 0, 0]
    for task, prompt_id, calls, local, inp, cached, out in rows:
        values = [calls, local or 0, inp or 0, cached or 0, out or 0]
        total = [a + b for a, b in zip(total, values, strict=True)]
        calls, local, inp, cached, out = values
        print(
            f"{task:<14}{prompt_id:<25}{calls:>6}{pct(local, calls):>12}"
            f"{inp:>14}{pct(cached, inp):>12}{out:>14}"
        )
    calls, local, inp, cached, out = total
    print("-" * 86)
    print(
        f"{'合计':<12}{'':<25}{calls:>6}{pct(local, calls):>12}"
        f"{inp:>14}{pct(cached, inp):>12}{out:>14}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
