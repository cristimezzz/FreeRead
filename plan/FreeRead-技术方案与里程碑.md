# FreeRead 技术方案与里程碑（可执行版）

> 版本：v1.1 ｜ 依据：[Scholaread 调研报告](../report/Scholaread-调研报告.md)（本机 cn-1.1.86 逆向 + 公开取证）
> 目标：把「本地优先的开源论文辅助阅读器」从选型落到**可开工、可验收**的粒度。
> 阅读指引：决策者看 §1/§2/§7；架构师看 §3/§4；工程负责人看 §5/§6/§8/§9；所有人先看 §0。

---

## 0. 一页结论

| 项 | 结论 |
|---|---|
| **产品定位** | **本地优先（Local-first）的论文精读工作台**：重排 + 对照翻译 + 笔记 + **内置研究 Agent（V1）**；**不做出处不明的全文获取**（只走 OA 与用户授权） |
| **技术栈** | **Electron + TypeScript + React + Vite**；解析用 **Docling(主) / Marker(备) / GROBID(元数据)** 以 **Python sidecar** 形式接入；渲染用 **PDF.js**；公式 **KaTeX**；存储 **SQLite(better-sqlite3) + 文件式知识库**；同步先 **WebDAV/Syncthing**，V2 再上 CRDT |
| **核心资产** | **锚点模型（Anchor Model）**：句子 ↔ PDF 行区间 ↔ 版面区域的稳定三重映射（照搬 Scholaread 已验证的思路，见 §4.1） |
| **许可策略** | 主仓 **AGPL-3.0**（已定，见 §12）；**可直接链接/复用 AGPL 与 GPLv3 组件**（Zotero、PyMuPDF、PDFMathTranslate、pdf2htmlEX 等）；CI 仍设 License Gate，但改为**黑名单**（SSPL/BUSL/专有/CC-BY-NC 权重/仅 GPL-2.0 的组件）+ **AGPL 源码义务提醒** |
| **MVP 范围** | M0–M4（约 **14 人周**）即可交付"能读、能译、能记、离线可用"的可用版本 |
| **完整 V1** | M0–M7（约 **25 人周**，2 人并行 ≈ **14–16 周**；含 V1 内置 Agent） |
| **最大技术风险** | 版面质量与锚点对齐精度 → 用 §6 的黄金集 + 指标卡门禁，并在 M2 设置"降级不失败"策略 |

---

## 1. 产品范围（V1 做什么 / 不做什么）

### 1.1 V1 必做（In Scope）

| # | 能力 | 对应 Scholaread 能力 | 我们的差异点 |
|---|---|---|---|
| 1 | 本地文献库（导入/文件夹/标签/全文检索） | 文献库 | 数据是磁盘上的普通文件，可 Git / 可同步盘 |
| 2 | 双模式阅读：**原文模式**（PDF.js）+ **重排模式**（语义 HTML） | 原文/重排 | 重排完全本地，无额度 |
| 3 | **对照翻译**（逐段/逐句/仅译文/划词），可接本地或自带 Key 的 LLM | 对照式翻译 | 无配额、可离线、可自定义术语表 |
| 4 | 笔记/高亮/阅读进度，**跨模式稳定** | 笔记与高亮 | 修复其被反复抱怨的"回到文章开头" |
| 5 | **排版纠错闭环**（标记错误区域 → 调整类型 → 重转 → 本地 patch） | 排版纠错 | patch 可导出/可社区收集 |
| 6 | OA 优先的文献获取与元数据补全 | 全网检索/一键保存 | 只走 arXiv/PMC/Unpaywall/OpenAlex + 用户会话 |
| 7 | Zotero **只读**导入 | Zotero 集成 | 不改写用户 Zotero 库 |

### 1.2 V1 明确不做（Out of Scope，写入 README 与 CI 检查）

- ❌ Sci-Hub / 机构代理绕过 / 任何形式的付费墙规避；
- ❌ 云端账号与云端主数据（V1 不设服务器）；
- ❌ 移动端、多人协同；
- ❌ 内置付费模型或额度体系。

### 1.3 V2 / V3 路线（预留接口，不在 V1 实现）

- **V2**：可选云同步（端到端加密）、CRDT 多端合并、**浏览器自动化（网页抓取型 Agent 工具）**、浏览器扩展、技能市场与远端技能分发、多 Agent 并行编排。
- **V3**：插件市场、团队/机构版（自托管同步服务）、Word/WPS 引用插件。

---

## 2. 技术选型决策（ADR）

> 每条决策含：**选择 / 理由 / 被否方案 / 风险**。许可均已按 [调研报告 §7.3](Scholaread-调研报告.md) 核验。

### ADR-01 应用形态：Electron + TypeScript ✅

| 维度 | 内容 |
|---|---|
| **选择** | Electron 3x + TypeScript 5.x + React 19 + Vite；`electron-builder` 打包，`electron-updater` 更新 |
| **理由** | ① 目标能力（多标签内嵌浏览器、屏幕截图 OCR、Pyodide 沙箱、本地 sidecar 管理）在 Electron 上最成熟；② PDF.js / KaTeX / Mermaid 生态都是 Web 技术；③ 与 Scholaread 同构，迁移与对标成本最低；④ 团队招聘面最广 |
| **被否** | **Tauri 2**：体积/内存更优，但多 WebView 管理、sidecar、跨平台 WebView 差异（WebView2/WebKit）会显著增加 V1 成本 → 列为 **V2 评估项**；**PyQt/Qt**：Web 渲染与前端生态劣势；**纯 Web PWA**：无法满足本地文件、离线解析、系统级截图 |
| **风险** | 安装包体积大（预计 150–250 MB，含 Python sidecar）→ 用 sidecar 按需下载（首次启用重排时下载）来规避 |

### ADR-02 前端框架：React ✅（可低成本换 Vue）

- **选择**：React 19 + Vite + Zustand（轻量状态） + TanStack Query（数据获取） + Tailwind CSS。
- **理由**：PDF 标注/虚拟列表/拖拽类库最丰富；Zustand 比 Redux 更适合"文档级多实例状态"。
- **被否**：Vue 3（Scholaread 同款，若团队更熟悉可直接换，仅影响 UI 层，不影响 §3.3 接口）。
- **风险**：无。

