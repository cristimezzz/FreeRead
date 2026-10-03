# 02 · 领域模型规范

> 状态：**冻结**。领域层位于 `packages/core/src/domain/`，**零外部依赖**、纯类型 + 纯函数。
> 持久化映射见 `05-storage.md`；锚点结构见 `03-anchor-model.md`（本文件不重复定义 `DocAnchorModel` 内部字段）。

---

## 1. 实体与值对象

| 名称 | 类型 | 标识 | 说明 |
|---|---|---|---|
| `Document` | 实体 | `docId`（sha256） | 一篇文献；生命周期见 §3.1 |
| `LibraryEntry` | 实体 | `citekey` | 文献库中的条目（`Document` + 元数据 + 标签），一个 `Document` 可对应多条 `LibraryEntry`（同一文件不同分类） |
| `Meta` | 值对象 | — | 见 `schemas/meta.schema.json` |
| `ReadingSession` | 实体 | `sessionId`（ULID） | 一次阅读会话（进程内），承载当前 `sentenceId` 与视图状态 |
| `ReadingProgress` | 值对象 | — | `{docId, sentenceId, page, scrollRatio, updatedAt}` |
| `Annotation` | 实体 | `id`（ULID） | 见 `schemas/annotation.schema.json` |
| `DocAnchorModel` | 值对象（不可变） | `docId + cacheKey` | 锚点模型，见 `03-anchor-model.md` |
| `ParseJob` | 实体 | `jobId` | 解析作业，见 `04-parser-sidecar.md` |
| `TranslationUnit` | 值对象 | `unitId`（`pa_*` 或 `s_*`） | 待译单元 |
| `Translation` | 实体 | `(docId, lang, unitId)` | 译文与其 `sourceHash` |
| `Glossary` / `GlossaryTerm` | 实体 / 值对象 | `glossaryId` / `(source)` | 术语表 |
| `Patch` | 实体 | `patchId` | 排版纠错补丁，见 `05-storage.md` §6 |
| `PatchOp` | 值对象 | — | `retype`/`move`/`merge`/`split`/`delete` |
| `OpLogEntry` | 实体 | `clientEventId` | 本地操作记录（撤销/审计） |
| `FetchRecord` | 值对象 | — | 一次 OA 获取尝试（见 `09-fetch-compliance.md` §6 审计） |

**ULID 生成**：统一用 `packages/core/src/util/id.ts` 的 `newId()`（时间有序、可注入时钟以满足确定性测试）。

---

## 2. 全局不变量

| ID | 不变量 | 校验点 |
|---|---|---|
| DM-1 | `LibraryEntry.citekey` 在库内唯一，且匹配 `^[a-z0-9][a-z0-9-]{0,39}$` | 导入/改名时 |
| DM-2 | `LibraryEntry.docId` 必须存在于 `document` 表或可由 `paper.pdf` 重算得到 | doctor `--verify-hashes` |
| DM-3 | `Annotation.anchor.sentenceId` 必须存在于对应 `DocAnchorModel.sentences` | 写入前校验；不存在则该标注标记 `orphan:true` 并保留（绝不丢弃） |
| DM-4 | 译文必须带 `sourceHash`，读取时若与当前源文本不符则视为未命中 | 翻译读取 |
| DM-5 | `Patch` 只叠加、不改写 `blocks.json` | 渲染时合成 |
| DM-6 | 任何写操作必须记录 `OpLogEntry`（可撤销） | 写路径装饰器 |
| DM-7 | `docId` 相同的文档，`blocks.json` 的 `engine.version` 与 `PARSER_RULES_REVISION` 必须匹配缓存键 | 打开文档时 |

---

## 3. 状态机

### 3.1 Document 生命周期

```
          import                parse(若未缓存)             open
(absent) ────────► indexed ──────────────────► ready ──────────────► reading
                     │                            ▲                    │
                     │ parse failed               │ close               │ close
                     ▼                            │                    ▼
                  failed ◄── retry ───────────────┘                 indexed
```

