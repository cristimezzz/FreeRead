"""评测脚本共用的部分（scripts/m2_summary_eval.py、scripts/m2_qa_eval.py）。

在进程内用 AppContext 跑真实服务：配置一个名为 eval 的 provider（或假模型 / 录制回放），
从评测集导入 PDF 并解析，再由各脚本调用总结 / 问答服务。
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

from freeread.context import AppContext
from freeread.infra.llm.fake import FakeProvider, RecordingProvider
from freeread.infra.llm.gateway import Message, TaskKind
from freeread.services.settings import AppSettings, ModelRoute, ProviderConfig

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "core" / "tests" / "fixtures" / "pdfs"
MISSING_PDF = "PDF 不存在（files/ 不入库，先运行 scripts/m0_build_eval_set.py）"


async def _noop(*_) -> None:
    pass


def add_common_args(ap: argparse.ArgumentParser, out: Path) -> None:
    ap.add_argument(
        "--out",
        type=Path,
        help=f"输出目录（默认 {out.relative_to(ROOT)}；--fake 时默认加 -fake 后缀，不覆盖真实结果）",
    )
    ap.add_argument("--data-dir", type=Path, help="数据目录（默认 <输出目录>/data）")
    ap.add_argument("--docs", nargs="*", help="只跑这些 doc_id（默认 manifest 全部）")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--lang", default="zh-CN")
    ap.add_argument("--engine", default="pymupdf")
    ap.add_argument("--base-url", default="http://127.0.0.1:1/v1")
    ap.add_argument("--model", default="fake")
    ap.add_argument("--api-key-env", default="FREEREAD_EVAL_API_KEY")
    ap.add_argument("--fake", action="store_true", help="确定性假模型，只验证链路")
    ap.add_argument("--record", help="把真实模型的回复录进这个 JSON 文件")
    ap.add_argument("--replay", help="从 --record 录下的文件回放，不联网")
    ap.add_argument("--jobs", type=int, default=4, help="同时处理几篇（默认 4）")
    ap.add_argument(
        "--extra-body",
        type=json.loads,
        default={},
        help='透传给服务商的请求参数（JSON），如关闭推理模型的思考：{"thinking": {"type": "disabled"}}',
    )


def resolve_dirs(args, out: Path) -> None:
    """补全 --out / --data-dir 的默认值：假模型的结果不能和真实评测写进同一个目录。"""
    if args.out is None:
        args.out = out.with_name(out.name + "-fake") if args.fake else out
    if args.data_dir is None:
        args.data_dir = args.out / "data"
    args.out.mkdir(parents=True, exist_ok=True)


def api_key(args) -> str | None:
    """返回 Key；需要却没有时打印提示并返回 None。"""
    key = os.environ.get(args.api_key_env)
    if not (args.fake or args.replay or key):
        print(
            f"缺少 API Key：设置环境变量 {args.api_key_env}，或用 --fake 只验证链路",
            file=sys.stderr,
        )
        return None
    return key or "sk-fake"


def manifest_entries(args) -> list[dict]:
    entries = yaml.safe_load((FIX / "manifest.yaml").read_text(encoding="utf-8"))["documents"]
    if args.docs:
        entries = [e for e in entries if e["doc_id"] in set(args.docs)]
    return entries[: args.limit] if args.limit else entries


def configure(
    ctx: AppContext, args, task: TaskKind, responder: Callable[[str, list[Message]], str]
) -> None:
    settings = AppSettings(
        target_lang=args.lang,
        # 并发由评测脚本自己的 --jobs 等参数控制，网关不再额外收紧
        providers=[
            ProviderConfig(id="eval", name="评测", base_url=args.base_url, max_concurrency=32)
        ],
        routes={task: ModelRoute(provider_id="eval", model=args.model)},
    )
    # 先保存服务地址再记同意：地址变了时 SettingsService 会作废旧的同意（隐私规则），
    # 同一次 put 里带上同意会被当成"旧地址的同意"丢掉
    ctx.settings.put(settings)
    ctx.settings.put(settings.model_copy(update={"consented_providers": ["eval"]}))
    if args.fake or args.replay:
        replay = Path(args.replay) if args.replay else None
        fake = FakeProvider("eval", responder=responder, replay_file=replay)
        ctx.llm._factory = lambda config, key: fake
    elif args.record:
        default = ctx.llm._factory
        ctx.llm._factory = lambda config, key: RecordingProvider(
            default(config, key), Path(args.record)
        )


async def import_and_parse(ctx: AppContext, entry: dict, engine: str) -> str | None:
    """导入评测集里的 PDF 并解析（已解析则跳过），返回 doc_id；PDF 不在时返回 None。"""
    pdf = FIX / "files" / f"{entry['doc_id']}.pdf"
    if not pdf.is_file():
        return None
    item_id, _ = ctx.library.import_file(pdf)
    doc_id = ctx.library.get_item(item_id).documents[0].doc_id
    if ctx.parse.get(doc_id).parse_status != "ready":
        await ctx.parse.run(doc_id, engine, _noop)
    return doc_id