### ADR-03 PDF 渲染：PDF.js ✅

- **选择**：`pdfjs-dist`（**Apache-2.0**），自建 viewer 而非直接用其 demo viewer。
- **理由**：事实标准、许可宽松、可按页取文本层与坐标（`getTextContent()` 提供我们需要构建锚点的行盒）。
- **被否**：PDFium/WASM（集成复杂、坐标 API 不如 PDF.js 友好）；**PyMuPDF**（AGPL——在新许可下**可用**，但 V1 仍优先 PDF.js：其 `getTextContent()` 的行盒与坐标更贴合锚点构建；PyMuPDF 留作 sidecar 内的解析加速备选）。
- **风险**：大文档内存 → 采用"按页懒渲染 + 位图 LRU 缓存"（见 §6 性能门禁）。

### ADR-04 版面解析：Docling(主) + Marker(备) + GROBID(元数据)，Python sidecar ✅

| 维度 | 内容 |
|---|---|
| **选择** | 独立 **Python 3.11 sidecar 进程**（`python -m freeread_parser`），通过 **本地 HTTP/JSON-RPC** 暴露 `parse()`；主进程管理其生命周期；**必带纯规则降级路径**（PDF.js 文本行聚类 + XY-Cut） |
| **理由** | ① Docling **MIT**、Marker **Apache**、GROBID **Apache** 的功能/中文覆盖最佳（许可已无约束，主仓为 AGPL-3.0，与 MIT/Apache 单向兼容）；② Python 是这三个项目的原生语言，重写代价极高；③ sidecar 进程用于**隔离模型崩溃与内存峰值**、支持热替换引擎，并让用户可外挂 MinerU/PyMuPDF/PDFMathTranslate 等更重的组件而不影响主进程稳定性 |
| **被否** | 全 ONNX 端侧重写（工期 ×3，且中文表格效果差）；直接内置 pdf2htmlEX（GPLv3 **现已兼容**，但项目自 2020 年起停更、输出为绝对定位 HTML，不适合做语义重排的**主**引擎，仅作参考实现） |
| **风险** | sidecar 体积与启动延迟 → 冷启动预算 ≤ 1.5 s、模型懒加载；无 Python 环境时**自动降级**到规则解析并在 UI 明示"当前为快速模式" |

**Sidecar 协议（冻结版，V1 不再改）**

```
POST http://127.0.0.1:<random-port>/v1/parse
{ "docId": "...", "pdfPath": "...", "options": { "engine": "docling|marker|rule", "ocr": true, "lang": ["en","zh"] } }
→ 202 { "jobId": "..." }
GET /v1/jobs/<jobId>            → { "state": "running|done|failed", "progress": 0.0-1.0, "model": DocAnchorModel|null, "error": null }
POST /v1/cancel/<jobId>
GET  /v1/health                 → { "ok": true, "engines": ["docling","marker","rule"], "version": "..." }
```

### ADR-05 图像渲染与原文层：自建"像素对齐层" ✅

- **选择**：重排页背景 = 该页位图（PNG，`dpi=110`，与 Scholaread 的 `bgN.png` 同思路），用于"原文对照/高亮落框"；大图（jpg）按需生成。
- **理由**：高亮/边注需要"区域框落在可见像素上"，纯 DOM 无法保证；这也是 Scholaread 的做法。
- **风险**：磁盘占用 → 采用 **WebP** + 按页 LRU 清理（默认保留最近 30 天/500 MB）。

### ADR-06 OCR：PaddleOCR(中文优先) / Tesseract(轻量兜底) ✅

- **选择**：默认 **PaddleOCR (Apache-2.0)**（sidecar 内）；无 OCR 需求或资源受限时用 **Tesseract (Apache-2.0)**。
- **理由**：Scholaread 用 Tesseract，其中文效果一般；PaddleOCR 在中文扫描件上明显更好且许可宽松。
- **风险**：模型下载体积 → 首次启用时下载并校验 SHA256。

### ADR-07 公式与图表：KaTeX + Mermaid ✅

- **选择**：`katex`（MIT）渲染行内/行间公式；`mermaid`（MIT）渲染流程图/时序图（用于笔记与 AI 回答）。
- **被否**：MathJax（体积大、首屏慢）；自研渲染（无必要）。

### ADR-08 存储：SQLite 索引 + 文件式知识库 ✅

- **选择**：`better-sqlite3`（MIT）存索引/笔记/事件；**真源是磁盘上的文件**（见 §3.4）。
- **理由**：可 Git、可 diff、可被其他工具消费；SQLite 只做加速与 FTS5 全文检索。
- **风险**：文件与索引不一致 → 提供 `freeread doctor` 重建索引命令；所有写操作走"先写文件再更新索引"。

### ADR-09 同步：WebDAV/Syncthing（V1） → CRDT（V2） ✅

- **选择**：V1 通过同步盘解决多端（用户自选），应用内只做**冲突检测**（文件级 mtime+hash）；V2 引入 **Yjs/Automerge（MIT）** 做笔记 CRDT 合并。
- **被否**：自建服务器同步（V1 不设服务器）；直接照搬 Scholaread 的事件溯源同步（其复杂度只为云端多端服务，本地优先场景收益低）——但**保留其 `client_event_id` 思路用于"操作日志/撤销"**。

### ADR-10 翻译与 LLM：Provider 抽象 + 本地优先 ✅

- **选择**：统一 `TranslatorProvider` / `LlmProvider` 接口，内置实现：
  1. **Ollama**（MIT，本地，默认推荐，零成本零上传）；
  2. **OpenAI 兼容 HTTP**（用户自带 baseURL + key，覆盖 OpenAI/DeepSeek/通义/Kimi/本地 vLLM）；
  3. **无模型时的降级**：仅提供"原文 + 词典式划词"（内置 ECDICT 词库，MIT/CC），保证核心阅读不空洞。
