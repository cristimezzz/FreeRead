# FreeRead 系统架构

- 版本：0.1（草案）
- 更新日期：2026-10-17
- 相关决策：[ADR-0001](adr/0001-tauri-python-sidecar.md)、[ADR-0002](adr/0002-local-first-sqlite.md)、[ADR-0003](adr/0003-pluggable-parser.md)、[ADR-0004](adr/0004-document-ir-as-core.md)、[ADR-0005](adr/0005-llm-gateway.md)、[ADR-0006](adr/0006-material3-ui.md)

## 1. 设计原则

1. **IR 为核心**：所有功能都围绕统一文档模型（[Document IR](02-document-ir.md)）运转。重排是 IR 的渲染，翻译是 IR 上的平行文本，总结、问答和图谱都引用 IR 的 `block_id`，从而任何 AI 输出都能追溯到原文位置。
2. **本地优先**：数据存在本地 SQLite 和文件目录中；外部服务（LLM、云解析）都是可替换的插件。
3. **可插拔**：解析引擎、LLM 提供方、Zotero 接入方式都放在接口后面。
4. **长任务异步化**：解析、嵌入、图谱抽取、批量翻译都走持久化任务队列，前端通过 SSE 获取进度。
5. **一切可缓存**：解析结果按 `pdf_hash + parser_version` 缓存；LLM 结果按 `hash(input + model + prompt_version)` 缓存。

## 2. 系统上下文（C4 Level 1）

```
                ┌──────────────┐
                │   研究者用户   │
                └──────┬───────┘
                       │ 阅读 / 提问
                ┌──────▼───────┐
   ┌───────────►│   FreeRead   │◄────────────┐
   │            └──┬────────┬──┘             │
   │               │        │                │
┌──┴──────┐  ┌─────▼────┐ ┌─▼────────────┐ ┌─┴──────────┐
│ Zotero  │  │ LLM 提供方│ │ 云端解析服务   │ │ 本地文件系统 │
│本地/云端 │  │OpenAI兼容 │ │（可选）       │ │ PDF / 数据  │
│         │  │Claude等   │ │              │ │            │
└─────────┘  └──────────┘ └──────────────┘ └────────────┘
```

## 3. 容器视图（C4 Level 2）

```
┌──────────────────── Desktop App (Tauri 2) ─────────────────────┐
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Frontend (React + TS, 运行于 WebView)                      │  │
│  │ Library │ Reader(PDF ⇄ Reflow) │ Translate │ Summary │ Graph │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│  ┌───────────────────────┴──────────┐                          │
│  │ Rust 壳：窗口、文件对话框、钥匙串、   │                          │
│  │ sidecar 进程生命周期管理            │                          │
│  └───────────────────────┬──────────┘                          │
└──────────────────────────┼─────────────────────────────────────┘
                           │ HTTP(127.0.0.1, 随机端口 + 会话 token) + SSE
┌──────────────────────────▼─────────────────────────────────────┐
│ Core Service (Python 3.11+, FastAPI, 作为 sidecar 打包)          │
│  API → Services → Domain → Infrastructure                       │
└───────┬──────────────┬─────────────────┬───────────────────────┘
        │              │                 │
   ┌────▼────┐   ┌─────▼──────┐   ┌──────▼─────────┐
   │ SQLite  │   │ 向量索引     │   │ 数据目录         │
   │ 主库     │   │ sqlite-vec │   │ IR / 图片 / 快照 │
   └─────────┘   └────────────┘   └────────────────┘
```

**进程通信**：Rust 壳启动 sidecar 时分配随机端口和一次性 token，经由启动参数传入；前端每个请求都带上该 token，防止本机其他程序调用。

## 4. 组件视图（C4 Level 3：Core Service）

```
api/            路由与 DTO（REST + SSE）
  ├─ library.py  reader.py  translate.py  summary.py  qa.py  jobs.py  settings.py
services/       应用服务：编排领域对象与基础设施
  ├─ LibraryService    导入、同步、条目管理
  ├─ ReaderService     获取 IR、定位映射、批注
  ├─ TranslateService  块级翻译、术语表、缓存
  ├─ SummaryService    分层总结
  └─ QAService         RAG / 图检索 / 问答树
domain/         纯领域模型，不依赖框架
  ├─ ir/        Document IR 模型与校验
  ├─ kg/        实体、关系、消歧规则
  └─ qa/        问答树、引用
infra/          基础设施适配器
  ├─ zotero/    ZoteroConnector：LocalApi / SqliteSnapshot / WebApi
  ├─ parsers/   Parser 接口及实现：MinerU / Docling / PyMuPDF(fast) / Cloud
  ├─ llm/       LLMGateway：providers、路由、缓存、用量统计
  ├─ jobs/      SQLite 持久化任务队列 + asyncio worker
  └─ db/        SQLAlchemy 模型、仓储、Alembic 迁移
prompts/        带版本号的提示词模板（YAML + Jinja2）
```

