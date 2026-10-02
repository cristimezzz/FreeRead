# FreeRead 技术规范（Specs）· 总览

> **本目录是 FreeRead 的唯一技术真源（Single Source of Truth）。**
> 面向两类读者：① 人类工程师；② AI 编码代理（vibe coding）。所有实现必须与规范一致；实现与规范冲突时，**先改规范（走 ADR）再改代码**。

- 版本：`spec-v1.0`（2026-10-03）
- 上游文档：[技术方案与里程碑](../plan/FreeRead-技术方案与里程碑.md) ｜ [Scholaread 调研报告](../report/Scholaread-调研报告.md)
- 主仓许可：**AGPL-3.0**（见方案 §12.1；引入依赖前必须过 License Gate）
- 实施记录（2026-10-03）：M0 工程骨架、离线空壳、三平台原生 CI 与首批样本已落地；实际证据及固定硬件基准缺口见 [M0 交付报告](../docs/m0-delivery.md)。任务认领与规范修订见 `13-task-template.md` §5、ADR-13，schema 未变更。

---

## 1. 给 AI 编码代理的使用协议（必读）

任何编码任务按以下顺序执行，**不得跳步**：

```
1. 读 ../AGENTS.md            —— 项目级硬规则（边界、禁止事项、DoD）
2. 读本文件 §3 词汇表         —— 术语与标识符必须与之一致
3. 读 specs/00-conventions.md —— 代码风格与提交规范
4. 读与本任务相关的规范文件（见 §2 索引）+ 相关 schemas/*.json
5. 认领任务卡（specs/13-task-template.md 的格式），确认 验收标准 可测
6. 实现 → 自测（单测必写）→ 运行 pnpm verify（typecheck+lint+test+boundaries+license）
7. 若发现规范缺失/歧义：先提交规范修订 PR（含 ADR 条目），再实现
```

**硬性禁止**（违反即为不合格实现，PR 会被拒）：

| # | 禁止 | 原因 |
|---|---|---|
| F1 | 在 `renderer` 中直接使用 `fs` / `net` / `child_process` | 模块边界（§4），必须走 IPC |
| F2 | 绕过 `NetGuard` 发起任何网络请求（含 `fetch`、`axios`、`net`） | 合规硬约束（`09-fetch-compliance.md`） |
| F3 | 出现任何 Sci-Hub / 付费墙绕过 / 机构代理相关代码或域名 | 合规红线，CI 有 grep 门禁 |
| F4 | `any` / `as any` / `@ts-ignore`（除非同文件注释说明并链接 issue） | 类型安全 |
| F5 | 静默 `catch {}`；错误必须转成 `AppError`（见 `11-error-handling.md`） | 可观测性 |
| F6 | 硬编码用户可见文案（必须走 i18n key） | 国际化 |
| F7 | 引入 License Gate 黑名单许可（`GPL-2.0-only`/SSPL/BUSL/Elastic/专有/CC-BY-NC 权重） | 许可合规 |
| F8 | 未写单测就提交 `packages/core`、`packages/render-reflow`、`services/parser` 的改动 | 质量门禁 |
| F9 | 修改 `specs/03-anchor-model.md` 或 `schemas/*.json` 而不 bump `schemaVersion` | 数据兼容 |

---

## 2. 规范索引

| 文件 | 内容 | 主要读者 | 状态 |
|---|---|---|---|
| `00-conventions.md` | 代码风格、命名、目录、提交、PR、DoD、质量门禁 | 全部 | 冻结 |
| `01-architecture.md` | 进程/模块/依赖方向、可机检的边界规则、启动时序 | 架构、全部 | 冻结 |
| `02-domain-model.md` | 领域实体、值对象、不变量、状态机 | 全部 | 冻结 |
| `03-anchor-model.md` | **锚点模型（核心）**：坐标、ID、构建算法、序列化、指标 | 全部 | 冻结 |
| `04-parser-sidecar.md` | 解析 sidecar 协议、任务生命周期、引擎适配、降级 | 解析/集成 | 冻结 |
| `05-storage.md` | 文件式知识库布局、SQLite DDL、迁移、doctor 修复 | 集成/平台 | 冻结 |
| `06-ipc-contract.md` | IPC 通道表、载荷类型、权限与校验 | 前后端 | 冻结 |
| `07-ui-spec.md` | 布局、组件树、交互、状态、键盘、无障碍、空态 | 前端 | 冻结 |
| `08-translation.md` | Provider 接口、提示词、术语表、缓存、降级 | AI/翻译 | 冻结 |
| `09-fetch-compliance.md` | NetGuard、OA 来源、审计、禁止清单 | 合规/集成 | 冻结 |
| `10-testing.md` | 单测/E2E/黄金集/性能门禁/指标卡 | 全部 | 冻结 |
| `11-error-handling.md` | 错误码表、用户文案映射、日志与脱敏 | 全部 | 冻结 |
| `12-build-release.md` | 构建、打包、签名、更新、许可合规产物 | 发布 | 冻结 |
| `13-task-template.md` | AI 任务卡模板 + 完成定义（DoD） | 全部 | 冻结 |
| `14-agent.md` | **Agent（V1 内置）**：14 个工具、4 级权限、项目工作区、会话事件流、技能、LlmProvider、15 通道 + 2 事件、12 条错误码 | 全部 | 冻结 |
| `schemas/*.json` | 机器可读契约（JSON Schema 2020-12），代码由 `pnpm gen` 生成 | 全部 | 冻结 |