- **理由**：这是与 Scholaread（纯云端、配额制）形成差异的关键；且避免我们承担模型成本与合规责任。
- **被否**：内置免费翻译 API 池（不稳定、违反 ToS）；自建模型网关（V1 无服务器）。
- **风险**：本地模型质量参差 → 在 UI 中提供"术语表 + 译文二次编辑 + 一键切换 Provider"。

### ADR-11 Agent：**V1 内置**（2026-10-03 决策，取代原「V2 才做」）✅

- **选择**：V1 交付**本地优先的研究 Agent** —— 14 个工具、4 级权限（`always/once/ask/deny`）、项目工作区、append-only 会话事件流、本地技能安装；模型走本地 Ollama 或用户自带 Key。
- **理由**：① 决策者确认 V1 必须包含 Agent；② 其依赖的文档模型（锚点）、存储（§3.4）、IPC 契约在 M1–M5 即已冻结，M6 可以并行推进；③ LLM 与工具面完全可插拔，不与核心阅读体验耦合（失败时降级不影响阅读）。
- **边界（V1 明确不做）**：❌ 浏览器自动化 / 网页抓取工具；❌ 云端会话同步；❌ 远端技能下载（供应链风险）；❌ 多 Agent 并行编排。均延至 V2 评估。
- **风险与缓解**：Agent 的越权与提示注入是主要风险 → 三面受限能力模型（文献库只读 / 工作区读写 / NetGuard 白名单）、工具级权限门禁、全量审计（AG-2/AG-3/AG-8）、注入防护（`14-agent.md` §6.3）。
- **被否**：仅做「接口预留」（决策者要求 V1 可用）；把浏览器自动化一并纳入 V1（合规面与工期均不可接受）。
- **规范**：`specs/14-agent.md`（权威）、`specs/schemas/agent-session.schema.json`、`specs/schemas/agent-permissions.schema.json`。

### ADR-12 工程与发布 ✅

| 项 | 选择 | 许可 |
|---|---|---|
| 包管理与 monorepo | pnpm workspaces + Turborepo | MIT |
| 测试 | Vitest（单测）+ Playwright（Electron E2E） | MIT / Apache |
| 代码规范 | ESLint + Prettier + TypeScript strict + `eslint-plugin-boundaries`（模块边界） | MIT |
| 打包 | electron-builder（NSIS / dmg / deb / AppImage） | MIT |
| 自动更新 | electron-updater（**仅签名包**；更新源可配置） | MIT |
| 崩溃上报 | **默认关闭**；启用时用 Sentry 自托管或完全关闭（隐私优先） | MIT（自托管） |
| CI | GitHub Actions：typecheck / test / e2e / **License Gate** / 打包 | — |
| **License Gate** | `license-checker-rsc` + **黑名单**：`SSPL`、`BUSL-1.1`、`Elastic-2.0`、`GPL-2.0-only`（与 AGPLv3 不兼容）、任何 `UNLICENSED`/专有依赖、以及 **CC-BY-NC 类模型权重**（如 Nougat 权重）一律 fail；AGPL/GPLv3/MIT/Apache 允许。同时生成 `THIRD_PARTY_NOTICES.md` 与 `SOURCE_OFFER.md`（AGPL 源码义务） | — |

---

## 3. 系统架构

### 3.1 进程与模块图

```
┌──────────────────────────── Electron 桌面端 ────────────────────────────┐
│ main 进程                                                                │
│  ├ 窗口与视图：library / reader(原文|重排) / agent / project / settings │
│  ├ LibraryService      文献库 CRUD、导入、去重(hash)、索引重建            │
│  ├ ParserClient        sidecar 生命周期 + 任务队列 + 断点续转            │
│  ├ AnchorStore         锚点模型读写（anchors.json + SQLite 索引）        │
│  ├ NoteService         笔记/高亮/进度（唯一写入者，跨模式锚定）           │
│  ├ TranslateService    Provider 调度、术语表、段落级缓存(SQLite)         │
│  ├ FetchService        OA 获取（arXiv/PMC/Unpaywall/OpenAlex）+ 用户会话 │
│  └ NetGuard            出站域名白名单 + 审计日志（合规硬约束）            │
│                                                                          │
│ renderer                                                                 │
│  ├ 原文视图   PDF.js（自建 viewer，暴露行盒与选中）                      │
│  ├ 重排视图   语义 HTML + 段落/句子 DOM（携带 data-anchor-*）            │
│  └ 共用的锚点总线 AnchorBus（选中/高亮/滚动/翻译 → 双向映射）            │
└──────────────────────────────────────────────────────────────────────────┘
            │ localhost HTTP(JSON-RPC)          │ HTTPS(白名单)
            ▼                                   ▼
   Python sidecar (Docling/Marker/GROBID/OCR)   OA 数据源（arXiv/PMC/Crossref/
   + 模型缓存目录                                Unpaywall/OpenAlex/Zotero 只读）
```

**模块边界硬约束**（由 `eslint-plugin-boundaries` 强制）：
`core` 不得依赖 `ui`；`ui` 不得直接访问文件系统或网络（只能通过 IPC 契约）；`parser` 只输出 `DocAnchorModel`，不得输出 HTML。

### 3.2 仓库结构（monorepo）

```
freeread/
├─ apps/
│  ├─ desktop/                  # Electron 主进程 + 渲染进程（React）
│  │  ├─ src/main/              # LibraryService / ParserClient / NoteService ...
│  │  ├─ src/renderer/          # 阅读器 UI（原文视图 / 重排视图 / 侧栏）
│  │  └─ src/preload/           # 最小化 IPC 桥（白名单式）
│  └─ cli/                      # freeread doctor / freeread import（无头运维）
├─ packages/
│  ├─ core/                     # 纯逻辑：锚点模型、文档模型、事件、全文检索
│  ├─ parser-protocol/          # sidecar 协议类型 + 客户端（与 Python 端共享 JSON Schema）
│  ├─ render-reflow/            # DocAnchorModel → 语义 HTML 的渲染器（无框架依赖）
│  ├─ translate/                # TranslatorProvider 实现（ollama / openai-compatible / 降级）
│  ├─ fetch/                    # OA 获取器（arXiv / PMC / Unpaywall / OpenAlex）
│  ├─ zotero/                   # Zotero 只读适配器（sqlite 只读副本 + 字段映射）
│  └─ ui/                       # 设计系统（组件库）
├─ services/
│  └─ parser/                   # Python sidecar（Docling / Marker / GROBID / PaddleOCR）
│     ├─ freeread_parser/       # 引擎适配、任务队列、坐标归一化
│     ├─ schemas/               # 与 packages/parser-protocol 共享的 JSON Schema（单一真源）
│     └─ pyproject.toml
├─ plugins/                     # 官方插件示例（V2 插件 API 先行验证）
├─ fixtures/                    # 黄金集：50 篇 PDF（OA 授权）+ 期望锚点/版面标注
├─ docs/
│  ├─ adr/                      # 本方案 §2 的逐条 ADR（每个决策一个文件）
│  ├─ anchor-model.md           # 锚点模型规范（§4.1 的正式版）
│  └─ plugin-api.md
└─ .github/workflows/           # ci.yml / license.yml / release.yml
```