依赖方向：`api → services → domain`，`services → infra`。`domain` 不依赖任何其他层。

## 5. 关键模块设计

### 5.1 Zotero 接入

```python
class ZoteroConnector(Protocol):
    async def list_collections(self) -> list[Collection]: ...
    async def list_items(self, since_version: int | None = None) -> list[Item]: ...
    async def resolve_attachment(self, item: Item) -> Path | None: ...
```

| 实现 | 前提 | 用途 |
|---|---|---|
| `LocalApiConnector` | Zotero 7 正在运行，本地 API 已启用（`http://localhost:23119/api/`） | 默认方式，只读 |
| `SqliteSnapshotConnector` | 能找到 Zotero 数据目录 | Zotero 未运行时；**先复制 `zotero.sqlite` 到快照目录再只读打开**，附件路径从 `storage/<key>/` 解析 |
| `WebApiConnector` | 用户提供 API Key 与 library ID | 云同步；后续用于写回 |

同步策略：记录每个 library 的最后同步 version，增量拉取；本地以 `zotero_key` 作为外部主键做 upsert；Zotero 端删除的条目在本地标记为 `archived`，不立即物理删除。M1 先做全量拉取（`LibraryService.sync_zotero`），增量在 M2。

- 没有父条目的独立 PDF 也作为文献导入（`item_type = attachment`，`extra.standalone = true`，标题取附件标题或文件名）。
- 同步时可以指定一个分类：元数据仍全量更新，只为该分类（含子分类）下的条目建解析任务。
- Zotero 附件原地引用；手动导入的 PDF 复制到 `documents/<doc_id>/source.pdf`，因为原文件可能被移动或删除。

### 5.2 解析管线

```
PDF ─► 计算 sha256 ─► 命中缓存? ──是──► 返回 IR
                        │否
                        ▼
      Parser.parse(pdf) → RawLayout（引擎原生输出）
                        ▼
      Normalizer：RawLayout → Document IR
        · 统一块类型  · 阅读顺序  · 章节路径  · 图/表与图注配对
        · 公式 LaTeX 规范化  · 参考文献结构化  · 坐标统一为 PDF 点(pt)
                        ▼
      Validator（JSON Schema + 规则检查）
                        ▼
      写入 data/documents/<doc_id>/ir.json + 资源图片；blocks 表入库
                        ▼
      触发后续任务：embed → kg_extract（按设置）
```

```python
class Parser(Protocol):
    name: str
    version: str
    def capabilities(self) -> ParserCaps: ...      # 是否支持公式、表格、需 GPU 等
    async def parse(self, pdf: Path, out_dir: Path, progress: ProgressCb) -> RawLayout: ...
```

每个引擎一个 Normalizer，保证上层只看到 IR。

M1 实现（`services/parse.py`）：

- 两类任务：`parse`（PyMuPDF 快速模式，并发 2，秒级出可读 IR）和 `parse_hq`（MinerU / Docling，全局并发 1）。`parse` 完成后按设置 `parse_engine` 追加 `parse_hq`；`auto` 表示 MinerU 可用时升级。
- 自动流程不会用低质量引擎的结果覆盖高质量结果；用户手动重新解析（`POST /documents/{id}/parse`）不受此限。
- `raw/<engine>/engine.json` 存在即视为原生输出完整：只升级 Normalizer 时直接从 `raw/` 重新规范化，不重新跑引擎。
- 图 / 表图片按 bbox 从 PDF 页面截取（150 dpi），与引擎无关。
- MinerU 以常驻 worker 运行（`infra/parsers/resident.py` + `scripts/engines/mineru_worker.py`，JSON Lines 协议），空闲 10 分钟退出。本机 RTX 3050 Ti 4GB 上合成 PDF：冷启动 31 s，热调用 1.4 s。
- 第一次解析失败标记 `failed`；已有可读 IR 时升级失败保持 `ready`。解析状态变化通过 `/jobs/stream` 的 `document` 事件推送。

### 5.3 重排渲染与双向定位

- 前端按 IR 渲染：`heading/paragraph` → 语义 HTML；`equation` → KaTeX；`table` → 净化后的 HTML；`figure` → 图片 + 图注。
- 每个渲染节点带 `data-block-id`。
- **重排 → 原版**：点击块 → 取 `anchors[0]` → pdf.js 跳到对应页并绘制 bbox 高亮。
- **原版 → 重排**：点击 PDF 坐标 → 在该页 anchors 中做点包含查询（前端缓存每页的 bbox 索引）→ 滚动到对应块。
- 跨页段落有多个 anchor。

### 5.4 LLM Gateway