| 状态 | 含义 | UI 表现 |
|---|---|---|
| `indexed` | 已入库，尚未解析（或解析中） | 文献库卡片显示"待解析/解析中(x%)" |
| `ready` | `blocks.json` 就绪且通过 schema 校验 | 可进入重排模式 |
| `reading` | 有活动 `ReadingSession` | 阅读器 |
| `failed` | 解析失败（可重试） | 卡片显示错误徽标 + 重试按钮 |

### 3.2 ReadingSession

```
opening ──► ready ──► closing ──► closed
   │           │
   └─ 超时/错误 ─┴─► error（保留窗口，提示重试）
```

- `opening` 阶段允许先渲染原文模式（不等待锚点），锚点就绪后无缝切换；
- `closing` 必须**同步写入** `ReadingProgress`（这是"位置永不丢失"承诺的落点），失败时降级写入 `OpLogEntry` 并在下次启动补偿。

### 3.3 ParseJob

见 `04-parser-sidecar.md`（`queued → running → done | failed | canceled`）。领域层只暴露只读快照。

### 3.4 TranslationJob

```
idle ─► batching ─► requesting ─┬─► applied ─► idle
                      │  ▲      │
                   retry ┘      └─► failed(可重试) ─► idle
```

- 同一 `(docId, lang)` 同时只允许一个进行中的作业；新请求合并到当前批次；
- 取消时保留已完成单元的结果（部分成功可接受，但必须用 `partial:true` 标记）。

---

## 4. 领域事件

| 事件 | 载荷 | 触发者 | 订阅者 |
|---|---|---|---|
| `DocumentIndexed` | `{docId, citekey}` | LibraryService | 索引/UI |
| `ParseCompleted` | `{docId, engine, stats}` | ParserClient | UI、缓存 |
| `AnchorModelReplaced` | `{docId, cacheKey}` | AnchorStore | 阅读器（重渲染）、标注校验（DM-3） |
| `AnnotationChanged` | `{docId, annotationId, op}` | NoteService | UI、op_log |
| `ProgressChanged` | `{docId, sentenceId}` | NoteService | UI、同步(V2) |
| `TranslationApplied` | `{docId, lang, unitIds}` | TranslateService | UI |
| `PatchApplied` | `{docId, patchId}` | PatchService | 阅读器 |
| `NetBlocked` | `{url_host, reason}` | NetGuard | UI（合规提示）、审计 |

**事件规则**：领域事件是**纯数据**（可序列化）；不得携带类实例；订阅是同步的（UI 更新走 IPC 事件，见 `06-ipc-contract.md`）。

---

## 5. 领域服务（无状态，纯函数优先）

| 服务 | 职责 | 关键函数 |
|---|---|---|
| `AnchorBuilder` | 构建 `DocAnchorModel` | `buildDocAnchorModel(input): DocAnchorModel`（见 03 §6） |
| `SentenceSegmenter` | 句子切分 | `segment(blockText, protections): Sentence[]`（03 §6.5） |
| `PatchComposer` | 叠加补丁 | `compose(model, patches): DocAnchorModel` |
| `ProgressResolver` | 恢复阅读位置 | `resolve(progress, model): {sentenceId, rects}` |
| `GlossaryMatcher` | 术语命中 | `apply(text, glossary): {text, hits}` |
| `CacheKeyBuilder` | 缓存键 | `anchorKey(docId, engine, rulesRevision, schemaVersion)` |
| `MetaNormalizer` | 元数据归一化 | `normalize(doi|arxivId|title): Partial<Meta>` |

---

## 6. 与存储的映射

| 领域对象 | 持久化位置 |
|---|---|
| `Document` / `LibraryEntry` / `Meta` | `library/<citekey>/meta.json` + SQLite `document` |
| `DocAnchorModel` | `library/<citekey>/blocks.json` |
| `Annotation` | `library/<citekey>/annotations.jsonl` + SQLite `annotation` |
| `Translation` | `library/<citekey>/translation/<lang>.jsonl` + SQLite `translation_cache` |
| `Patch` | `library/<citekey>/patches/<patchId>.json` |
| `ReadingProgress` | `meta.json` 的 `reading` 节 + SQLite `document.read_progress`（可重建：以 meta.json 为准） |
| `OpLogEntry` | SQLite `op_log`（不落文件，属本机审计） |
| `Glossary` | `config.json` 引用的 `glossaries/*.tsv` 或内联 |

