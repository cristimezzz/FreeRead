import json
import re
from collections import Counter

import pytest

from freeread.domain.kg.extract import (
    DocGraph,
    LocalEntity,
    LocalRelation,
    evidence_in_text,
    merge_groups,
    parse_group,
    parse_value,
    prune,
    value_in_text,
)
from freeread.domain.kg.normalize import acronym_split, name_norm
from freeread.domain.kg.schema import EntityType, RelationType
from freeread.infra.db.models import (
    BlockRow,
    DocumentRow,
    KGEntityRow,
    KGMentionRow,
    KGRelationRow,
    LLMCallRow,
)
from freeread.infra.jobs.worker import JobContext
from freeread.infra.llm.errors import ProviderError
from freeread.infra.llm.fake import FakeProvider
from freeread.services.kg import migrate_kg
from freeread.services.llm_preflight import PreflightError
from tests.test_glossary import run_job
from tests.test_translate import configure

PAPER_1 = [
    "FooNet: Fast Image Classification",
    "We propose FooNet for image classification. It uses attention.",
    "FooNet achieves 85.3% top-1 accuracy on ImageNet, improving on ResNet-50 (76.1%).",
]
PAPER_2 = [
    "BarNet: Building on FooNet",
    "BarNet builds on FooNet and is evaluated on ILSVRC.",
    "BarNet achieves 87.0% top-1 accuracy on ImageNet-1k.",
]

TYPES = {
    "FooNet": "Model",
    "BarNet": "Model",
    "ResNet-50": "Model",
    "ImageNet-1k": "Dataset",
    "ImageNet": "Dataset",
    "ILSVRC": "Dataset",
    "top-1 accuracy": "Metric",
    "image classification": "Task",
    "attention": "Method",
}
LINE_RE = re.compile(r"^\[(b_\d+)\] (.*)$", re.MULTILINE)