```python
class LLMGateway:
    async def complete(self, task: TaskKind, messages, **opts) -> LLMResult: ...
    def stream(self, task: TaskKind, messages, **opts) -> AsyncIterator[LLMChunk]: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- `TaskKind`：`translate | summarize | qa | kg_extract | glossary | embed`，在设置里为每种任务指定 provider + model。
- Provider 适配：`openai_compatible`（覆盖 OpenAI、DeepSeek、通义、Moonshot、vLLM 等）、`anthropic`、`ollama`。
- 缓存：`llm_cache` 表，键为 `sha256(provider|model|prompt_id@version|canonical_input)`。
- 限流与重试：每个 provider 一个令牌桶；429 / 5xx 指数退避。
- 审计：每次调用写入 `llm_calls`（token、耗时、估算费用、任务类型、关联 doc_id）。
- 密钥：Rust 壳从系统钥匙串读取后，在启动 sidecar 时通过环境变量注入；Python 端不落盘。

### 5.5 翻译

1. 前端上报可视区域的 block_id 列表 → `POST /translate/blocks`。
2. 服务端过滤出已缓存的块，立即返回；其余按章节分批。
3. **占位保护**：行内公式、引用标记、URL、行内代码替换为 `⟦EQ1⟧`、`⟦CITE3⟧` 等；翻译后校验占位符完整（数量、顺序一致），不一致则重试一次，仍失败就标记 `needs_review` 并回退原文。
4. 上下文：论文标题 + 摘要 + 当前章节标题 + 前一块原文 + 术语表中命中的条目。
5. 结果以 SSE 按块推送，写入 `translations` 表。

块级 `equation`、`table`、`figure` 不翻译（表格内文本和图注作为可选项）。

M1 实现（`services/translate.py`、`domain/translate/placeholders.py`）与上面的差异：

- 占位符只校验**数量**（每个恰好出现一次），不校验顺序：中文语序调整后引用的先后可能合理地变化。模型写成 `⟦ CITE1 ⟧`、`[[CITE1]]`、`【CITE1】` 的会先统一回标准写法。只保护数字引用 `[1, 3–5]`；作者年份引用要翻译，不保护。
- 不按章节分批，而是逐块调用、全局并发 3，可视区域内的块按请求顺序开始；同一块同一语言并发请求时只调用一次。前端断开（滚走）时，没有其他请求在等的块会被取消。
- 上下文暂不含摘要和术语表（术语表在 M2）。
- 重试一次时绕开 LLM 缓存（否则拿回同一个错误译文）；两次都失败时 `needs_review`，译文存原文。
- 发送前检查：任务路由已配置、provider 有密钥、用户已确认向该 provider 发送内容（`settings.consented_providers`）；不满足时 SSE 发 `error` 事件（`route_not_configured` / `missing_api_key` / `consent_required`），已有译文仍先发出。
- 文档语言与目标语言相同时不翻译。离线阅读走 `GET /documents/{id}/translations`，只读本地库。

### 5.6 AI 总结

- **Map**：按一级章节分组，每组生成章节摘要，输出 JSON：`[{point, block_ids[]}]`。
- **Reduce**：把章节摘要汇总成全文结构化总结（问题 / 方法 / 实验 / 结论 / 局限 / 可复用点），每条保留 `block_ids`。
- 校验：引用的 block_id 必须存在于该文档；无引用的结论在 UI 中标记为"未溯源"。
- 存入 `summaries`，键为 `(doc_id, template_id, model, prompt_version)`。

### 5.7 图状结构问答

**A. 知识图谱（检索层）**

- 抽取：对每篇文档按章节调用 LLM，按固定 schema 输出实体与关系。
  - 实体类型：`Task, Method, Dataset, Metric, Model, Concept, Claim`
  - 关系类型：`proposes, uses, improves_on, evaluated_on, achieves, compares_with, contradicts, part_of`
  - 每条关系必须带 `source_block_id`，`achieves` 可带数值属性（metric、value）。
- 消歧：名称归一化（大小写、缩写表）→ 嵌入相似度候选 → 阈值以上合并，模糊区间交给 LLM 判定；合并记录保留别名。
- 存储：`kg_entities`、`kg_relations` 表；查询时按需加载子图到 NetworkX。

**混合检索流程**

```
问题 ─► 查询改写 / 实体识别
     ├─► 向量检索 top-k blocks（限定范围：当前文档 / 分类 / 全库）
     └─► 识别出的实体 → 图上 k 跳扩展（k ≤ 2）→ 相关关系及其 source blocks
     合并、去重、重排序 ─► 组装上下文（每段带 block_id）
     ─► LLM 生成答案（要求以 [b_xxxx] 标注引用）
     ─► 引用校验 ─► 返回答案 + 引用 + 涉及子图（供可视化）