### 3.3 核心接口（TypeScript 定义，冻结后 V1 只允许向后兼容扩展）

```ts
// packages/core/src/anchor.ts —— 全文最重要的一组类型
export type PageNo = number;                    // 1-based
export interface Rect { x: number; y: number; w: number; h: number }  // PDF pt, 原点左上

export type BlockType =
  | 'title' | 'author' | 'abstract' | 'heading' | 'text'
  | 'figure' | 'figure_caption' | 'table' | 'table_caption'
  | 'formula' | 'inline_formula' | 'reference' | 'aside' | 'abandon';

export interface Block {
  id: string;            // 稳定 id：`b_${page}_${seq}`
  page: PageNo;
  rect: Rect;
  type: BlockType;
  score: number;         // 0..1 置信度；< 0.6 在 UI 中标记为"低置信，可纠错"
  order: number;         // 阅读顺序
  text?: string;
}

/** 句子 → 原始 PDF 行区间（对齐翻译与高亮的基石） */
export interface LineRef { lineId: number; page: PageNo; begin: number; len: number }

export interface Sentence {
  id: string;            // `s_${blockId}_${seq}`
  blockId: string;
  page: PageNo;
  text: string;
  lines: LineRef[];      // 对应 PDF.js textContent 的行对象
}

export interface Paragraph { id: string; blockIds: string[]; sentenceIds: string[] }

export interface DocAnchorModel {
  schemaVersion: 1;
  docId: string;                                   // = sha256(pdf)
  engine: { name: 'docling' | 'marker' | 'rule'; version: string };
  pageSize: Record<PageNo, { w: number; h: number }>;
  blocks: Block[];
  paragraphs: Paragraph[];
  sentences: Sentence[];
  outline: { title: string; page: PageNo; blockId: string; level: number }[];
  figures: { tag: string; page: PageNo; blockId: string; caption?: string }[];
  references: { tag: string; page: PageNo; text: string; doi?: string }[];
}

// packages/parser-protocol/src/provider.ts
export interface ParserProvider {
  readonly id: string;
  readonly version: string;
  health(): Promise<{ ok: boolean; engines: string[] }>;
  parse(pdfPath: string, opts: ParseOptions, onProgress?: (p: number) => void): Promise<DocAnchorModel>;
}

// packages/translate/src/provider.ts
export interface GlossaryTerm { source: string; target: string; caseSensitive?: boolean }
export interface TranslateRequest {
  texts: string[]; from?: string; to: string; glossary?: GlossaryTerm[];
  context?: { docTitle?: string; field?: string };   // 供模型消歧
}
export interface TranslatorProvider {
  readonly id: string;
  readonly kind: 'local' | 'remote';
  translate(req: TranslateRequest, signal: AbortSignal): Promise<string[]>;
}

// packages/core/src/plugin.ts（V2 插件 API 的 V1 骨架）
export interface FreeReadPlugin {
  id: string; name: string; version: string;
  activate(ctx: PluginContext): void | Promise<void>;
}
export interface PluginContext {
  registerParser(p: ParserProvider): void;
  registerTranslator(t: TranslatorProvider): void;
  registerReaderPanel(panel: { id: string; title: string; render(host: HTMLElement, doc: DocAnchorModel): void }): void;
  readonly log: (msg: string) => void;
}
```

### 3.4 数据模型

**A. 文件式知识库（真源）**

```
~/FreeRead/library/<citekey>/
├─ paper.pdf                # 原始文件（只读，不修改）
├─ meta.json                # title/authors/year/doi/venue/abstract/tags/addedAt
├─ blocks.json              # DocAnchorModel（§3.3）
├─ notes.md                 # 用户笔记（Markdown，人可读）
├─ annotations.jsonl        # 一行一条标注（追加写，便于冲突合并）
├─ translation/<lang>.jsonl # 段落级译文缓存（可删可重建）
└─ patches/                 # 排版纠错结果（区域修正 patch）
```

`annotations.jsonl` 单条结构（锚点必须可跨模式还原）：

```json
{"id":"an_01H...","kind":"highlight","anchor":{"page":3,"blockId":"b_3_7","sentenceId":"s_b_3_7_2",
 "rects":[{"x":72.1,"y":301.4,"w":210.3,"h":11.8}],"lines":[{"lineId":15,"page":3,"begin":0,"len":3}]},
 "color":"yellow","createdAt":"2026-10-03T00:00:00Z","deviceId":"dev_..."}
```

**B. SQLite 索引（可重建，`freeread doctor --rebuild`）**

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE document (
  doc_id      TEXT PRIMARY KEY,       -- sha256(pdf)
  citekey     TEXT UNIQUE NOT NULL,
  title TEXT, authors TEXT, year INTEGER, doi TEXT, venue TEXT,
  page_count  INTEGER, parser_engine TEXT, parser_version TEXT,
  added_at    INTEGER, updated_at INTEGER, read_state TEXT, read_progress REAL
);

CREATE TABLE annotation (            -- 与 annotations.jsonl 同步（文件为真源）
  id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, kind TEXT NOT NULL,
  page INTEGER, block_id TEXT, sentence_id TEXT,
  json TEXT NOT NULL, created_at INTEGER, updated_at INTEGER, deleted INTEGER DEFAULT 0
);