def _present(name: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None


def responder(model, messages):
    user = messages[-1].content
    lines = LINE_RE.findall(user)
    names = [n for n in TYPES if any(_present(n, t) for _, t in lines)]
    entities = [{"id": n, "type": TYPES[n], "name": n} for n in names]
    if "FooNet" in names:
        entities[names.index("FooNet")]["aliases"] = ["FN"]
    relations = []
    for bid, text in lines:
        model_name = next((m for m in ("BarNet", "FooNet") if text.startswith(m)), None)
        if "propose FooNet" in text:
            relations.append(
                {
                    "src": "FooNet",
                    "dst": "image classification",
                    "type": "proposes",
                    "block_id": bid,
                }
            )
        if model_name and "achieves" in text:
            value = re.search(r"(\d+\.\d)%", text).group(1)
            dataset = "ImageNet-1k" if "ImageNet-1k" in text else "ImageNet"
            relations += [
                {
                    "src": model_name,
                    "dst": "top-1 accuracy",
                    "type": "achieves",
                    "block_id": bid,
                    "evidence": f"achieves {value}% top-1 accuracy",
                    "attrs": {"metric": "top-1 accuracy", "value": value, "dataset": dataset},
                },
                # 原文里没有的数值：应被丢弃
                {
                    "src": model_name,
                    "dst": "top-1 accuracy",
                    "type": "achieves",
                    "block_id": bid,
                    "attrs": {"metric": "top-1 accuracy", "value": "99.9"},
                },
                {"src": model_name, "dst": dataset, "type": "evaluated_on", "block_id": bid},
            ]
        if "improving on ResNet-50" in text:
            relations.append(
                {
                    "src": "FooNet",
                    "dst": "ResNet-50",
                    "type": "improves_on",
                    "block_id": bid,
                    "evidence": "编造的证据",
                }
            )
        if "builds on FooNet" in text:
            relations += [
                {"src": "BarNet", "dst": "FooNet", "type": "improves_on", "block_id": bid},
                {"src": "BarNet", "dst": "ILSVRC", "type": "evaluated_on", "block_id": bid},
                # 不存在的块：应被丢弃
                {"src": "BarNet", "dst": "FooNet", "type": "uses", "block_id": "b_0999"},
            ]
    return "```json\n" + json.dumps({"entities": entities, "relations": relations}) + "\n```"


def write_paper(path, paras):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    for i, p in enumerate(paras):
        y = 72 + 80 * i
        page.insert_textbox(pymupdf.Rect(72, y, 520, y + 60), p, fontsize=10)
    doc.save(path)
    doc.close()
    return path


async def make_doc(ctx, tmp_path, name, paras):
    item_id, _ = ctx.library.import_file(write_paper(tmp_path / f"{name}.pdf", paras))
    doc_id = ctx.library.get_item(item_id).documents[0].doc_id

    async def noop(*_):
        pass

    await ctx.parse.run(doc_id, "pymupdf", noop)
    return doc_id


async def extract(ctx, doc_id):
    ctx.kg.request_extract(doc_id)
    await run_job(ctx, "kg_extract", ctx.kg.run_extract_job)
    return ctx.kg.doc_graph(doc_id)


def by_name(graph):
    return {e.name: e for e in graph.entities}


# ------------------------------------------------------------ 纯函数


def test_name_norm_and_acronyms():
    assert name_norm("ResNet-50") == name_norm("resnet 50") == name_norm("ResNet50")
    assert name_norm("GPT-3.5") != name_norm("GPT-35")
    assert name_norm("“BERT’s”") == "bert"
    assert name_norm("β-VAE") == "betavae"
    assert acronym_split("Long Short-Term Memory (LSTM)") == ["Long Short-Term Memory", "LSTM"]
    assert acronym_split("长短期记忆网络（LSTM）") == ["长短期记忆网络", "LSTM"]
    assert acronym_split("ImageNet") == ["ImageNet"]


def test_values_and_evidence():
    assert parse_value("85.3%") == (85.3, "85.3%")
    assert parse_value("<50") == (50.0, "<50")
    assert parse_value("0.07 ± 0.05") == (0.07, "0.07 ± 0.05")
    assert parse_value(28.4) == (28.4, "28.4")
    assert parse_value("n/a") is None
    assert value_in_text(85.3, "reaches 85.30 on the test set")
    assert value_in_text(1234.0, "1,234 images")
    assert not value_in_text(0.853, "85.3%")
    assert not value_in_text(50.0, "ResNet-50")  # 名称里的数字不算 -50
    # 中文紧挨着数字（评测集的中译本里很常见）
    assert value_in_text(66.5, "其T1/2 在10mM中为66.5h")
    assert value_in_text(41.0, "表达最高增加41倍")
    assert not value_in_text(2.0, "codonGPT2 模型")
    # 摘句：PDF 换行在中文里插入的空格、英文里丢掉的空格、连字符写法、省略号截断
    assert evidence_in_text("同时保持同义保真度", "同时保持同义保 真度，而无需")
    assert evidence_in_text("BD Canto II", "样品在BDCantoII上分析")
    assert evidence_in_text("GC-CAI trend", "the positive GC‑CAI trend")
    assert evidence_in_text("Histone QTLs … autoimmune", "Histone QTLs are enriched for autoimmune")
    assert not evidence_in_text(
        "autoimmune … Histone QTLs", "Histone QTLs are enriched for autoimmune"
    )
    assert not evidence_in_text("…", "anything")


def test_parse_group_enforces_provenance():
    blocks = {"b_0001": "FooNet achieves 85.3 BLEU on WMT14.", "b_0002": "RoBERTa is strong."}
    raw = {
        "entities": [
            {"id": "e1", "type": "model", "name": "FooNet", "block_ids": ["b_1"]},
            {"id": "e2", "type": "Metric", "name": "BLEU"},
            {"id": "e3", "type": "Dataset", "name": "WMT14"},
            {"id": "e4", "type": "Model", "name": "BERT"},  # 只在 RoBERTa 里"出现"：不算提及
            {"id": "e5", "type": "Planet", "name": "Mars"},  # 未知类型
        ],
        "relations": [
            {"src": "e1", "dst": "e2", "type": "achieves", "block_id": "b_0001",
             "attrs": {"value": "85.3"}, "evidence": "achieves  85.3 bleu"},
            {"src": "e1", "dst": "e2", "type": "achieves", "block_id": "b_0001",
             "attrs": {"value": "86"}},  # 原文没有这个数
            {"src": "e1", "dst": "e3", "type": "evaluated on", "block_id": "b_0003"},  # 不在本组
            {"src": "e1", "dst": "e3", "type": "evaluated-on", "block_id": "B_0001",
             "evidence": "不在原文里", "confidence": 0.9},
            {"src": "e1", "dst": "e9", "type": "uses", "block_id": "b_0001"},  # 端点不存在
        ],
    }  # fmt: skip
    entities, relations, stats = parse_group(raw, blocks)
    assert [e.name for e in entities] == ["FooNet", "BLEU", "WMT14"]
    assert entities[0].type is EntityType.MODEL and entities[0].mentions == {"b_0001": "FooNet"}
    assert [r.type for r in relations] == [RelationType.ACHIEVES, RelationType.EVALUATED_ON]
    assert relations[0].attrs == {"value": 85.3, "value_text": "85.3"}
    assert relations[0].evidence == "achieves 85.3 bleu"
    assert relations[1].evidence == "" and relations[1].confidence == pytest.approx(0.63)
    assert stats == Counter(
        bad_entities=2, unverified_values=1, no_source=1, bad_relations=1, unsupported_evidence=1
    )

    merged = merge_groups([(entities, relations, stats), (entities, relations, Counter())])
    assert len(merged.entities) == 3 and len(merged.relations) == 2


def test_prune_keeps_important_entities():
    def ent(name, etype=EntityType.CONCEPT, blocks=1):
        return LocalEntity(
            etype, name, [name], mentions={f"b_{i:04d}": name for i in range(blocks)}
        )

    entities = [
        ent("FooNet", EntityType.MODEL),
        ent("ImageNet", EntityType.DATASET),
        ent("lonely"),  # 没有关系、只出现一次：去掉
        ent("often", EntityType.METHOD, blocks=3),  # 没有关系但多次出现：保留
    ] + [ent(f"c{i}") for i in range(5)]
    relations = [LocalRelation(0, 1, RelationType.EVALUATED_ON, "b_0000")] + [
        LocalRelation(0, 4 + i, RelationType.USES, "b_0000") for i in range(5)
    ]
    graph = prune(DocGraph(entities, relations, Counter(unverified_values=1)), max_concepts=3)
    names = [e.name for e in graph.entities]
    assert names[:2] == ["FooNet", "ImageNet"] and "lonely" not in names
    assert sum(e.type is EntityType.CONCEPT for e in graph.entities) == 3
    assert graph.stats == Counter(unverified_values=1, pruned=3)
    assert all(r.src < len(names) and r.dst < len(names) for r in graph.relations)
    assert len(graph.relations) == 1 + 3  # 被去掉的 Concept 的关系一起去掉

    small = prune(DocGraph(entities, relations), max_entities=1)
    assert [e.name for e in small.entities] == ["FooNet"] and small.relations == []


# ------------------------------------------------------------ 抽取任务


async def test_extract_job_stores_graph_with_provenance(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=responder))
    doc_id = await make_doc(ctx, tmp_path, "foo", PAPER_1)
    graph = await extract(ctx, doc_id)

    assert graph.kg_status == "ready"
    names = by_name(graph)
    # attention 没有关系、只出现一次：被精简掉
    assert set(names) == {
        "FooNet",
        "ImageNet",
        "ResNet-50",
        "top-1 accuracy",
        "image classification",
    }
    assert graph.entities[0].name == "FooNet" and names["FooNet"].aliases == ["FN"]
    assert names["FooNet"].score == 2 * 4 + len(names["FooNet"].block_ids)
    with ctx.sessions() as s:
        block_ids = {b.block_id for b in s.query(BlockRow).filter_by(doc_id=doc_id)}
        assert s.query(LLMCallRow).filter_by(prompt_id="kg_extract@3").count() == 1
    assert {r.block_id for r in graph.relations} <= block_ids
    assert all(b in block_ids for e in graph.entities for b in e.block_ids)
    achieves = [r for r in graph.relations if r.type == "achieves"]
    assert len(achieves) == 1  # 99.9 被丢弃
    assert achieves[0].attrs["value"] == 85.3 and achieves[0].attrs["dataset"] == "ImageNet"
    assert achieves[0].evidence == "achieves 85.3% top-1 accuracy"
    assert (achieves[0].src_name, achieves[0].dst_name) == ("FooNet", "top-1 accuracy")
    improves = next(r for r in graph.relations if r.type == "improves_on")
    assert improves.evidence == "" and improves.confidence < 0.8  # 编造的证据被清空

    job = ctx.jobs.list(kind="kg_extract")[0]
    assert job.kind == "kg_extract" and job.message.startswith("5 个实体、4 条关系")
    assert "略去 1 个次要实体" in job.message and "丢弃 1 条" in job.message

    # 重新抽取（命中缓存）整体替换，不重复写入
    again = await extract(ctx, doc_id)
    assert len(again.entities) == 5 and len(again.relations) == 4
    assert not {e.id for e in again.entities} & {e.id for e in graph.entities}