**真源规则**：文件为准，SQLite 可删可重建（`05-storage.md` §1）。

---

## 7. Agent 领域对象（V1）

> 详细契约见 `14-agent.md`；本节只定义领域层视角的实体与不变量，避免与 14 章重复。

| 名称 | 类型 | 标识 | 说明 |
|---|---|---|---|
| `Project` | 实体 | `projectId`（ULID） | Agent 的工作项目；拥有 `workspace/`、`permissions.json`、`skills/` 与若干会话 |
| `AgentSession` | 实体 | `sessionId`（ULID） | 一次可恢复的对话；事件流 append-only（`schemas/agent-session.schema.json`） |
| `Run` | 实体 | `runId`（ULID） | 会话内一次「模型↔工具」执行；受 `AGENT_BUDGETS` 约束 |
| `ToolCall` | 值对象 | `callId`（`call_*`） | 一次工具调用的请求/结果/耗时/授权决策 |
| `PermissionRule` | 值对象 | `(projectId, tool)` | `always` \| `once` \| `ask` \| `deny` |
| `Skill` | 实体 | `(projectId, name)` | 本地 `SKILL.md` 能力包 |
| `LlmProviderRef` | 值对象 | `(providerId, modelId)` | 模型引用；凭据存 OS Keychain，**不入领域模型** |

**领域不变量**（与 `14-agent.md` AG-1..AG-10 一一对应，此处只列领域层关心的三条）

| ID | 不变量 |
|---|---|
| DM-8 | 一个 `Project` 同时最多 1 个活动 `Run`（AG-1）；`Run` 终止后其 `once` 授权立即失效 |
| DM-9 | `AgentSession` 的事件 `seq` 严格递增且不重复；解析失败的行**不得**被丢弃，须标记为 `error` 事件后继续（AG-7） |
| DM-10 | `ToolCall` 必须同时存在 `tool_call` 与 `tool_result`（或 `error`）两条事件，否则会话被视为未完成，重开时提示可恢复（AG-2/AG-7） |

**`Run` 状态机**：见 `14-agent.md` §3.1（`planning → acting → observing` 循环，终止于 `finished|canceled|failed`；`ask_user`/权限询问进入 `waiting_user`）。

**领域事件（新增，经 IPC 转发见 `06-ipc-contract.md`）**

| 事件 | 载荷 | 订阅者 |
|---|---|---|
| `AgentSessionStarted` | `{projectId, sessionId, providerId}` | UI |
| `AgentToolExecuted` | `{sessionId, callId, tool, ok, durationMs}` | UI、审计 |
| `AgentPermissionDecided` | `{sessionId, callId, tool, decision}` | UI、`permissions.json` 写入 |
| `AgentRunFinished` | `{sessionId, runId, state, steps, toolCalls}` | UI |
| `ProjectChanged` | `{projectId, kind: 'files'\|'skills'\|'permissions'}` | UI（文件树刷新） |

**与存储的映射**

| 领域对象 | 持久化位置 |
|---|---|
| `Project` | `%APPDATA%/FreeRead/projects/<projectId>/project.json` |
| `AgentSession` / `Run` / `ToolCall` | `projects/<projectId>/sessions/<sessionId>.jsonl` + SQLite `op_log`（`op='agent.tool'`） |
| `PermissionRule` | `projects/<projectId>/permissions.json`（`schemas/agent-permissions.schema.json`） |
| `Skill` | `projects/<projectId>/skills/<name>/SKILL.md` |
| Agent 可读写文件 | `projects/<projectId>/workspace/**`（**唯一**可写目录，AG-3） |

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结 |
| v1.1 | 2026-10-03 | V1 纳入 Agent：新增 §7（Project/AgentSession/Run/ToolCall/PermissionRule/Skill）、DM-8..DM-10、5 个领域事件与存储映射 |
| v1.0 | 2026-10-03 | 首版冻结 |

| v1.2-M1 | 2026-10-03 | ADR-14：meta schema v2 持久化 reading，v1 校验迁移；M1 最小 PDF.js 锚点与 node:sqlite。preload 增加本地 PDF 选择对话框（只返回授权路径）；仅原文阅读，M2 再验收重排。 |