CREATE TABLE op_log (                -- 借鉴 Scholaread 的 client_event_id 思路（撤销/审计）
  client_event_id TEXT PRIMARY KEY, doc_id TEXT, op TEXT, payload TEXT,
  device_id TEXT, at INTEGER, synced INTEGER DEFAULT 0
);

CREATE TABLE translation_cache (
  doc_id TEXT, lang TEXT, paragraph_id TEXT, source_hash TEXT, target TEXT,
  provider TEXT, created_at INTEGER, PRIMARY KEY (doc_id, lang, paragraph_id)
);

CREATE VIRTUAL TABLE doc_fts USING fts5(title, abstract, body, content='', tokenize='unicode61');
```

**C. 目录约定**

```
%APPDATA%/FreeRead/            (或 ~/.config/FreeRead)
├─ config.json                 # 设置（不含任何云端凭据；本地 Provider 的 key 存 OS Keychain）
├─ index.sqlite
├─ cache/{pages,translation,ocr}   # 可清理缓存（有独立容量上限）
└─ logs/                       # 轮转日志；默认不开启崩溃上报
```

---

## 4. 关键设计（直接承接调研结论）

### 4.1 锚点模型：为什么是它、怎么落地

**问题**：重排后的句子与 PDF 原始行必须能互相定位，否则高亮、笔记、翻译对齐、进度恢复全部会错位——这正是 Scholaread 被用户抱怨「每次打开回到文章开头」的根因所在。

**设计**（三步，全部本地）：

1. **建锚**：PDF.js `getTextContent()` 给出行盒与 `lineId`；解析器给出版面块；用"行盒 → 块"的包含/重叠判定建立 `Block → LineRef[]`。
2. **切句**：在块内做句子切分（`Intl.Segmenter` + 学术缩写例外表），产出 `Sentence.lines`，即"这句由第几页哪几行的哪一段构成"。
3. **渲染与回写**：重排 HTML 上每个句子节点带 `data-sentence-id` / `data-block-id`；原文视图的选区通过 `lineId` 反查句子。**所有标注只存 `sentenceId + rects`**，两个视图各自用同一份锚点还原。

**质量门禁**：黄金集上"句子 ↔ 行区间"字符级 IoU ≥ **0.98**；不达标不允许进入 M3（见 §6）。

### 4.2 双模式渲染

- **原文模式**：PDF.js 画布 + 文本层 + 位图背景；标注框按 `rects` 绝对定位。
- **重排模式**：`packages/render-reflow` 把 `DocAnchorModel` 渲染成语义 HTML（`article > section > h2 > p > span[data-sentence-id]`），CSS 变量控制字号/行距/字体/主题；译文以**段落或句子为粒度**插入到同段落内的 `<span class="translation">`，天然保证对照不串行。
- **切换**：切换时以"当前视口内的第一个 `sentenceId`"为同步点，双向跳转误差 ≤ 1 段。

### 4.3 排版纠错闭环（差异化能力）

- UI：`低置信区域`（`score < 0.6`）自动描边 → 用户可「改类型 / 合并 / 拆分 / 删除 / 调序」→ 保存为 `patches/<blockId>.json`；
- 生效：本地**立即重渲染**（不重跑模型）；
- 沉淀：`freeread export-patch` 导出为标准化 JSON（含引擎版本与页面指纹），社区可汇总用于评测集与规则迭代——**这是开源项目相对闭源产品的结构性优势**。

### 4.4 合规内建（NetGuard）

- 出站请求必须命中白名单：`arxiv.org`、`ncbi.nlm.nih.gov`、`api.crossref.org`、`api.openalex.org`、`api.unpaywall.org`、`cdn.jsdelivr.net`（模型/词库）、用户显式配置的 LLM endpoint；
- **任何 `sci-hub` / 代理站域名在代码层不存在**（CI 加一条 grep 门禁，防止未来误引入）；
- 用户手动用内嵌浏览器访问出版商站点时，只使用**用户自己的会话**，且默认不落盘、不上传；NetGuard 会记录审计日志（本地可查）。

---

## 5. 里程碑（M0–M7）

> 工时单位：**人周**（1 人周 ≈ 5 个工作日）。并行建议见 §8。
> 每个里程碑都有**可测验收标准**，不达标不进入下一个（Gate）。

| 里程碑 | 目标 | 主要交付物 | 验收标准（Gate） | 人周 | 依赖 |
|---|---|---|---|---|---|
| **M0** 骨架 | 工程可跑、可发版 | monorepo、CI（typecheck/test/e2e/license）、Electron 空壳可打包、ADR 落档、`fixtures/` 首批 10 篇 | `pnpm build` 产出三平台安装包；CI 全绿；License Gate 能拦住一个故意引入的 AGPL 依赖 | 1.5 | — |
| **M1** 阅读内核 | 能读、能管、能记 | 文献库（导入/去重/标签/FTS5 检索）、PDF.js 原文视图、标注与笔记、进度恢复 | ① 1000 页 PDF 首屏 ≤ 3 s；② 滚动 ≥ 55 fps；③ **杀进程重开，阅读位置精确恢复到上次句子（20/20 次）** | 3.5 | M0 |
| **M2** 锚点与解析 | 得到可信的 `DocAnchorModel` | Python sidecar（Docling 主 / 规则降级）、锚点构建器、坐标归一化、黄金集 50 篇与评测脚本 | ① 黄金集版面块 F1 ≥ 0.90；② 句子↔行 IoU ≥ 0.98；③ 无 Python 环境时自动降级且不崩（规则路径 F1 ≥ 0.75） | 4.0 | M1 |
| **M3** 重排阅读 | 双模式可切换、可纠错 | `render-reflow`、重排视图、低置信描边与纠错 UI、patch 存取与重渲染 | ① 50 篇黄金集重排后**无内容丢失**（块覆盖率 100%）与无重叠溢出；② 切换模式前后定位误差 ≤ 1 段；③ 纠错 patch 可保存、可重放 | 3.0 | M2 |
| **M4** 对照翻译 | 可离线/自带 Key 的对照翻译 | TranslatorProvider（Ollama / OpenAI 兼容 / 降级词典）、段落与句子级对照渲染、术语表、翻译缓存 | ① 1000 词段落批量翻译端到端 ≤ 8 s（本地 7B 模型，草稿机）；② 术语表命中词 100% 按术语输出；③ 公式与引用角标不被破坏（黄金集 50/50） | 3.0 | M3 |
| **M5** 获取与集成 | OA 优先的获取 + Zotero 只读 | FetchService（arXiv/PMC/Unpaywall/OpenAlex）、元数据补全、Zotero 只读导入、浏览器导入（可选扩展） | ① 给定 50 个 DOI，OA 全自动获取成功率 ≥ 70%（其余给出"需用户会话"提示，绝不绕过）；② Zotero 1000 条导入 ≤ 30 s 且**不写用户库**（校验 mtime/hash 不变） | 3.0 | M1 |
| **M6** Agent（**V1 交付**） | 可审计的本地研究 Agent | 项目工作区、会话事件流、14 个工具、4 级权限门禁与 UI、技能本地安装、LlmProvider（Ollama / OpenAI 兼容）、审计与 `14-agent.md` §14 测试 | ① 越权文件访问与越界网络 100% 被拦（`FR-AGT-008`）；② 每次工具调用可审计（含 argsHash/摘要/耗时/授权决策）；③ 权限 `deny` 为终态且不再询问；④ 取消 run 保留产出；⑤ 断网/无 Provider 时核心阅读功能零降级 | 4.0 | M4、M5 |
| **M7** 发布与生态 | 可交付、可扩展 | 三平台签名安装包与自动更新、插件 API 1.0 与 2 个示例插件、文档与官网、`THIRD_PARTY_NOTICES` | ① 三平台安装→首启→读一篇论文全流程 E2E 通过；② 插件沙箱越权测试通过；③ 许可清单人工复核通过 | 3.0 | M6 |

**合计 25 人周**；**双人并行**（A：解析/渲染/翻译；B：阅读器/库/集成/工程）预计 **14–15 周**。

### 5.1 里程碑拆解示例（M2 的周级任务）

| 周 | 任务 | 产出 | 验收 |
|---|---|---|---|
| M2-W1 | sidecar 骨架、协议实现、健康检查、生命周期管理 | `services/parser` 可独立起停；`ParserClient` 单测 | 灌入 5 篇 PDF 得到合法 JSON |
| M2-W2 | Docling 适配 + 坐标归一化（不同 dpi → PDF pt） | `blocks.json` 与页面坐标一致 | 10 篇目视 + 单测：块框落在页面内且顺序正确 |
| M2-W3 | 锚点构建器（行盒→块→句子）与评测脚本 | `anchor-metrics` CLI | 黄金集 IoU 报告可复现 |
| M2-W4 | 规则降级路径（XY-Cut）+ 黄金集扩到 50 篇 + 调参 | 达标报告 | **Gate：F1 ≥ 0.90 且 IoU ≥ 0.98** |

---

## 6. 质量与评测体系（Gate 的依据）

### 6.1 黄金集（`fixtures/`）

| 子集 | 数量 | 覆盖 |
|---|---|---|
| 双栏正文 | 15 | 典型 arXiv/ACM 模板 |
| 公式密集 | 10 | LaTeX 公式、行内公式、多行公式 |
| 表格/图注 | 10 | 三线表、跨页表、图注分段 |
| 扫描件/影印版 | 8 | 低质量扫描、中文竖排混排 |
| 中文期刊（CAJ 转换后） | 7 | 知网样式（**仅使用作者授权/自备样本**） |
| **合计** | **50** | 全部具备可再分发的授权或为合成样本 |

> 标注规范：每篇人工标注 `blocks`（类型 + 框）与 20 个句子的 `lines` 映射，作为评测真值。

### 6.2 指标卡门禁（CI 每次 PR 跑小集，每夜跑全集）

| 指标 | 阈值 | 门禁级别 |
|---|---|---|
| 块结构 F1 | ≥ 0.90 | P0（阻断） |
| 句子↔行 IoU | ≥ 0.98 | P0 |
| 块覆盖率（重排无丢内容） | 100% | P0 |
| 公式保护率 | ≥ 99% | P0 |
| 首屏渲染（1000 页） | ≤ 3.0 s | P1 |
| 滚动帧率 | ≥ 55 fps | P1 |
| 阅读位置恢复准确率 | 100%（20/20） | P0 |
| 内存峰值（打开 5 篇） | ≤ 1.2 GB | P1 |
| 冷启动（含 sidecar 健康检查） | ≤ 2.5 s | P2 |

### 6.3 许可合规 CI

```yaml
# .github/workflows/license.yml（要点，主仓 AGPL-3.0）
- run: pnpm license-checker-rsc --production --failOn "SSPL-1.0;BUSL-1.1;Elastic-2.0;GPL-2.0-only;UNLICENSED"
- run: pnpm tsx scripts/gen-third-party-notices.ts      # 生成 THIRD_PARTY_NOTICES.md
- run: python services/parser/scripts/check_licenses.py # sidecar 依赖黑名单（含模型权重许可）
- run: bash scripts/forbid-domains.sh                   # grep 禁用域名（sci-hub 等）
- run: bash scripts/check-agpl-obligations.sh           # 校验：源码可见性声明、修改文件标注、NOTICE 完整性
```

---

## 7. 风险登记册

| # | 风险 | 概率 | 影响 | 缓解措施 | 触发条件（早停信号） |
|---|---|---|---|---|---|
| R1 | 版面解析质量不达标（双栏/公式/表格） | 中 | 高 | 主备双引擎 + 规则降级；`score` 显式暴露；纠错闭环收集真实修正 | M2 Gate 两次未过 → 缩小 V1 重排到"单栏 + 摘要 + 参考文献" |
| R2 | sidecar 体积/启动/兼容（Python 环境缺失） | 高 | 中 | 规则路径保底；sidecar 按需下载；健康检查超时即降级 | 冷启动 > 3 s → 改懒加载 + 预启动 |
| R3 | **AGPL 合规义务被忽视**（主仓为 AGPL-3.0） | 中 | 中 | ① 每个发布包必须附完整对应源码（含 sidecar 依赖的源码获取方式）；② 修改过的第三方文件需显著标注；③ 若未来提供**网络服务**（云同步/在线解析），必须向服务使用者提供源码；④ CI 增加 `check-agpl-obligations.sh`；⑤ 对外文档明确"AGPL-3.0，可自托管、可商用但须开源衍生" | 任一发布产物缺少源码或 NOTICE → 阻断发布 |
| R4 | 本地 LLM 质量差导致翻译口碑崩 | 中 | 中 | Provider 可切换 + 术语表 + 译文可编辑；内置词典降级 | 用户测试满意度 < 3/5 → 默认改为"自带 Key"引导 |
| R5 | 合规越界（获取链路被曲解为绕过） | 低 | 极高 | NetGuard 白名单 + 代码层无 Sci-Hub + README 明确声明 + 审计日志 | 任何 PR 触及付费墙 → 立即回滚并复核 |
| R6 | 锚点一致性回归（跨模式错位） | 中 | 高 | P0 门禁（IoU/恢复率）+ 合成回归用例 | 夜间全集 IoU 下降 > 0.5% → 阻断合并 |
| R7 | 单人依赖（bus factor） | 中 | 中 | 每个模块必须有 ADR + 评测脚本；文档即交付物 | 任一模块无第二作者 → 排期插入结对 |

---

## 8. 团队配置与并行策略

**推荐 2 人（MVP）**

- **A｜文档智能**：§2 ADR-04/05/06 + M2 + M3（解析、锚点、重排、纠错）+ §6 评测体系；
- **B｜应用与集成**：M0 + M1 + M4 + M5（工程、阅读器、翻译 Provider、获取与 Zotero）。

**推荐 4 人（完整 V1）**

- A：解析与锚点（M2）；B：渲染与交互（M1 + M3）；C：翻译与 Provider（M4）；D：工程/集成/发布（M0 + M5 + M7）；M6 由 A+D 在 V2 启动时共同承担。

**并行纪律**（避免互相踩踏）：

- 写权限按包隔离：A 只改 `services/parser/**`、`packages/core/src/anchor*`、`packages/render-reflow/**`；B 只改 `apps/**`、`packages/ui/**`；C 只改 `packages/translate/**`；D 只改 `.github/**`、`apps/cli/**`、构建脚本。
- **`packages/core/src/anchor.ts` 是唯一共享写点**：冻结后只能追加字段，修改需双人 review。

---

## 9. 第 1 周可执行清单（Day 1–5）

**Day 1｜仓库与门禁**

```bash
pnpm dlx create-turbo@latest freeread --package-manager pnpm
cd freeread && pnpm add -w -D typescript vitest @types/node eslint prettier turbo
mkdir -p apps/desktop/src/{main,renderer,preload} packages/{core,parser-protocol,render-reflow,translate,fetch,zotero,ui}/src services/parser/freeread_parser fixtures docs/adr
# 主仓许可：AGPL-3.0（已定）；写入 LICENSE、COPYING、SOURCE_OFFER.md、CONTRIBUTING.md、CODE_OF_CONDUCT.md
```

- 提交第一批 ADR：把 §2 的 12 条决策各落一个文件到 `docs/adr/`。
- 接 CI：`ci.yml`（typecheck/test/build）+ `license.yml`（**先故意加一个 `SSPL` 与一个 `CC-BY-NC` 权重依赖，验证门禁确实拦住**，再删掉）。

**Day 2｜Electron 空壳 + 阅读器占位**

```bash
pnpm --filter desktop add electron electron-builder electron-updater vite @vitejs/plugin-react react react-dom
pnpm --filter desktop add pdfjs-dist zustand
```

- 产出：能打开本地 PDF 的窗口（PDF.js 默认渲染），并输出 `getTextContent()` 的 `lineId` 统计。
- 验收：控制台能打印"第 1 页 N 行、行盒坐标范围"。

**Day 3｜数据模型与库服务**

- 落地 §3.4 的目录结构与 SQLite DDL（先不做同步）。
- `LibraryService.import(path)`：计算 sha256 → 复制到 `library/<citekey>/` → 写 `meta.json` → 插入索引。
- 验收：导入 10 篇 PDF，重复导入 0 新增（去重命中）。

**Day 4｜锚点最小闭环（不依赖 Python）**

- 用 PDF.js 行盒 + 简单 XY-Cut 产出 `blocks.json`（规则路径先跑通）。
- 渲染"重排视图"最小版：把块按顺序渲染为 `<p>`，句子带 `data-sentence-id`。
- 验收：点击重排句子能高亮原文对应行（双向验证锚点模型成立）——**这是整个项目的技术里程碑，务必在 M0 内做掉**。

**Day 5｜评测与决策前置**

- 建立 `fixtures/` 首批 10 篇与 `anchor-metrics` CLI（先输出 IoU 报告，不设阈值）。
- sidecar 可行性 spike：本地跑通 Docling，记录耗时/内存/体积，写入 `docs/adr/ADR-04-parser-sidecar.md` 的"实测数据"小节。
- 验收：产出 M2 的基线报告（当前规则法 vs Docling 的 F1/IoU 对比）。

**第 1 周结束时的产物**：可打包的空壳 + 能导入/去重/检索的库 + **锚点双向跳转跑通** + 评测基线 + 12 条 ADR + 许可门禁生效。

---

## 10. 外部依赖与成本清单（V1）

| 依赖 | 用途 | 成本 | 备注 |
|---|---|---|---|
| arXiv / PMC / Crossref / OpenAlex / Unpaywall API | 元数据与 OA 全文 | 免费（遵守 ToS，填 User-Agent 与邮箱） | Unpaywall 需邮箱参数 |
| Ollama（用户自装） | 本地翻译/问答 | 免费 | 我们只做客户端，不打包模型 |
| LLM API（可选） | 高质量翻译 | 用户自付 | key 存 OS Keychain，不落明文 |
| 代码签名证书（Win/macOS） | 分发 | 约 ¥2k–8k/年 | macOS 需 Apple Developer $99/年 |
| CI | 构建/测试 | GitHub Actions 免费额度 | 夜间全集评测用自托管 runner 更省 |

---

## 11. 附录：与 Scholaread 的能力对照（V1/V2/V3）

| Scholaread 能力 | FreeRead V1 | V2 | V3 | 说明 |
|---|---|---|---|---|
| 原文/重排双模式 | ✅ | | | 本地重排，无额度 |
| AI 重排（trust region） | ✅（本地，Docling/规则） | | | 用 `score` 暴露置信度 |
| 逐段/逐句对照翻译 | ✅（本地/自带 Key） | | | 无配额 |
| 划词/截图 OCR 翻译 | 划词 ✅ | 截图 OCR | | V1 先做划词 |
| 术语表 | ✅（对方没有） | | | 免费补位点 |
| 笔记/高亮/进度跨模式 | ✅（可靠恢复） | | | 攻克其最大抱怨 |
| 排版纠错闭环 | ✅ | | 社区 patch 汇总 | |
| 文献库/标签/全文检索 | ✅ | | | FTS5 |
| Zotero 集成 | ✅（只读导入） | 插件形态（**AGPL 已兼容，可直接做官方插件**） | | 主仓 AGPL-3.0 与 Zotero 同族，插件可共用代码 |
| 浏览器一键保存 | V1 后半可做 | ✅ 扩展 | | 对方扩展 1.3★ 且停更 |
| 全网/期刊检索 | ❌ | ✅（OA 优先） | | 不做付费墙获取 |
| AI 问答/综述 | ✅（Agent：文献库 + 项目文件 + OA 问答） | 综述报告模板、多篇对比 | | 工具面见 `specs/14-agent.md` §4.1 |
| Agent 工作区/技能/权限 | ✅（V1：14 工具 / 4 级权限 / 事件流审计） | 浏览器自动化、远端技能、多 Agent | | 见 ADR-11 与 `specs/14-agent.md` |
| 云同步/多端 | ❌（用同步盘） | ✅ CRDT | | 端到端加密 |
| Word/WPS 引用插件 | ❌ | | ✅ | 生态扩张阶段 |
| 移动端 | ❌ | | 评估 | |

---

## 12. 决策记录与待定项

### 12.1 已定：主仓许可 = **AGPL-3.0**（2026-10-03 拍板）

**这项决策解锁了什么**（原 Apache-2.0 方案中被排除、现在可以用的能力）：

| 解锁项 | 许可 | 带来的收益 | 建议用法 |
|---|---|---|---|
| **Zotero 本体 / 插件生态** | AGPL-3.0 | 可做**官方级 Zotero 插件**并与主仓共用代码；可直接引入其 translators/connectors 生态 | V2 用插件形态替代"只读导入"的临时方案 |
| **PDFMathTranslate** | AGPL-3.0 | 37.3k★ 的"保留版式 PDF 双语翻译"可直接 vendor/参考，M4 工期可压缩 | 作为 `packages/translate` 的参考实现或 `render-reflow` 的对照 |
| **PyMuPDF** | AGPL-3.0 | 解析/渲染性能最好，sidecar 内可直接使用，无需购买 Artifex 商业许可 | M2 在 sidecar 中作为快速预抽取（文本+图+坐标），Docling 做结构 |
| **pdf2htmlEX** | GPLv3（与 AGPLv3 兼容） | 可合法内置（Scholaread 同款路径） | **仍不推荐**：2020 年起停更、绝对定位 HTML 不适合语义重排；仅保留为"极端保真排版"的可行性选项 |
| **KOReader / zotero-pdf-translate / Better Notes / zotero-gpt** | AGPL-3.0 | 重排、翻译、笔记交互的实现可整段借鉴甚至移植 | 阅读交互与笔记模板 |

**同时新增的三条义务（写进 CI 与发布流程）**：

1. **源码义务**：每个分发产物必须能获得完整对应源码；若未来提供**网络服务**（云同步、在线解析），必须向该服务的使用者提供源码（AGPL §13）。
2. **标注义务**：修改过的第三方文件必须显著标注改动；保留所有版权与许可声明，产出 `THIRD_PARTY_NOTICES.md` 与 `SOURCE_OFFER.md`。
3. **兼容性边界**：**不得**引入 `GPL-2.0-only`（与 AGPLv3 不兼容）、`SSPL/BUSL/Elastic`、专有 SDK，以及 **CC-BY-NC 类模型权重**（如 Nougat 权重）——这条改成 CI 黑名单后由机器守。

**对商业化的影响（提前说明）**：AGPL-3.0 意味着任何把 FreeRead 改造后对外提供**网络服务**的一方都必须开源其改动。这对"开源项目 + 社区共建"是加强，对"某公司拿去闭源做 SaaS"是阻断——如果未来希望企业采用，可采用 **AGPL + 商业双许可（dual licensing）**：著作权归项目方，企业可另购非 AGPL 许可。**建议在 M0 前把 CLA（贡献者许可协议）一并落地**，否则后期无法双许可。

**还需同步的一处**：调研报告 §7.3/§9.1 当时给出的"商业友好（Apache 系）组件组合"是基于 Apache-2.0 假设的分析结论，仍然成立但**不再是本项目的约束**；本项目按本节的可复用清单执行即可。

### 12.2 决策状态

**已决（2026-10-03）**

1. **主仓许可 = AGPL-3.0**（见 §12.1）。
2. **接受 Python sidecar**：按需下载 150–300 MB 运行时 + 无 Python 时自动降级 `rule` 引擎（见 ADR-04）。
3. **V1 包含 Agent**：按 `specs/14-agent.md` 实施（见 ADR-11，含 V1 的明确边界：无浏览器自动化、无云端同步、无远端技能、无多 Agent 编排）。

**仍待决定**

- **CLA 与双许可**：若认同 §12.1 的双许可（AGPL + 商业许可）思路，M0 需引入 CLA 机器人（如 CLA Assistant）；否则后期无法回溯取得贡献者授权。

---

*本方案可直接作为项目启动文档（Project Charter）使用；§9 为可立即执行的开工清单。当前状态：**方案待内部评审，尚未生成代码骨架**（按你的选择）。*