async def test_each_document_has_its_own_graph(ctx, tmp_path):
    """同名实体在两篇论文里是各自的节点；删除文档时它的图一起删除。"""
    configure(ctx, FakeProvider("p1", responder=responder))
    doc1 = await make_doc(ctx, tmp_path, "foo", PAPER_1)
    doc2 = await make_doc(ctx, tmp_path, "bar", PAPER_2)
    g1, g2 = await extract(ctx, doc1), await extract(ctx, doc2)
    assert by_name(g1)["FooNet"].id != by_name(g2)["FooNet"].id
    assert {r.type for r in g2.relations} == {"improves_on", "evaluated_on", "achieves"}
    assert all(r.block_id != "b_0999" for r in g2.relations)
    assert "ResNet-50" not in by_name(g2)

    with ctx.sessions.begin() as s:
        s.delete(s.get(DocumentRow, doc2))
    with ctx.sessions() as s:
        assert {e.doc_id for e in s.query(KGEntityRow)} == {doc1}
        assert {r.doc_id for r in s.query(KGRelationRow)} == {doc1}
    assert len(ctx.kg.doc_graph(doc1).entities) == len(g1.entities)


async def test_reparse_migrates_provenance(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=responder))
    doc_id = await make_doc(ctx, tmp_path, "foo", PAPER_1)
    before = await extract(ctx, doc_id)

    async def noop(*_):
        pass

    await ctx.parse.run(doc_id, "pymupdf", noop)  # 文本不变：出处原样保留
    after = ctx.kg.doc_graph(doc_id)
    assert {r.block_id for r in after.relations} == {r.block_id for r in before.relations}
    assert all(r.status == "ok" for r in after.relations)

    with ctx.sessions.begin() as s:
        assert migrate_kg(s, doc_id, {}) == len(before.relations)
    with ctx.sessions() as s:
        assert s.query(KGMentionRow).filter_by(doc_id=doc_id).count() == 0
        assert {r.status for r in s.query(KGRelationRow).filter_by(doc_id=doc_id)} == {"stale"}