**优先级（冲突时）**：`schemas/*.json` > `03-anchor-model.md` > 其余规范 > 实现习惯。

---

## 3. 冻结词汇表（Glossary）

> 标识符、文件名、IPC 通道、错误码一律以本表为准；新增术语必须更新本表。

| 术语 | 标识符（英文） | 定义 |
|---|---|---|
| 文档指纹 | `docId` | PDF 文件字节的 sha256（hex 小写，64 字符）。全系统文档主键 |
| 引用键 | `citekey` | 用户可读、唯一、可编辑的短标识（默认 `firstauthorYEARword`），用作知识库目录名 |
| 页面号 | `PageNo` | **1-based** 整数 |
| 矩形 | `Rect` | `{x,y,w,h}`，单位 **PDF point**，原点页面**左上角**，y 轴向下 |
| 版面区域 | `Block` | 版面模型识别出的语义区域（标题/正文/图表/公式…），带 `type`/`score`/`order` |
| 行引用 | `LineRef` | `{lineId,page,begin,len}`，指向 PDF.js 文本层的一行及其子串 |
| 句子 | `Sentence` | 由若干 `LineRef` 组成的语义最小单元，锚点系统的核心 |
| 段落 | `Paragraph` | 若干 `Block` + `Sentence` 的逻辑分组，翻译与重排的最小展示单元 |
| 锚点模型 | `DocAnchorModel` | 一篇文档的完整结构（blocks/paragraphs/sentences/outline/figures/references） |
| 标注 | `Annotation` | 用户产出的 highlight/note/bookmark/ink，**只引用 `sentenceId` + `rects`** |
| 纠错补丁 | `Patch` | 用户对区域类型/边界的修正，可重放 |
| 解析任务 | `ParseJob` | sidecar 内的一次解析作业（含进度、可取消） |
| 解析引擎 | `ParserEngine` | `docling` \| `marker` \| `grobid` \| `rule`（`rule` 为纯 JS 降级引擎） |
| 翻译单元 | `TranslationUnit` | `paragraph` 或 `sentence` 粒度的待译文本 |
| 术语 | `GlossaryTerm` | `{source,target,caseSensitive?}`，翻译时必须命中 |
| 出站守卫 | `NetGuard` | 唯一允许发起网络请求的模块，白名单 + 审计 |
| 获取器 | `FetchProvider` | OA 来源适配器（`arxiv`/`pmc`/`unpaywall`/`openalex`/`crossref`/`user-session`） |
| 操作日志 | `OpLogEntry` | 本地操作记录（`clientEventId` 主键），用于撤销与审计 |
| 项目工作区 | `Workspace` | **V1 内置** Agent 的项目目录（`%APPDATA%/FreeRead/projects/<projectId>/`），见 `14-agent.md` §7 |
| Agent 会话 | `AgentSession` | 一次可恢复的对话（`sessionId` = ULID），事件流 append-only，见 `14-agent.md` §8 |
| Agent 运行 | `Run` | 会话内一次「模型↔工具」执行（`runId`），受预算约束，见 `14-agent.md` §3 |
| 工具 | `AgentTool` | Agent 可调用的受限能力（V1 共 14 个），见 `14-agent.md` §4.1 |
| 权限规则 | `PermissionRule` | `always` \| `once` \| `ask` \| `deny`，见 `14-agent.md` §5 |
| 技能 | `Skill` | `SKILL.md` 约定的本地能力包（V1 仅本地安装），见 `14-agent.md` §9 |
| 重排 | reflow | 由 `DocAnchorModel` 渲染出的语义化 HTML 阅读视图 |
| 原文模式 | original | 直接渲染 PDF 的阅读视图 |

**命名规则**