```

**B. 问答画布（交互层）**

- 问答树：`qa_nodes(id, session_id, parent_id, question, answer, citations, pinned_blocks, subgraph)`。
- 节点上下文 = 祖先链的问答（超长时摘要压缩）+ 本节点固定的原文片段 + 本次检索结果。
- 前端用 React Flow 渲染；可以把图谱实体或原文块拖到节点上作为固定上下文。

### 5.8 任务队列

- `jobs` 表：`id, kind, payload, status(queued|running|done|failed|cancelled), progress, depends_on, attempts, error, timestamps`。
- 单进程 asyncio worker；CPU / GPU 重任务（解析）放到独立的进程池，并发数 1，避免显存争用。
- 任务链：`import → parse → embed → kg_extract`，前一个完成后创建下一个。
- 应用重启后，将 `running` 状态重置为 `queued`；解析引擎以页为单位记录进度以支持续跑（视引擎能力而定）。
- 进度通过 `GET /jobs/stream`（SSE）推送。

## 6. API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/library/items` | 列表、搜索、按分类筛选 |
| POST | `/library/sync` | 触发 Zotero 同步（返回 job_id） |
| POST | `/library/import-file` | 导入本地 PDF |
| GET | `/documents/{doc_id}/ir` | 获取 IR |
| POST | `/documents/{doc_id}/parse` | （重新）解析，可指定引擎 / 页范围 |
| POST | `/translate/blocks` | 翻译指定块（SSE 流式） |
| GET/PUT | `/glossary` | 术语表 |
| POST | `/documents/{doc_id}/summary` | 生成总结（SSE） |
| POST | `/qa/sessions` / `/qa/sessions/{id}/nodes` | 创建问答会话 / 提问（可指定 parent_id，SSE） |
| GET | `/kg/subgraph` | 按实体或文档范围取子图 |
| GET | `/jobs/stream` | 任务进度 SSE |
| GET/PUT | `/settings` | 设置（不含密钥） |

完整定义以 FastAPI 自动生成的 OpenAPI 为准；前端用 `openapi-typescript` 生成类型。

## 7. 前端结构

```
apps/desktop/src/
├─ app/              路由、布局、全局 Provider（含 ThemeProvider）
├─ api/              生成的类型 + fetch / SSE 客户端
├─ features/
│  ├─ library/       文献列表、分类树、同步状态
│  ├─ reader/        PdfView(pdf.js)、ReflowView、定位联动、批注
│  ├─ translate/     译文显示模式、术语表编辑
│  ├─ summary/       总结面板、引用跳转
│  └─ graph/         图谱浏览(Cytoscape.js)、问答画布(React Flow)
├─ stores/           Zustand
└─ components/       通用 UI；m3/ 放官方缺失的 M3 组件（导航栏、侧边面板、表格等）
```

UI 采用 Material 3，组件使用官方 `@material/web`，配色由 `@material/material-color-utilities` 按用户选择的种子色生成，见 [ADR-0006](adr/0006-material3-ui.md)。

## 8. 数据目录布局

```
%APPDATA%/FreeRead/            （macOS: ~/Library/Application Support/FreeRead）
├─ freeread.db                 主库（含 sqlite-vec 向量表）
├─ documents/<doc_id>/
│  ├─ ir.json
│  ├─ raw/                     解析引擎原始输出（便于重新规范化）
│  └─ assets/                  图片、表格截图
├─ zotero-snapshots/           zotero.sqlite 只读快照
├─ models/                     本地解析 / 嵌入模型
└─ logs/
```

## 9. 测试与评测

| 层级 | 内容 |
|---|---|
| 单元测试 | domain 层纯逻辑、Normalizer、占位保护、引用校验（pytest） |
| 集成测试 | API + SQLite（临时库）；LLM 使用录制回放的假 provider |
| 解析评测 | `core/tests/fixtures/pdfs/` 下 20–50 篇代表性 PDF（双栏、公式密集、扫描版、中文论文、长附录），配人工标注的 golden IR 片段；指标：块类型准确率、阅读顺序（Kendall τ）、公式 LaTeX 编辑距离 |
| 翻译评测 | 占位还原率；抽样人工评分；可选 LLM-as-judge |
| 总结 / 问答评测 | 引用覆盖率、引用正确率（引用块是否支持该结论）、人工忠实度抽检 |
| 前端 | Vitest 组件测试；Playwright 跑关键流程 |

## 10. 安全与隐私

- sidecar 只监听 `127.0.0.1`，并校验会话 token。
- Zotero 数据只读；快照与原库隔离。
- 首次向某个外部 LLM 或云解析服务发送文档内容前弹窗告知。
- 表格 HTML、LLM 输出在渲染前做净化（DOMPurify），防止 XSS。
- 日志中不记录密钥和全文内容。