async def test_fatal_provider_error_fails_job_with_reason(ctx, tmp_path):
    """余额不足 / 密钥无效：任务失败，原因是服务商的错误，而不是"没有可解析的结果"。"""
    error = ProviderError("p1: HTTP 402: Insufficient Balance", 402)
    fake = FakeProvider("p1", script=[error, error, error])
    configure(ctx, fake)
    doc_id = await make_doc(ctx, tmp_path, "foo", PAPER_1)
    ctx.kg.request_extract(doc_id)
    job = ctx.jobs.claim_next({"kg_extract"})
    with pytest.raises(RuntimeError, match="调用模型失败.*HTTP 402"):
        await ctx.kg.run_extract_job(JobContext(job, ctx.jobs))
    assert ctx.kg.doc_graph(doc_id).kg_status == "failed"
    assert len(fake.calls) == 1  # 不重试、不继续调用


async def test_auto_enqueue_and_preflight(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=responder), consent=False)
    doc_id = await make_doc(ctx, tmp_path, "foo", PAPER_1)
    assert ctx.kg.enqueue_auto(doc_id) is None  # 默认关闭
    settings = ctx.settings.get()
    ctx.settings.put(
        settings.model_copy(update={"kg": settings.kg.model_copy(update={"auto": True})})
    )
    assert ctx.kg.enqueue_auto(doc_id) is None  # 还没确认发送
    with pytest.raises(PreflightError) as e:
        ctx.kg.request_extract(doc_id)
    assert e.value.code == "consent_required"

    ctx.settings.put(ctx.settings.get().model_copy(update={"consented_providers": ["p1"]}))
    job = ctx.kg.enqueue_auto(doc_id)
    assert job is not None and job.kind == "kg_extract"
    assert ctx.kg.enqueue_auto(doc_id).id == job.id  # 排队中的去重
    assert ctx.embed.on_embedded == ctx.kg.enqueue_auto


def test_kg_api(client, tmp_path):
    ctx = client.app.state.ctx
    configure(ctx, FakeProvider("p1", responder=responder))
    doc_id = client.portal.call(make_doc, ctx, tmp_path, "foo", PAPER_1)

    assert client.get(f"/documents/{doc_id}/kg").json()["kg_status"] == "pending"
    r = client.post(f"/documents/{doc_id}/kg/extract")
    assert r.status_code == 202 and r.json()["kind"] == "kg_extract"
    client.portal.call(_wait_job, ctx, r.json()["id"])

    graph = client.get(f"/documents/{doc_id}/kg").json()
    assert graph["kg_status"] == "ready" and len(graph["entities"]) == 5
    foo = next(e for e in graph["entities"] if e["name"] == "FooNet")
    assert foo["aliases"] == ["FN"] and foo["block_ids"] and foo["score"] > 0
    assert len(graph["relations"]) == 4 and all(r["block_id"] for r in graph["relations"])
    assert client.get("/documents/nope/kg").status_code == 404
    assert client.get("/kg/entities").status_code == 404  # 不再有全库实体接口

    assert client.post("/documents/nope/kg/extract").status_code == 404
    ctx.settings.put(ctx.settings.get().model_copy(update={"consented_providers": []}))
    r = client.post(f"/documents/{doc_id}/kg/extract")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required"


async def _wait_job(ctx, job_id):
    import asyncio

    for _ in range(200):
        job = ctx.jobs.get(job_id)
        if job.status in ("done", "failed"):
            assert job.status == "done", job.error
            return
        await asyncio.sleep(0.05)
    raise AssertionError("kg_extract job did not finish")