| 类别 | 规则 | 示例 |
|---|---|---|
| 文件/目录 | `kebab-case` | `anchor-builder.ts`、`reader-view/` |
| React 组件文件 | `PascalCase.tsx` | `ReaderView.tsx` |
| Hooks | `use-*.ts`，导出 `useXxx` | `use-anchor-sync.ts` → `useAnchorSync` |
| 类型/接口 | `PascalCase`；后缀语义化 | `ParseOptions`、`ParseResult`、`TranslatorProvider` |
| 常量 | `UPPER_SNAKE_CASE` | `MAX_PAGE_COUNT` |
| ID 字符串 | 前缀 + `_` + 内容 | `b_3_7`（第3页第7块）、`s_b_3_7_2`（该块第2句）、`an_<ulid>`、`pa_3_7` |
| IPC 通道 | `fr:<domain>:<action>` | `fr:library:import`、`fr:parser:start` |
| 错误码 | `FR-<AREA>-<3位>` | `FR-PARSE-002` |
| i18n key | `<area>.<component>.<key>` | `reader.toolbar.translate` |
| CSS 类/变量 | 前缀 `fr-` / `--fr-` | `fr-reader-toolbar`、`--fr-font-size` |
| 事件（主→渲染） | `fr:<domain>:<event>` | `fr:parser:progress` |
| 日志字段 | `snake_case` | `doc_id`、`elapsed_ms` |

---

## 4. 模块边界（可机检，详见 `01-architecture.md`）

```
apps/desktop/src/renderer   →  仅可依赖 packages/ui、packages/core(纯类型)、IPC 客户端
apps/desktop/src/main       →  可依赖 packages/*、services/* 客户端
apps/cli                    →  可依赖 packages/*
packages/core               →  零依赖（除 zod/node 标准库），不得依赖 ui/react/electron
packages/render-reflow      →  仅依赖 packages/core（输出 HTML 字符串，不依赖框架）
packages/translate          →  packages/core + provider SDK
packages/fetch              →  packages/core + NetGuard
services/parser (Python)    →  仅通过 04 章协议与外界通信
```

**网格规则**：`renderer` 永不触碰文件系统与网络；`core` 永不引入 UI/Electron；`sidecar` 只输出 `DocAnchorModel`，**不得输出 HTML**（HTML 由 `render-reflow` 生成，保证可替换）。

---

## 5. 规范变更流程

1. 任何规范改动 → 新分支 + `spec:` 前缀提交 + 更新对应文件的「变更记录」小节；
2. 影响数据结构的改动 → **必须 bump `schemaVersion`** 并提供迁移函数（`05-storage.md` §迁移）；
3. 影响接口的改动 → 同步更新 `schemas/*.json` 与 `06-ipc-contract.md` 的通道表；
4. 重大取舍 → 追加 `docs/adr/ADR-xx-*.md`，并在本文件 §2 表内标记状态。

---

## 6. 机器可读契约一览

| Schema | 用途 | 生成物 |
|---|---|---|
| `schemas/doc-anchor-model.schema.json` | 锚点模型（`blocks.json`） | `packages/core/src/anchor.generated.ts` |
| `schemas/parse-request.schema.json` | sidecar 解析请求 | `packages/parser-protocol/src/generated/` |
| `schemas/parse-result.schema.json` | sidecar 解析结果/进度 | 同上 |
| `schemas/annotation.schema.json` | `annotations.jsonl` 单行 | `packages/core/src/annotation.generated.ts` |
| `schemas/agent-session.schema.json` | Agent 会话事件流单行 | `packages/core/src/agent/session.generated.ts` |
| `schemas/agent-permissions.schema.json` | `permissions.json` | `packages/core/src/agent/permissions.generated.ts` |
| `schemas/meta.schema.json` | `meta.json` | 同上 |
| `schemas/app-config.schema.json` | `config.json` | `apps/desktop/src/main/config.generated.ts` |
| `schemas/ipc-channels.json` | IPC 通道清单（单一真源） | preload 桥 + renderer 客户端类型 |

> 生成命令：`pnpm gen`（JSON Schema → TypeScript，使用 `json-schema-to-typescript`，MIT）。
> **禁止手改 `*.generated.ts`。**

---

## 7. 规范自检（可执行）

```bash
node specs/tools/check-specs.mjs
```

无第三方依赖，退出码 0 = 通过、1 = 存在失败项。检查项：

| ID | 检查内容 |
|---|---|
| C1 | README 索引中列出的规范文件是否都存在 |
| C2 | 每个规范文件是否含「变更记录」小节 |
| C3 | `schemas/*.json` 是否为合法 JSON 且含 `$schema`/`$id` |
| C4 | schema 内部 `#/$defs/...` 引用是否可解析 |
| C5 | 跨文件 `$ref`（`https://freeread.dev/schemas/*.json`）是否指向存在的文件 |
| C6 | `ipc-channels.json` 的通道命名是否满足 `fr:<domain>:<action>` 且唯一、`kind` 合法 |
| C7 | `ipc-channels.json` 与 `06-ipc-contract.md` 的通道清单是否**双向一致** |
| C8 | 规范中引用的每个错误码是否都在 `11-error-handling.md` 中定义 |
| C9 | 禁止域名是否只出现在 `09-fetch-compliance.md` 或门禁说明行 |
| C10 | 是否存在未被 README 索引的规范文件 |

> **规范变更后必须重跑本自检**；CI 的 `ci.yml` 将其作为独立步骤（`pnpm spec:check`）。
