# 07 · UI 规范（布局 / 组件树 / 交互 / 状态 / 键盘 / 无障碍 / 文案）

> 状态：**冻结**（`spec-v1.1`：V1 纳入内置 Agent）。本文件是前端实现（`apps/desktop/src/renderer/**`、`packages/ui/**`）的唯一依据。
> 上游：[README §3 词汇表与命名](README.md) ｜ [00-conventions](00-conventions.md) ｜ [03-anchor-model](03-anchor-model.md) ｜ [14-agent](14-agent.md) ｜ [技术方案 §4.2 双模式渲染](../plan/FreeRead-技术方案与里程碑.md)。
> 面向读者：AI 编码代理。**本文件不含歧义项；任何"看情况"都已写成阈值。**
>
> **Agent 边界（硬规则）**：Agent 的 run 状态机、工具清单、权限模型、事件 kind 以 `14-agent.md` 为**唯一真源**，本文件只规定其**渲染与交互**；渲染进程**不实现**任何 Agent 逻辑（不调模型、不执行工具、不读写文件），只渲染 `fr:agent:event` 事件流（F1、C-1）。UI 文案与状态名不得与 `14-agent.md` §3.1 / §5.2 / §11 的命名冲突。

---

## 1. 设计原则（不可协商）

| # | 原则 | 可测判据 |
|---|---|---|
| P1 | **本地优先**：离线是默认态，网络失败绝不阻塞阅读 | 断网时 `/library`、`/reader/:citekey`、`/agent`、`OriginalPane`、`ReflowPane`、`NotesPanel` 全部可用；仅 `TranslationPanel` 与 OA 获取入口显示降级提示。断网时 `AgentView` 仍可问答（本地 `ollama` Provider），仅 `search_open_access`/`resolve_metadata`/`import_pdf` 三个联网工具卡片显示 `agent.error.*` 兜底与重试。E2E 用例登记于 `10-testing.md`：断网后打开已解析文档并加 1 条高亮成功 |
| P2 | **一切耗时操作可取消、有进度、可后台** | 导入 / 解析 / 翻译 / 索引重建四类长任务必须同时具备：进度（0–1 数值）、取消按钮、后台继续（关闭浮层不中断）。无进度可报时用**不确定进度条**（`aria-busy="true"`，不得伪造百分比） |
| P3 | **键盘优先**：论文阅读高频操作必须可纯键盘完成 | 打开库 → 导入 → 打开文档 → 切模式 → 上下句 → 加高亮 → 加笔记 → 搜索 → 关闭，全链路无鼠标；E2E 主路径用例见 `10-testing.md` |
| P4 | **阅读位置永不丢失（产品级承诺）** | ① 退出/崩溃/切换模式/重解析后，重开恢复到最后一次聚焦的 `sentenceId`，门禁值见 `AGENTS.md §7` 与 `10-testing.md` 的位置恢复用例（P0）；② 恢复失败时 UI 必须显示 `reader.banner.positionRestoredDegraded` 并落到该段所在页顶部，**不得静默回到第 1 页** |
| P5 | **低置信与双模式必须显式可见** | `score < BUDGETS.LOW_CONFIDENCE_THRESHOLD (0.60)` 的块必须出现虚线描边 + `aria-label`（INV-8）；当前阅读模式必须常驻可辨识（`aria-pressed`） |

---

## 2. 信息架构与路由

路由表（`react-router` 的 `createHashRouter`，Electron 下用 hash 路由，避免 file:// 路径问题）：

| 路由 | 页面 | 职责 | 进入条件 | 退出条件 |
|---|---|---|---|---|
| `/library` | 文献库 | 列出/筛选/排序/标签管理/导入/删除/打开文档；全文检索入口 | 应用启动默认页；`Cmd/Ctrl+O` 导入后仍停留 | 打开文档 → push `/reader/:citekey` |
| `/reader/:citekey` | 阅读器 | 双模式阅读、翻译、笔记、高亮、纠错 patch | `citekey` 在索引中存在（`fr:library:get` 成功） | 返回 / `Cmd/Ctrl+W`（关文档不关窗口）→ `/library` |
| `/agent` | Agent 主视图 | **会话列表 + 当前会话**：对话与工具卡片流、附件、引用来源、运行状态与控制 | `fr:app:getCapabilities` 的 `agent` 能力位为 `true`（V1 恒为 `true`；`false` 仅保留给企业策略/无模型运行时的显式关闭，届时隐藏入口但保留 `workspace/`、`skills/`、`permissions.json`）。**无可用 Provider 不阻断进入**：`fr:agent:start` 返回 `llmReady: false` 时渲染配置引导卡，仅禁用发送能力 | 切到其他路由（执行中必须先过 R-5 二次确认）；`Cmd/Ctrl+W` 返回 `/library` |
| `/project/:projectId` | 项目工作区 | **文件树 + 会话列表 + 权限入口**：工作区文件清单、本项目会话、工具权限表、导入/导出 | `fr:project:ensure` 返回该 `projectId`；`projectId` 不是 ULID 或项目不存在 → 重定向 `/agent` 并 toast | 手动返回 `/agent`；导出 zip 不改变路由 |
| `/settings` | 设置 | 解析引擎、OCR、翻译 Provider、术语表、外观、缓存、快捷键说明、日志导出 | 点击设置或 `Cmd/Ctrl+,` | 返回来源页（保留 scroll 与 focus） |
| `/doctor` | 诊断 | sidecar 健康、SQLite 完整性、索引一致性、日志导出、重建索引 | 设置页入口或错误页「打开诊断」；致命错误兜底跳转 | 手动返回 |

**进入/退出硬规则**：R-1 命中失败（文档不存在/被移动）→ 不渲染阅读器，渲染 `ErrorState`（`FR-LIB-005`）+「从磁盘重新定位」「从库中移除」；R-2 路由切换必须经 `fr:notes:updateProgress` 落盘位置（`visibilitychange`/`beforeunload`/路由离开三处触发，节流 1 s）；R-3 阅读器卸载前 `fr:parser:cancel` 本会话启动的解析任务（用户显式取消除外）；R-4 V1 **不提供多标签阅读**，新窗口为独立 BrowserWindow + 独立 `AnchorBusProvider`。

**Agent 路由硬规则（R-5 … R-9）**：

- **R-5（二次确认）**：离开**正在执行**的会话前必须二次确认。判据 = 当前会话 `AgentRunUiState ∈ { planning, acting, observing, waiting_user }`（§6.4）；`finished` / `canceled` / `failed` / 无 run 时**直接离开**。确认文案按 `14-agent.md` §3.1 的语义二选一：
  - `acting`（或 `planning`/`observing`）→ `agent.cancel.confirm`（"当前运行**正在执行工具**，可能已改动工作区文件；取消后已产出内容会保留"）；
  - `waiting_user`（等待 `ask_user` 回答或权限授权）→ `agent.cancel.confirmWaitingUser`（"当前运行**正在等待你的回答或授权**；取消后已产出内容会保留"）。
  `ConfirmDialog` 提供三个动作：**取消运行并离开**（`fr:agent:cancel` → 收到 `run_state=canceled` 后导航，产出保留，AG-6）/ **后台继续**（`run` 不中断，导航；`/agent` 顶部常驻 `agent.status.background` + 「返回会话」）/ **留在本页**（默认焦点，`Esc` = 留在本页）。`waiting_user` 下选「后台继续」必须同屏提示 `permission.timeout`：**120 s 倒计时继续走，超时按「拒绝」处理（仅本次 run，不写盘）**。
- **R-6（项目解析）**：`/agent` 与 `/project/:projectId` 进入时若 `projectId` 未知 → `fr:project:ensure`（创建/打开）→ 成功后才渲染；失败 → `ErrorState`（`FR-AGT-012`）+ `project.unavailable.action`。
- **R-7（并排 ≠ 多标签）**：Agent 与阅读器**可并排**，实现为**同一 BrowserWindow 内的双栏**（§3.4），**不是**多标签、不是新窗口；R-4 不变。`/reader/:citekey` 的右栏第三个页签（`rightPanel: 'ai'`）挂载 `AgentView`（`layout="dock"`），与 `/agent` 页面共用同一 `sessionId` 状态源。
- **R-8（离开不丢事件）**：run 运行在主进程，路由离开**不等于**取消；重新进入会话时用 `fr:agent:getSession({ sessionId, afterSeq })` 增量续接（`afterSeq` = 本地已知最大 `seq`），**禁止**全量重放（§12 PF-7）。
- **R-9（无特权预览）**：`ProjectFileTree` **不得**直接读取文件内容（renderer 零特权 F1，且契约无对应通道）；文件预览一律经 Agent 工具（`workspace_read` / `read_document`）产出。UI 不得为此新增通道。

---

## 3. 布局规范

### 3.1 三栏阅读器线框

```
┌─────────────────────────────────────────── Toolbar (h=48) ───────────────────────────────────────────┐
│ ← 返回   citekey · 标题(截断)        原文│重排  A- A+  t译文  / 查找  1/2/3面板  ⌘ 设置  ⛶ 全屏        │
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ QuickModeBanner (可选, h=36, 仅在 rule 引擎 / OCR 质量差 / 离线降级时出现)                            │
├──────────────┬───────────────────────────────────────────────────────────┬───────────────────────────┤
│ LeftPanel    │        ReaderArea (中栏, flex:1, 唯一滚动容器)             │ RightPanel                │
│ w=260        │   ┌───────────────────────────────────────────────┐       │ w=360                     │
│ [大纲|缩略图|标签]│   │ 段落 pa_3_4                                   │       │ [笔记|翻译|Agent]         │
│ · 1 引言      │   │  ▸ 句子 span[data-sentence-id] ←──┐           │       │ ┌───────────────────────┐ │
│ · 2 方法      │   │  ▸ 低置信块: 2px 虚线 --fr-warn   │ AnchorBus │       │ │ 笔记列表 (虚拟化)     │ │
│   · 2.1 数据  │   │  ▸ 译文 span.translation (t 开)   │           │       │ │ an_01H… 第3页 黄      │ │
│ · 3 结果      │   └───────────────────────────────────────────────┘       │ │ [导出 notes.md]      │ │
│               │   ReflowPane: article>section>h2>p>span (每 200 段一批)    │ │ 翻译: Provider/语言    │ │
│               │   OriginalPane: canvas + textLayer + 高亮层(abs rects)     │ │ [翻译本段][取消][全部] │ │
├──────────────┴───────────────────────────────────────────────────────────┴───────────────────────────┤
│ StatusBar (h=24)：页码/总页数 · 引擎(docling|marker|rule) · 解析状态 · 位置恢复状态 · fps(dev only)   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
        ▲ DragHandle(左, w=6)                                    ▲ DragHandle(右, w=6)
```

### 3.2 断点与拖拽阈值

| 视口宽度 | 左栏 | 右栏 | 行为 |
|---|---|---|---|
| ≥ 1440px | 展开（默认 260） | 展开（默认 360） | 三栏 |
| 1281–1439px | 展开 | 展开 | 中栏最小 560px，不足时优先压缩右栏至 280 |
| **1025–1280px** | 展开 | **自动收起**（`collapsed`，保留 44px 图标条） | 收起不写盘，仅临时态 |
| **≤ 1024px** | **自动收起**（保留 44px 图标条） | 自动收起 | 单栏阅读；打开任一栏以 **overlay** 覆盖中栏，`Esc` 关闭 |

**栏宽与分隔条**：左/右栏默认 260/360px，最小 200/280px，最大 420/560px，收起态 44px；键盘拖拽步长 8px；分隔条可视宽 6px、命中区 12px、`cursor: col-resize`、`role="separator"` + `aria-orientation="vertical"` + `tabindex="0"` + `aria-valuenow`（当前宽度）。

**面板状态持久化**：布局写入 `config.json` 的 `reader.layout`（`schemas/app-config.schema.json`）：

```ts
interface ReaderLayoutConfig {
  leftWidth: number;        // 200..420，默认 260
  rightWidth: number;       // 280..560，默认 360
  leftPanel: 'outline' | 'thumbnails' | 'tags';   // 默认 'outline'
  rightPanel: 'notes' | 'translation' | 'ai';     // 默认 'notes'；'ai' = AgentView(layout="dock")，见 §3.4 L-2
  leftCollapsed: boolean;   // 默认 false
  rightCollapsed: boolean;  // 默认 false
  mode: 'original' | 'reflow';                    // 默认 'reflow'（首次打开且解析未完成时为 'original'）
}
```
写入时机：拖拽结束（`pointerup`）、面板切换、模式切换，**节流 500 ms**，经 `fr:app:setConfig` 落盘；读取失败回落默认值并记 `warn`（不得抛错阻塞渲染）。

### 3.3 Agent 视图线框（复用三栏骨架）

```
┌──────────────────────────────────── Toolbar (h=48) ────────────────────────────────────┐
│ ← 返回   项目：{title}    [会话|项目文件|权限]      ⌘K 会话   ⌘⇧P 权限   ⛶ 全屏            │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ AgentBanner (可选, h=36)：agent.model.unsupportedTools ｜ agent.capability.browserNotInV1 │
├──────────────┬────────────────────────────────────────────┬────────────────────────────┤
│ LeftPanel    │  SessionView（中栏, flex:1, 唯一滚动容器）   │ RightPanel                 │
│ w=260        │   MessageBubble(role=user|assistant)       │ w=420                      │
│ [会话|项目]   │   ToolCallCard（风险图标 + 状态 + 耗时）     │ [文件|权限|技能|引用]        │
│ · 今天        │   CitationList（挂在 finish 消息下）         │ ProjectFileTree            │
│  · 会话 A     │   MessageBubble(流式, aria-busy)            │ ToolPermissionPanel        │
│ · 本周        │   ────────────────────────────────────     │ SkillPanel                 │
│  · 会话 B     │   AttachmentPicker + 输入框 + RunCancelButton│ CitationList（镜像只读）     │
│ ProjectList  │   AgentStatusBar（steps/calls/tokens）      │                            │
├──────────────┴────────────────────────────────────────────┴────────────────────────────┤
│ StatusBar (h=24)：run 状态 · 模型 · 项目 · 会话保留期提示                                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
      ▲ DragHandle(左, w=6)                        ▲ DragHandle(右/Agent 面板, w=6)
```

| 栏 | 内容 | 约束 |
|---|---|---|
| 左栏（默认 260，规则同 §3.2） | 会话列表 + 项目列表（同一个 `SessionList`，按项目分组） | `fr:agent:listSessions` 结果缓存；**不得**轮询（§12 PF-9） |
| 中栏（`flex:1`） | 对话与工具卡片流；输入区吸附底部 | **唯一滚动容器**；> 200 条事件必须虚拟化（§12 PF-7） |
| 右栏（默认 420，见 §3.4） | 项目文件树 / 权限入口 / 技能 / 引用来源（四页签） | 只读展示；文件**不可**在渲染进程预览（R-9） |

**必挂载元素**：`AgentView` 必须始终渲染 `AgentStatusBar`；存在活动 run 时必须渲染 `RunCancelButton`；右栏必须常驻 `ToolPermissionPanel` 入口（**权限入口不可藏在二级菜单内**，`14-agent.md` §13 要求权限可见）。

### 3.4 Agent 与阅读器的关系（并排形态）

| # | 规则 | 可测判据 |
|---|---|---|
| L-1 | **页面形态**：`/agent` 独占整窗，三栏同 §3.3 | 路由 `/agent` 下渲染 `AgentView(layout="page")` |
| L-2 | **并排形态（dock）**：同一 BrowserWindow 内**双栏**——阅读器保留左栏与中栏，Agent 面板占右栏位置 | `/reader/:citekey` 的 `rightPanel: 'ai'` 渲染 `AgentView(layout="dock")`；**不**新建窗口、**不**新增标签（R-7） |
| L-3 | Agent 面板宽度：**默认 420px**（`AGENT_PANEL_WIDTH_DEFAULT`）、**最小 320px**（`AGENT_PANEL_WIDTH_MIN`）、**最大 720px**（`AGENT_PANEL_WIDTH_MAX`）、收起态 44px；键盘拖拽步长 8px；分隔条规则同 §3.2（`role="separator"` + `aria-valuenow`） | 拖到 300 时钳制为 320；拖到 900 时钳制为 720 |
| L-4 | 断点：≥ 1440 三栏并排；1281–1439 先压缩阅读器右栏（360→280），再压缩 Agent 面板但**不得低于 320**；≤ 1280 Agent 面板改为 **overlay** 覆盖中栏（`Esc` 关闭，宽 = `min(720, 视口宽 − 88)`） | 视口 1200 时 Agent 为 overlay；`Esc` 优先关闭 overlay（§7.3 层序） |
| L-5 | 宽度为**会话内临时态，不写盘**：不新增 `config.json` 键（`schemas/app-config.schema.json` 是配置唯一真源；持久化须走 `spec:` 变更 + `schemaVersion` 流程，F9） | 重启后回到默认 420 |
| L-6 | 非阻塞：run 进入 `waiting_user` 时阅读器照常可读可标注（`14-agent.md` §3.1） | `waiting_user` 下中栏滚动与快捷键 `j/k/n/p/t/o/h/m` 全部可用 |
| L-7 | dock 形态下 Agent 快捷键要求焦点在面板内（`data-fr-keyscope="agent"`）；`/agent` 页面形态下为全局作用域 | 阅读器内按 `Cmd/Ctrl+K` 不打开会话切换（焦点不在面板） |
| L-8 | 权限弹窗落点：dock 形态渲染在 Agent 面板内（`role="alertdialog"` + 面板内焦点陷阱，**不遮挡阅读器正文**）；页面形态为居中模态 | 两种形态均可纯键盘完成四选项（§8 A11） |

---

## 4. 组件树（V1 清单）

> 所有组件：`PascalCase.tsx`；样式类名 `fr-*`；用户可见文案一律 i18n key（F6）。
> IPC 通道引用 `06-ipc-contract.md`；本节给出的通道名即该文件通道表的**最小必备集**。

### 4.1 组合关系

```
App
├─ AppShell / ThemeProvider(主题 + prefers-reduced-motion + 字号) / I18nProvider / ToastProvider
├─ Routes
│  ├─ LibraryView ── ImportDialog / SearchPalette
│  ├─ ReaderView ── AnchorBusProvider
│  │   ├─ Toolbar / QuickModeBanner / StatusBar
│  │   ├─ LeftPanel → OutlinePanel | ThumbnailsPanel | TagTreePanel
│  │   ├─ ReaderArea → OriginalPane | ReflowPane
│  │   │   ├─ LowConfidenceOverlay（两个 Pane 各自渲染）
│  │   │   └─ PatchEditor（Popover，挂载在选中块上）
│  │   └─ RightPanel → NotesPanel | TranslationPanel | AgentView(layout="dock")   ← 并排（§3.4 L-2）
│  ├─ AgentView(layout="page")                                                        ← 路由 /agent
│  │   ├─ AgentBanner（unsupportedTools / browserNotInV1，可关闭但每次会话首条显示）
│  │   ├─ LeftPanel → SessionList（会话列表 + 项目列表，按项目分组）
│  │   ├─ SessionView（中栏，唯一滚动容器）
│  │   │   ├─ MessageBubble（role=user | assistant；流式文本）
│  │   │   │   ├─ ToolCallCard（可聚焦；sideEffect 风险图标 + 状态；展开看参数摘要）
│  │   │   │   └─ CitationList（挂在 finish 消息下；右栏「引用」页签为其只读镜像）
│  │   │   └─ Composer → AttachmentPicker / 输入框 / RunCancelButton
│  │   ├─ AgentStatusBar ── ModelPicker（Popover）
│  │   └─ RightPanel → ProjectFileTree | ToolPermissionPanel | SkillPanel | CitationList
│  ├─ AgentView(layout="page", initialRightTab="files")                                ← 路由 /project/:projectId
│  │   （项目工作区 = 文件树 + 本项目会话 + 权限入口；**不新增容器组件**，仅改初始项目与页签）
│  ├─ SettingsView ── GlossaryEditor / ProviderForm / CacheManager
│  └─ DoctorView
└─ ErrorBoundary(AppFatal) / ConfirmDialog / PermissionDialog(role="alertdialog") / ErrorState / EmptyState / Skeleton
```

### 4.2 组件契约

```ts
// 格式：职责 → props（TS 签名）→ 内部状态（S）→ 触发事件（E）→ IPC 依赖
export interface LibraryViewProps { initialFilter?: LibraryFilter }
// 职责：列表/筛选/排序/标签、导入入口、FTS 检索、打开文档
// S：filter, sort, query, selection:Set<docId>, importState ｜ E：onOpen(citekey), onImport(paths), onDelete(citekey), onTagChange
// IPC：fr:library:list / fr:library:import / fr:library:delete / fr:library:updateMeta / fr:search:query（> 100 条用 @tanstack/react-virtual 虚拟化）

export interface ReaderViewProps { citekey: string }
// 职责：会话编排（打开→解析→就绪）、双模式容器、位置保存、错误兜底
// S：session: ReaderSessionState, layout: ReaderLayoutConfig, engine, quality ｜ E：onClose, onRetryParse, onExportLogs
// IPC：fr:library:get / fr:anchor:get / fr:parse:start / fr:parse:cancel / fr:progress:save / fr:progress:get /
//      fr:config:get / fr:config:set；订阅事件 fr:parse:progress。状态机见 §6.1；容器自身不滚动，滚动只发生在 ReaderArea

export interface OriginalPaneProps {
  docId: string; pdfUrl: string;                      // pdfUrl 由 preload 提供 fr-file:// 协议，renderer 不碰 fs（F1）
  scale: number; pageWindow: [number, number];        // 仅渲染可见页 ±2
  activeSentenceId: string | null; flashRectKeys: string[];    // 点击重排句后的闪烁矩形 key
  onVisibleSentenceChange(sentenceId: string): void;  // 滚动 → 上报视口首个句子
  onSelectLines(lines: LineRef[]): void;              // 文本层选区 → 反查句子
}
// S：pageCanvases(Map<PageNo,{canvas,textLayer}>), rectIndex(Map<sentenceId,Rect[]>) ｜ E：onVisibleSentenceChange, onSelectLines
// IPC：fr:anchor:get（rects）/ fr:library:thumbnails ｜ 渲染：canvas(DPR 自适应, dpi=BUDGETS.PAGE_BITMAP_DPI) + 文本层 + 绝对定位高亮层

export interface ReflowPaneProps {
  model: DocAnchorModel;                              // 只读
  activeSentenceId: string | null; highlightIds: string[];
  translationMode: 'off' | 'sentence' | 'paragraph' | 'only';
  translations: Map<string, string>;                  // key = sentenceId | paragraphId
  onVisibleSentenceChange(sentenceId: string): void; onSentenceClick(sentenceId: string): void;
  onBlockContextMenu(blockId: string, at: { x: number; y: number }): void;   // 纠错入口
}
// S：mountedBatches:number（每 200 段一批）、patchOverlay ｜ E：onVisibleSentenceChange, onSentenceClick, onBlockContextMenu
// 依赖 packages/render-reflow 产出的 HTML 字符串（renderer 内不得实现排版算法）；分段挂载见 §12

export interface AnchorBusProviderProps { children: ReactNode; docId: string; initialSentenceId?: string }
// 职责：唯一的跨面板锚点总线（选中/高亮/滚动/翻译对齐）；任何跨视图同步必须经本 Provider，禁止组件间直接传 ref
// S：activeSentenceId, hoveredSentenceId, selection:{page,lines}[], scrollLock:'none'|'original'|'reflow'
// E：select(sentenceId), hover(sentenceId), flash(rectKeys,ms), lockScroll(who) ｜ IPC：无（持久化走 fr:progress:save，节流 1 s）

export interface ToolbarProps {
  citekey: string; title: string; mode: 'original' | 'reflow'; engine: ParserEngineName;
  parseState: ParseUiState; translateState: TranslateUiState;
  onModeChange(m: 'original' | 'reflow'): void; onToggleTranslation(): void;
  onOpenPanel(p: 'left' | 'right'): void; onZoom(delta: number): void; onFind(): void;
}
export interface OutlinePanelProps { items: OutlineItem[]; activeBlockId: string | null; onJump(page: PageNo, blockId: string): void }
export interface ThumbnailsPanelProps { docId: string; pageCount: number; onJump(page: PageNo): void }
export interface TagTreePanelProps { tags: TagNode[]; selected: string[]; onToggle(tag: string): void }
export interface NotesPanelProps {
  annotations: Annotation[]; filter: { kind?: AnnotationKind; color?: string; tag?: string };
  onEdit(id: string, patch: Partial<Annotation>): void; onDelete(id: string): void;
  onExport(kind: 'notes.md' | 'annotations.jsonl'): void; onJump(a: Annotation): void;
}
// IPC：fr:note:list / fr:note:add / fr:note:update / fr:note:delete
// 硬规则：译文模式（translationMode==='only'）下「加高亮/加笔记」按钮禁用，悬浮提示 = i18n `notes.translationDisabled`

export interface TranslationPanelProps {
  docId: string; targetLang: string; providerId: string | null; progress: { done: number; total: number } | null;
  onTranslateScope(scope: 'current' | 'viewport' | 'all'): void; onCancel(): void;
  onProviderChange(id: string): void; onOpenGlossary(): void;
}
// IPC：fr:translate:translate / fr:translate:batch / fr:translate:cancel / fr:translate:providers /
//      fr:translate:glossary:get / fr:translate:glossary:set ｜ 事件：fr:translate:progress

export interface QuickModeBannerProps { reason: 'noSidecar' | 'sidecarFailed' | 'ocrQuality' | 'offlineDegraded'; onRetry(): void; onDismiss(): void; onOpenDoctor(): void }
// 文案：`reader.banner.quickMode`（+ reason 后缀 key）；dismiss 仅当次会话有效（不写盘）

export interface LowConfidenceOverlayProps { blocks: Array<{ blockId: string; rect: Rect; page: PageNo; score: number }>; scale: number; onPick(blockId: string): void }
// 渲染：2px 虚线 --fr-warn；aria-label = `reader.lowConfidence.hint`（含 score 百分比）；触发：INV-8，score < 0.60

export interface PatchEditorProps { blockId: string; currentType: BlockType; siblings: string[]; onApply(patch: PatchOp): void; onCancel(): void }
export type PatchOp =
  | { op: 'retype'; blockId: string; type: BlockType }
  | { op: 'merge'; blockIds: string[] }
  | { op: 'split'; blockId: string; at: { page: PageNo; lineId: number; charIndex: number } }
  | { op: 'delete'; blockId: string }
  | { op: 'reorder'; blockId: string; afterBlockId: string | null };
// IPC：fr:anchor:patch:save / fr:anchor:patch:list；保存后本地立即重渲染（不重跑模型），落盘 library/<citekey>/patches/<blockId>.json

export interface ImportDialogProps {
  open: boolean; sources: Array<'file' | 'folder' | 'zotero'>;
  items: ImportItem[]; progress: { done: number; total: number; current: string } | null;
  onPick(paths: string[]): void; onCancel(): void; onClose(): void;
}
export interface SearchPaletteProps { open: boolean; scope: 'library' | 'document'; onQuery(q: string): void; onPick(hit: SearchHit): void; onClose(): void }
export interface SettingsViewProps { section?: 'parser' | 'translate' | 'appearance' | 'cache' | 'logs' | 'shortcuts' }
export interface DoctorViewProps { onRebuildIndex(): void; onExportLogs(): void; onRestartSidecar(): void }
// IPC：fr:search:query（库内检索）/ fr:doctor:run / fr:doctor:rebuildIndex / fr:app:exportLogs / fr:parser:health
```

### 4.3 组件纪律

- C-1：`renderer` 不得直接 `import 'fs' | 'electron' | 'node:*'`（F1、`00-conventions §4`）；一切经 `window.fr`（preload 白名单）。
- C-2：`packages/render-reflow` 只输出 HTML 字符串；renderer 不得在其中插入 React 节点后回传。
- C-3：所有跨进程返回载荷必须 zod 校验（`00-conventions §2.2`）；校验失败 → `AppError('FR-IPC-002')`。
- C-4：组件内不得出现魔法数字阈值；一律引用 `BUDGETS` 或本文件具名常量。
- C-5（Agent）：组件**不得硬编码** 14 个工具的名称与描述；一律由 `fr:agent:listTools` 的清单 + `agent.tool.<camelName>.name/desc` 驱动（§9.6 为冻结映射表）。
- C-6（Agent）：组件**不得**用轮询或本地计时器推断 run 状态；状态只来自 `fr:agent:event`（§12 PF-9）。唯一允许的计时器：`PermissionDialog` 的 120 s 倒计时、工具卡片耗时的 1 s 节流刷新。
- C-7（Agent）：授权、取消运行、删除会话三类动作必须走 `PermissionDialog` / `ConfirmDialog`，且**均有键盘等价路径**（§7.3、§8 A11）。

### 4.4 Agent 组件契约（V1 新增 14 个）

```ts
// 4.4.1 AgentView —— 装配容器（路由级）；本组件不含业务逻辑，只做 ensure → 取会话 → 订阅 → 分发
export interface AgentViewProps {
  layout: 'page' | 'dock';                       // page = /agent 与 /project/:projectId；dock = 阅读器右栏并排（§3.4）
  projectId?: string;                            // 缺省 = fr:project:ensure 的结果
  sessionId?: string | null;                     // 缺省 = 该项目最近会话
  initialRightTab?: 'files' | 'permissions' | 'skills' | 'citations';   // 默认 'files'
}
// S：sessions, activeSessionId, activeRun: AgentRunUiState, events: AgentEvent[], capabilities, banner
// E：onSelectSession(id) / onNewSession() / onDeleteSession(id) / onSend(text, attachments) / onCancelRun() / onSetRightTab(tab)
// IPC：fr:project:ensure / fr:agent:start / fr:agent:listSessions / fr:agent:getSession / fr:agent:send /
//      fr:agent:cancel / fr:agent:listTools / fr:app:getCapabilities ｜ 事件：fr:agent:event / fr:project:changed
// 硬规则：① 事件按 seq 单调去重，检出 gap 用 getSession({ afterSeq }) 补拉（R-8）；② 组件卸载**不**取消 run；
//        ③ capabilities.agent !== true 时不渲染 Agent 入口（能力位语义见 14-agent.md §11）

// 4.4.2 SessionList —— 数据行 = AgentSessionSummary（契约字段一对一，不得自造）
export interface SessionListProps {
  sessions: Array<{ sessionId: string; projectId: string; title: string; createdAt: number; updatedAt: number;
                    messageCount: number; toolCallCount?: number; runState: AgentRunUiState;
                    activeRunId: string | null; lastMessagePreview?: string | null }>;
  projects: Array<{ projectId: string; title: string; sessionCount: number }>;
  activeSessionId: string | null; activeProjectId: string | null;
  onSelect(sessionId: string): void; onSelectProject(projectId: string): void;
  onNewSession(projectId: string): void; onDeleteSession(sessionId: string): void;
}
// S：query（本地过滤，不查后端）, deleteTarget ｜ E：onSelect / onSelectProject / onNewSession / onDelete
// IPC：fr:agent:listSessions（强制分页：`items` + `total`；已取条数 < total 时滚动到底继续取）/ fr:agent:start /
//      fr:agent:deleteSession / fr:project:ensure ｜ 事件：fr:project:changed
// 硬规则：① 「运行中」徽标判据 = activeRunId !== null（不是 runState !== 'finished'）；
//        ② 删除必须经 ConfirmDialog（agent.session.deleteConfirm，含「不可恢复」与 agent.session.retention）；
//        ③ > 100 条用 @tanstack/react-virtual 虚拟化（同 PF-1）；④ 后台运行的会话显示 agent.state.* 小徽标

// 4.4.3 SessionView —— 中栏；唯一滚动容器
export interface SessionViewProps {
  sessionId: string; events: AgentEvent[]; runState: AgentRunUiState;
  streamingText: string | null;                 // 流式增量，≥ 30 ms/帧（PF-8）
  onSend(text: string, attachments: Attachment[]): void;
  onCancelRun(): void; onRetry(): void; onPickCitation(c: Citation): void;
}
// S：scrollPinned: boolean（贴底）, expandedCallIds: Set<string>, draft ｜ E：onSend / onCancelRun / onRetry / onPickCitation
// IPC：fr:agent:send / fr:agent:cancel / fr:agent:getSession ｜ 事件：fr:agent:event
// 硬规则：① 事件 > 200 条必须虚拟化（PF-7）；② 仅当 scrollPinned === true 时新事件自动贴底，用户上滚即解除；
//        ③ 渲染顺序严格按 seq，禁止按到达时间重排；④ `unparsableLines > 0`（FR-AGT-010）→ 该会话顶部显示
//          agent.error.sessionCorrupt，坏行不渲染但**不整页崩溃**；
//        ⑤ 历史分页：`fr:agent:getSession` 每页 ≤ 500 行，`hasMore === true` 时向上滚动继续取（游标 = 当前最小 seq）；
//        ⑥ `fr:agent:send` 返回 `deduped === true`（幂等命中）时**不得**重复插入用户消息，直接复用返回的 runId

// 4.4.4 MessageBubble
export interface MessageBubbleProps {
  role: 'user' | 'assistant'; text: string; at: number; tokens?: number;   // tokens 来自 message 事件（14-agent.md §8）
  streaming?: boolean;                           // true → aria-busy="true"，读屏不逐字播报
  unverified?: boolean;                          // 由 run_state.payload.verified === false 驱动（AG-10）
  citations?: Citation[];                        // 类型见 4.4.10（= run_state.payload.citations 的元素）
  onCopy(): void; onPickCitation(c: Citation): void;
}
// S：无（纯展示）｜ E：onCopy / onPickCitation
// IPC：无（数据由 SessionView 下发）｜ 渲染：Markdown 子集（粗体/列表/行内代码/KaTeX），禁止 dangerouslySetInnerHTML
// 硬规则：unverified === true 时必须显示 agent.unverified（AG-10），不得静默

// 4.4.5 ToolCallCard —— 必须区分 sideEffect 并显示风险图标
export interface ToolCallCardProps {
  callId: string; tool: string; labelKey: string;                 // labelKey = agent.tool.<camelName>.name
  sideEffect: 'none' | 'read' | 'write' | 'network' | 'execute';
  status: 'running' | 'ok' | 'failed' | 'rejected' | 'canceled';
  argsSummary: string;                          // tool_start.payload.argsSummary（≤ 400 字符）
  summary?: string;                             // tool_end.payload.summary（≤ 400 字符；唯一回灌模型的内容，UI 展示为结果摘要）
  resultId?: string;                            // tool_end.payload.resultId（AG-10 引用可追溯）
  errorCode?: string; durationMs?: number; startedAt: number;
  expanded: boolean; onToggle(callId: string): void; onOpenPermission(tool: string): void;
}
// S：无（受控；展开态由 SessionView 持有）｜ E：onToggle / onOpenPermission
// IPC：无（数据来自 fr:agent:event 的 tool_start / tool_end）；「权限」跳转经 ToolPermissionPanel
```

**风险图标与等级（冻结）**——`sideEffect` 必须映射为下表，不得自创：

| `sideEffect` | 图标 | 颜色令牌 | 文案 key | 风险等级 | 默认权限（`14-agent.md` §4.1） |
|---|---|---|---|---|---|
| `none` | `circle-slash` | `--fr-text-muted` | `agent.tool.sideEffect.none` | 低 | `always` |
| `read` | `eye` | `--fr-text-muted` | `agent.tool.sideEffect.read` | 低 | `always` |
| `network` | `cloud-arrow` | `--fr-accent` | `agent.tool.sideEffect.network` | 中 | `always`（出网必过 NetGuard 并记审计） |
| `write` | `pencil` | `--fr-warn` | `agent.tool.sideEffect.write` | 高 | `ask` |
| `execute` | `terminal` | `--fr-danger` | `agent.tool.sideEffect.execute` | 高 | `ask` |

```ts
// 硬规则（续 4.4.5）：① write / execute 卡片常驻风险提示行（agent.tool.sideEffect.*），不得只在 tooltip 里；
//   ② status==='rejected'（FR-AGT-003）与 'failed'（FR-AGT-005）必须视觉可区分（前者 --fr-text-muted + 权限入口，后者 --fr-danger + 重试）；
//   ③ 'canceled' 仅由 run_state=canceled 驱动：run 取消时仍在 running 的卡片转 'canceled'（中性色 + agent.tool.status.canceled），
//      已 ok 的卡片保持结果摘要不变（AG-6：取消保留产出）；
//   ④ 卡片可聚焦（tabindex="0"）且 aria-label 含「工具展示名 + 状态 + 风险等级」（§8 A10）

// 4.4.6 PermissionDialog —— 四选项 + 120 s 倒计时 + 默认拒绝
export interface PermissionDialogProps {
  open: boolean; callId: string; tool: string; labelKey: string;
  sideEffect: ToolCallCardProps['sideEffect']; argsSummary: string;   // argsSummary ≤ 400 字符（同契约）
  riskLevel: 'low' | 'medium' | 'high';          // 由 payload.risk（= sideEffect）按 4.4.5 冻结表映射，**不是**契约字段名
  timeoutMs: number;                             // 取自 payload.timeoutMs（默认 120_000，14-agent.md §5.2）；组件不得自造
  remainingMs: number;                           // 单一计时器由 SessionView 持有并每秒下发
  batchable: boolean;                            // 同一 run 内已有同类 write 调用 → 启用「本次全部允许」
  onDecide(d: PermissionDecision): void;
}
export type PermissionDecision =
  | { kind: 'once' }          // 允许一次（仅本 run 有效，不写盘）
  | { kind: 'always' }        // 总是允许（写 permissions.json）
  | { kind: 'allowAllOnce' }  // 本次全部允许（对同 run 内同 sideEffect 的 write 类工具置 once）
  | { kind: 'deny' };         // 拒绝（写盘；终态 AG-9，同工具不再询问）
// S：无（受控）｜ E：onDecide
// IPC：fr:agent:listTools（取 sideEffect 与当前规则）/ fr:agent:setPermissionRule ｜ 事件：fr:agent:event（kind=permission_required）
```

**四选项（冻结，`14-agent.md` §5.2 的 UI 映射）**：

| # | 选项 | 文案 key | 语义 | 持久化 | 键盘 |
|---|---|---|---|---|---|
| 1 | 允许一次 | `permission.option.allowOnce` | 置 `once`，本 run 内同工具免询问 | 否 | `1` / `Enter`（焦点项） |
| 2 | 总是允许 | `permission.option.alwaysAllow` | 置 `always`，写盘 | 是 | `2` |
| 3 | 本次全部允许 | `permission.option.allowAllOnce` | 对同 run 内同 `sideEffect` 的 `write`/`execute` 工具置 `once`（批量授权） | 否 | `3` |
| 4 | 拒绝 | `permission.option.deny` | 置 `deny`，写盘；同工具此后直接以 `FR-AGT-003` 返回 | 是 | `4` / `Esc`（= 拒绝） |

```ts
// PermissionDialog 硬规则（逐条可测）：
//  1. 恰有四个选项：DOM 顺序 = 上表；batchable === false 时第 3 项 disabled（不进 Tab 序）并显示 permission.batch.hint；
//  2. 初始焦点在「拒绝」上（安全默认）；焦点陷阱：Tab/Shift+Tab 只在可聚焦选项与「查看工具详情」之间循环；
//  3. 倒计时文案 = permission.timeout（{seconds}，向上取整）；到 0 → **自动按 deny 处理（仅本次 run，不写盘）** 并关闭；
//  4. 弹窗内必须显示 permission.defaultDenyNote（未选择时按拒绝处理）与风险等级（permission.risk.*）；
//  5. 去重键 = callId：已决策的 callId 不得再次弹出；跨会话切换后未决策的弹窗重新计时（重新由事件流驱动）；
//  6. role="alertdialog" + aria-modal="true" + aria-labelledby/aria-describedby（§8 A11），键盘可完成全部四选项

// 4.4.7 ToolPermissionPanel —— 权限入口（右栏「权限」页签；工具权限的唯一修改点）
export interface ToolPermissionPanelProps {
  tools: Array<{ name: string; labelKey: string; sideEffect: ToolCallCardProps['sideEffect']; description: string;
                 defaultRule: PermissionRule; rule: PermissionRule; updatedAt?: number; timeoutMs: number;
                 available: boolean }>;                      // available 来自 AgentToolInfo（依赖缺失，如离线联网工具、无 Pyodide）
  onSetRule(tool: string, rule: PermissionRule): void; onOpenToolDetail(tool: string): void;
}
export type PermissionRule = 'always' | 'once' | 'ask' | 'deny';   // 冻结，见 14-agent.md §5.1
// S：filter（按 sideEffect / 名称）, pendingTool ｜ E：onSetRule / onOpenToolDetail
// IPC：fr:agent:listTools（工具清单 + 权限表 + Provider 能力）/ fr:agent:setPermissionRule（返回完整权限表 + effective）/ fr:project:getPermissions
// 硬规则：① 下拉仅 [always | ask | deny]（`once` 是 run 作用域，**不得**出现在持久规则下拉里）；
//        ② 置 deny 后该行显示 permission.scope.deny（终态 AG-9），后续该工具调用卡片全部转 rejected；
//        ③ write / execute 行必须同时显示风险图标与 sideEffect 文案（与 4.4.5 同一映射）；
//        ④ available === false 的行置灰并显示 agent.tool.unavailable（**仍可设规则**：依赖恢复后立即生效）；
//        ⑤ 空清单显示 permission.panel.empty（不渲染空下拉）

// 4.4.8 SkillPanel
export interface SkillPanelProps {
  skills: Array<{ name: string; description: string; version: string; license: string; hasScripts: boolean }>;
  installing: boolean; error?: { code: string; message: string };
  onInstall(): void; onOpenFolder(skill: string): void;
}
// S：selectedSkill, filter ｜ E：onInstall（目录经系统选择对话框，renderer 不拼路径）/ onOpenFolder
// IPC：fr:agent:listSkills / fr:agent:installSkill
// 硬规则：① V1 只支持**本地目录安装**：无「市场」「搜索远端技能」「下载」入口（14-agent.md §9）；
//        ② 安装失败：SKILL.md/front-matter/license/路径穿越/体积不合规 → FR-AGT-009（errors.FR-AGT-009 + 原因）；
//           **同名技能已存在**时安装请求必须带 overwrite=true，UI 必须先经 ConfirmDialog 确认覆盖，未确认即失败 → FR-AGT-002；
//        ③ hasScripts === true 的技能显示 agent.skill.scriptsNotExecuted（V1 不允许 Agent 执行技能脚本）；
//        ④ 无效技能（`valid === false`）置灰并显示原因，**不注入上下文**（契约字段 valid/reason）；
//        ⑤ 空态 = agent.empty.skills

// 4.4.9 ProjectFileTree —— 数据行 = ProjectListFilesResponse.files（契约字段一对一）
export interface ProjectFileTreeProps {
  projectId: string; dir?: string;                     // dir = 工作区相对路径，省略为根
  files: Array<{ path: string; bytes: number; modifiedAt: number; ext?: string | null }>;
  total: number; truncated: boolean;                   // truncated === true → 显示 project.fileTree.truncated {count}
  importing: boolean;
  onLoadMore(): void; onImportFiles(): void; onExportZip(): void; onAskAboutFile(path: string): void;
}
// S：expandedDirs: Set<path>, selectedPath ｜ E：onLoadMore（offset += limit；limit ≤ 2000）/ onImportFiles / onExportZip / onAskAboutFile
// IPC：fr:project:listFiles（强制分页：offset/limit，recursive 可选）/ fr:project:importFiles / fr:project:exportZip
// 事件：fr:project:changed（→ 失效缓存并重取首页，防抖 300 ms）
// 硬规则：① **不渲染文件内容预览**（R-9：renderer 零特权且契约无对应通道）；onAskAboutFile 只写入输入框草稿，不自动发送；
//        ② 展示 `bytes`/`modifiedAt`（人类可读），**不得**展示或拼接绝对路径（契约只回相对路径，05-storage.md §11 PR1）；
//        ③ 空态 = project.fileTree.empty（不提供「新建文件」按钮：写入只经 Agent 的 workspace_write，AG-3/AG-4）；
//        ④ 导出 zip 前必须显示 project.export.note（恒不含 permissions.json 与 sessions/，14-agent.md §7）；
//        ⑤ 不提供「在文件管理器中显示」入口——契约无此通道，UI 不得发明（F1 ＋ 通道白名单）

// 4.4.10 CitationList —— 数据行 = run_state.payload.citations（≤ 200；字段 {callId, docId?, note?}）
export type Citation = { callId: string; docId?: string; note?: string };
export interface CitationListProps {
  citations: Citation[];
  variant: 'inline' | 'panel';
  onOpen(c: Citation): void; onJumpToToolCall(callId: string): void;
}
// S：无 ｜ E：onOpen（先 fr:library:get 校验存在 → push /reader/:citekey；不存在 → FR-LIB-005 显示 library.item.missing）/ onJumpToToolCall
// IPC：fr:library:get（docId → citekey + meta.title，标题**必须**由此解析，事件里没有标题）
// 硬规则：① 标题固定 agent.citation.title；② 列表为空且 variant==='inline' → 显示 agent.citation.empty
//          （不隐藏整块：AG-10 的可追溯性必须可见）；③ 每项显示来源工具调用（agent.citation.toolCall {tool}）并可回跳对应 ToolCallCard（按 callId 定位）；
//        ④ `run_state.payload.verified === false` 时同一消息必须同时出现 agent.unverified（MessageBubble 的 unverified 即由此驱动）

// 4.4.11 AgentStatusBar —— 全部计数取自 run_state.payload（steps / toolCalls / reason）
export interface AgentStatusBarProps {
  runState: AgentRunUiState; steps: number; maxSteps: number; toolCalls: number; maxCalls: number;
  reason?: string | null; model: string | null; providerId: string | null;
  sessionId: string | null; background: boolean;
  onOpenModelPicker(): void; onOpenPermissions(): void; onBackToSession(): void;
}
// S：无（受控）｜ E：onOpenModelPicker / onOpenPermissions / onBackToSession
// IPC：fr:agent:getSession（run = AgentRunSummary：state/steps/toolCalls）/ fr:agent:listTools（model / providerId / llmReady）
// 事件：fr:agent:event（kind=run_state）
// 硬规则：① 计数一律取自事件载荷，**禁止前端自算**（§6.4 A-1）；maxSteps/maxCalls 取自 `packages/core` 的
//         `AGENT_BUDGETS`（`14-agent.md` §3.2 冻结；UI 不得硬编码 24/40，C-4）；
//        ② 达到上限的 80% 时状态栏转 --fr-warn（只提示，不弹窗、不打断）；③ background === true 时显示 agent.status.background + 返回入口；
//        ④ llmReady === false 时显示 agent.model.none（不显示步数区，避免无意义计数）

// 4.4.12 RunCancelButton
export interface RunCancelButtonProps { runState: AgentRunUiState; pending: boolean; onCancel(): void }
// S：无 ｜ E：onCancel（必须经 ConfirmDialog，§7.3）
// IPC：fr:agent:cancel（终态幂等：对 finished/canceled/failed 返回 canceled:false，UI 不得报错）
// 硬规则：① 仅在 runState ∈ { planning, acting, observing, waiting_user } 时渲染；
//        ② 点击后立即 pending（disabled + aria-busy）直到收到 run_state=canceled/failed 或 5 s 超时（超时按 FR-IPC-003 文案提示）；
//        ③ 取消后**必须保留**全部已有消息与工具卡片（AG-6），并 toast agent.cancel.done

// 4.4.13 ModelPicker —— 数据源 = fr:agent:listTools 的 providers / activeProviderId / llmReady
export interface ModelPickerProps {
  open: boolean;
  providers: Array<{ id: string; kind: 'local' | 'remote'; model: string | null;
                     available: boolean; supportsTools: boolean; endpointHost?: string | null; reason?: string | null }>;
  activeProviderId: string | null; activeModel: string | null; llmReady: boolean;
  onChange(providerId: string, model: string): void; onOpenProviderSettings(): void; onClose(): void;
}
// S：query, loading ｜ E：onChange / onOpenProviderSettings / onClose
// IPC：fr:agent:listTools（Provider 与模型清单；**只回 host，绝不回密钥**）/ fr:app:setConfig（持久化；
//      `app-config.schema.json` **没有** agent 节，选择结果复用 `translation` 节的 Provider 体系，**禁止新增配置键**，F9）
// 硬规则：① llmReady === false 或全部 available === false → 显示 agent.model.none + agent.model.none.action，并禁用发送（FR-AGT-001，入口仍可见）；
//        ② supportsTools === false → 选中项副标题显示 agent.model.unsupportedTools（降级为 ReAct-文本模式，14-agent.md §10.1；
//          该字段在契约中为**必填**，UI 不得猜测）；
//        ③ 当前生效值以 providers[].model 与 activeProviderId 为准（不是本地缓存）；切换只影响**下一次** run，
//          活动 run 期间控件 disabled 并显示 agent.model.lockedDuringRun；
//        ④ Provider 的 endpointHost 可显示（仅主机名），**任何情况下不得显示密钥字段**（契约中不存在密钥字段）

// 4.4.14 AttachmentPicker
export interface AttachmentPickerProps {
  open: boolean;
  libraryItems: Array<{ docId: string; citekey: string; title: string }>;
  workspaceFiles: Array<{ path: string; name: string }>;
  selected: Attachment[];
  onSelect(a: Attachment): void; onRemove(key: string): void; onImportFile(): void; onClose(): void;
}
export type Attachment =
  | { kind: 'document'; docId: string; citekey: string }
  | { kind: 'workspaceFile'; path: string };
// S：tab: 'library' | 'workspace', query ｜ E：onSelect / onRemove / onImportFile / onClose
// IPC：fr:library:list（文献）/ fr:project:listFiles（工作区）/ fr:project:importFiles（从磁盘加入工作区）
// 硬规则：① 单条附件内容上限 8,000 字符（14-agent.md §6.1）：UI **不截断**，超限经主进程返回后显示
//          agent.attachment.tooLarge 并标红该条；② 已选项显示为可移除 chip（键盘 Backspace 删除末项）；
//        ③ 两个来源都为空 → agent.attachment.empty（含去导入文献库/工作区的指引）
```

---

## 5. 双模式渲染交互

### 5.1 模式切换的同步点

1. 取**当前视口内第一个可见 `sentenceId`**：以中栏滚动容器的 `getBoundingClientRect()` 上边界向下 8px 为扫描线，取第一个 `rect.bottom > scanline` 的 `span[data-sentence-id]`（无 span 时取最近的块 `data-block-id`）。
2. 切到目标模式后，把该 `sentenceId` 对应元素滚动到**扫描线下方 24px**处（`scrollIntoView({block:'start'})` 后再补偿 24px）。
3. **误差 ≤ 1 段**（"段"= `Paragraph`）：若目标模式中该 `sentenceId` 不存在（例如 `abandon` 块、或被 patch 合并/拆分），则回退到其所属 `paragraphId` 的第一个存在句子；再失败则回退到同页首个句子，并 toast `reader.error.anchorNotFound`。
4. 切换期间 `AnchorBus.scrollLock = 'none' → 'target'`，锁定 300 ms 防止双向同步抖动。
5. 模式切换**不重建** `AnchorBusProvider`（避免丢选中与滚动静默状态）。

### 5.2 滚动同步算法（节流 100 ms + 双向防抖）

```ts
// use-anchor-sync.ts —— 常量冻结：THROTTLE_MS=100, DEBOUNCE_MS=120, EPS_PX=4, SYNC_OFFSET_PX=24
// 事件处理顺序（必须完全一致）：
// 1) 若 bus.scrollLock !== 'none' 且 !== source → 直接 return（目标方不回声，双向防抖）
// 2) 若 |scrollTop − lastSyncedTop[source]| < EPS_PX → return（微小位移不触发）
// 3) throttle(100ms)：置 bus.scrollLock = source → jumpTo(other(source), topSentenceId, 24)
//    → setTimeout(120ms) 后置 bus.scrollLock = 'none'
export function onScroll(source: 'original' | 'reflow', topSentenceId: string, scrollTop: number): void;
```

硬规则：
- S-1：`scroll` 监听必须 `{passive: true}`；重排视图用 `content-visibility: auto` + `contain-intrinsic-size: 0 400px`。
- S-2：**用户主动滚动优先**——300 ms 内的新用户滚动立即取消程序化滚动（`cancelAnimationFrame`）。
- S-3：同步跳转不改变持久化目标；持久化始终取**中栏视口首个句子**。
- S-4：滚动期间不触发翻译调度；调度仅在滚动停止 400 ms 后按视口范围触发。

### 5.3 `OriginalPane` 高亮落框规则

- 数据源唯一：`anchor.rects`（`Annotation.anchor` 或由 `Sentence.lines → Block.rect` 派生），单位 PDF pt；落框公式 `left = rect.x*scale + pageOffsetX`、`top = rect.y*scale + pageOffsetY`、`width = rect.w*scale`、`height = rect.h*scale`，高亮层为页面内 `position:absolute; inset:0; pointer-events:none` 容器。
- H-1：高亮层容器与 `canvas` 同尺寸、共用同一 `transform: scale()` 上下文；**禁止**用 `getBoundingClientRect` 反算（受 CSS 变换影响会漂移）。
- H-2：`scale` 变化只重算 CSS 变量 `--fr-rect-x/y/w/h`，不重建 DOM 节点。
- H-3：`rects` 为空 → 不画框，记 `warn: anchor.rects.empty`，不抛错。
- H-4：跨页标注必须按 `page` 分组分别落在各页容器内，禁止用一个绝对定位层跨页。
- H-5：`rects` 超出 `pageSize`（突破 INV-4 容差）→ 按 `pageSize` 裁剪渲染并记 `warn`。
- H-6：点击重排句子 → 原文对应 `rects` 闪烁高亮 **800 ms**（`animation: fr-flash 800ms ease-out 1`，`prefers-reduced-motion: reduce` 时改为 800 ms 静态描边），同时把该页滚动到可见（`block:'center'`）。

---

## 6. 状态机

### 6.1 阅读会话（`ReaderSessionState`）

```
opening ──ok──► ready
   │             ▲
   ├─needsParse─► parsing ──done──► ready
   │                │
   │                ├─failed──► failed(可重试/降级)
   │                └─cancel──► ready(原文模式 only)
   └─error────► failed ──retry──► opening
ready ──unmount/close──► closed（保存位置）
```

| 态 | UI 表现 | 可执行动作 |
|---|---|---|
| `opening` | 骨架屏（`Skeleton`×3 段落），中栏显示 `library.loading` | 取消（返回库） |
| `parsing` | `QuickModeBanner` 位置显示进度条（`aria-busy`），显示 `reader.parse.progress`（`{percent}` 与批次数） | 取消（`fr:parser:cancel`）、切到原文模式先读 |
| `ready` | 正常阅读；`StatusBar` 显示引擎与置信统计 | 全部 |
| `failed` | `ErrorState`：错误码 + `i18nKey` 文案 + 建议动作按钮（重试 / 打开设置 / 打开诊断 / 导出日志） | 重试、降级到 `rule` 引擎、返回库 |
| `closed` | 无（组件卸载） | — |

硬规则：`failed` 时**原文模式仍可读**（本地优先 P1）；只有 PDF 本身不可读才全屏错误页。

### 6.2 解析进度态（对接 `04-parser-sidecar.md`）

`ParseUiState = { state: 'queued'|'running'|'done'|'failed'; progress: number; batch?: {done:number;total:number}; engine: ParserEngineName; errorCode?: string }`

| state | UI 表现 |
|---|---|
| `queued` | 进度条 indeterminate + `reader.parse.queued`（含队列位次） |
| `running` | 进度条 determinate（`progress` 0–1，来自 `fr:parser:progress` 事件）+ 取消按钮；> 500 页时额外显示 `reader.parse.batch`（`{done}/{total}` 批） |
| `done` | 进度条淡出 300 ms，重排视图可切；`QuickModeBanner` 若 `engine==='rule'` 则显示 |
| `failed` | 中栏 `ErrorState` + 原文模式兜底；错误码见 `11-error-handling.md`（`FR-PARSE-*`） |

### 6.3 翻译进度态

`TranslateUiState = { state: 'idle'|'running'|'paused'|'done'|'failed'; scope: 'sentence'|'paragraph'|'document'; done: number; total: number; providerId: string|null }`

- `running`：`TranslationPanel` 顶部线性进度条 + 「取消」；每个已译段落就地插入 `<span class="fr-translation">`（**流式渲染**，不等待全部完成）。
- 单段失败不阻塞整体：该段显示 `translation.paragraphFailed` + 「重试本段」，`TranslateUiState` 保持 `running`。
- 全部失败（Provider 不可用）：`failed`，面板显示 `translation.providerMissing` + 「打开设置」；正文保持原文（降级矩阵见 `11-error-handling.md §5`）。
- `paused`：因窗口失焦/网络中断自动暂停时（`FR-TRANS-005`），显示「继续」。

### 6.4 Agent run（`AgentRunUiState`）

UI 状态名与 `14-agent.md` §3.1 的 run 状态机**同名**，不得另起名称；唯一新增的是 UI 专用的 `idle`（对应 §3.1 图起点）。

```ts
export type AgentRunUiState =
  | 'idle'                                                                   // 无活动 run（UI 专用）
  | 'planning' | 'acting' | 'observing' | 'waiting_user'                      // 活动态（离开需二次确认，R-5）
  | 'finished' | 'canceled' | 'failed';
export interface AgentRunView {
  state: AgentRunUiState; steps: number; toolCalls: number; reason?: string | null; errorCode?: string;
}
```

| 态 | UI 表现 | 可执行动作 | 错误码占位（`14-agent.md` §12） |
|---|---|---|---|
| `idle` | 输入框可用；`AgentStatusBar` 显示模型/项目/会话；**无** `RunCancelButton` | 发送（`Cmd/Ctrl+Enter`）、加附件、切会话、改权限、删除会话 | — |
| `planning` | 输入框只读；中栏插入 assistant 占位气泡（`agent.state.planning`，`aria-busy="true"`）；出现 `RunCancelButton` | 取消 run（`Esc` → 二次确认） | `FR-AGT-001`（未配置 Provider）、`FR-AGT-002`（模型调用失败/超时） |
| `acting` | 工具卡片按 `seq` 逐张出现：`running` = 风险图标 + `agent.tool.<camel>.name` + 参数摘要 + 1 s 节流计时；`write`/`execute` 前可能弹 `PermissionDialog` | 取消 run、展开卡片、打开权限面板、`Cmd/Ctrl+Shift+P` | `FR-AGT-003`（拒绝）、`FR-AGT-004`（参数非法）、`FR-AGT-005`（执行失败）、`FR-AGT-008`（越界被拦） |
| `observing` | 对应卡片转 `ok` 并显示结果摘要与耗时；状态文案 `agent.state.observing`；`steps` / `toolCalls` 随 `run_state` 载荷刷新 | 取消 run、展开卡片、跳转引用 | `FR-AGT-011`（上下文超预算且无法压缩） |
| `waiting_user` | 两种形态：① `ask_user` → 输入框高亮 + 自动聚焦（`agent.state.waitingUser`）；② 权限 `ask` → `PermissionDialog`（120 s 倒计时）。阅读器**不阻塞**（§3.4 L-6） | 回答并发送、四选项授权、取消 run | `FR-AGT-003`（120 s 未响应 = 本次 run 的 `deny`，不写盘） |
| `finished` | 最终答复 + `CitationList`（`agent.citation.title`）；`run_state.payload.verified === false` 时答复标注 `agent.unverified`（AG-10）；`agent.state.finished`；输入框恢复可用 | 复制答复、打开引用文献、继续追问、删除会话 | `FR-AGT-010`（会话事件行损坏 → 显示 `agent.error.sessionCorrupt`，不整页崩溃） |
| `canceled` | 已有消息与工具卡片**全部保留**（AG-6）；顶部提示 `agent.state.canceled` + toast `agent.cancel.done`；`RunCancelButton` 消失 | 继续追问、重试本次提问、复制已产出、导出笔记 | `FR-AGT-007` |
| `failed` | 中栏尾部错误卡片 = 错误码 + 文案 + 建议动作（`ErrorState` 的行内变体）；**保留已产出** | 重试本次提问、打开设置（Provider）、打开权限面板、导出日志；**`FR-AGT-008` 为 fatal 安全事件，不提供重试入口**（仅导出日志/上报） | `FR-AGT-002`、`FR-AGT-005`、`FR-AGT-006`、`FR-AGT-008`、`FR-AGT-011`、`FR-AGT-012`，兜底 `FR-SYS-001` |

**硬规则**：

- A-1：状态只由 `fr:agent:event{kind:'run_state'}` 的 `payload.state` 驱动，只能按 §3.1 的箭头迁移；唯一例外是`fr:agent:send` 响应中的 `state`（受理时恒为 `planning`）作为初始值。出现非法迁移（如 `finished → acting`）→ 记 `warn: agent.runState.invalid` 并**以事件为准**，不崩溃、不回滚 UI。
- A-2：取消是**请求**而非状态：点击后进入 `pending`（按钮 disabled + `aria-busy`），只有收到 `run_state=canceled`（或 `failed`）才切换状态，禁止乐观切换到 `canceled`。
- A-3：同一错误码只提示一次（去重键 = `callId`，无 `callId` 时用 `seq`）；错误卡片与 toast 不得重复播报。
- A-4：会话重进（R-8）若 `fr:agent:getSession` 返回的最后 `run_state` 是活动态 → 直接恢复该态，并在 `/agent` 顶部显示 `agent.status.background` + 「返回会话」。
- A-5：`waiting_user` 且用户离开会话（R-5 选「后台继续」）时，倒计时**继续**；超时按 `deny`（本次 run）处理后 run 回到 `acting`/`failed`，状态栏同步更新。
- A-6：UI 不得显示 `14-agent.md` §12 之外的错误码；未登记的码一律按 `FR-SYS-001`（`common.error.unknown`）兜底展示，并在 `details.code` 中保留原码原文（便于导出日志）。
- A-7：**回放真源 = `fr:agent:getSession`**（`events` / `lastSeq` / `hasMore` / `unparsableLines`）；`fr:agent:event` 只是实时通知。两者冲突时以 `getSession` 为准（AG-7：事件流只追加、可完整回放）。

---

## 7. 键盘与鼠标

### 7.1 快捷键表（V1 冻结）

| 键 | 动作 | 作用域 | 冲突处理 |
|---|---|---|---|
| `j` / `k` | 下一条 / 上一条句子 | 阅读区 | 选中并滚动到可见；同时更新阅读位置 |
| `n` / `p` | 下一段 / 上一段 | 阅读区 | 段落粒度，跨模式等效 |
| `t` | 显示/隐藏译文 | 阅读区 | 切换 `translationMode: off ↔ paragraph` |
| `o` | 切换 原文 / 重排 | 阅读区 | 走 §5.1 同步点规则 |
| `h` | 高亮当前句 | 阅读区 | 译文模式（`only`）下禁用并 toast `notes.translationDisabled` |
| `m` | 为当前句加笔记 | 阅读区 | 打开 `NotesPanel` 并聚焦输入框 |
| `/` | 打开 `SearchPalette`（库内检索） | 全局 | 阅读区内打开的是页内查找（`document` scope） |
| `Cmd/Ctrl+F` | 页内查找 | 阅读区 | 重排模式查 DOM 文本；原文模式查文本层 |
| `Esc` | 关闭最上层浮层（面板→浮层→查找条→选中） | 全局 | 逐层关闭，一次一层 |
| `Cmd/Ctrl+O` | 打开 `ImportDialog` | 全局 | 文件选择器走 `fr:library:import` |
| `1` / `2` / `3` | 左栏 / 右栏 / 双栏 面板切换 | 阅读区 | `1`=左栏循环三种面板；`2`=右栏循环；`3`=同时收起/展开双栏 |
| `Cmd/Ctrl+,` | 打开 `/settings` | 全局 | — |
| `Cmd/Ctrl+W` | 关闭当前文档（回 `/library`） | 阅读区 | 不关闭窗口 |
| `←` / `→` | 分隔条聚焦时调整宽度 ±8px | 分隔条 | `role="separator"` + `aria-valuenow` |
| `g g` / `G` | 跳到文首 / 文末 | 阅读区 | 序列键，800 ms 内有效 |

### 7.2 输入态抑制规则（必须实现）

```ts
// 文本输入态判定：命中任一条件即为 true —— ① isContentEditable；② tagName ∈ {input, textarea, select}；
// ③ closest('[data-fr-keyscope="text"]') !== null；④ 非 HTMLElement → false。
export function isTypingTarget(el: EventTarget | null): boolean;
// 为 true 时单字符快捷键（j k n p t o h m / 1 2 3 g G）一律不触发；组合键（Cmd/Ctrl+*、Esc）仍生效。
// Esc 在文本域中的例外：先失焦（blur）并保存内容，再冒泡到全局 Esc 处理。
```

- 输入焦点必须可见：`:focus-visible { outline: 2px solid var(--fr-accent); outline-offset: 2px }`，禁止 `outline: none` 而无替代。
- 鼠标：单句单击 = 选中并同步（不弹菜单）；`contextmenu` = 块级菜单（纠错/复制/翻译本段/加笔记）；双击 = 选词（系统选区，用于划词翻译）。

### 7.3 Agent 视图快捷键（V1 冻结）

> 本节为 Agent 作用域新增；§7.1 的 `Esc` 行在 Agent 视图内按本节的**层序**解释（更具体的规则优先）。

| 键 | 动作 | 作用域 | 冲突处理 |
|---|---|---|---|
| `Cmd/Ctrl+Enter` | **发送**当前输入（含附件） | Agent 输入区 | 输入为空 / 存在活动 run / 无可用 Provider 时禁用（不发送空消息）；`isComposing === true`（输入法组合中）不触发 |
| `Esc` | **取消 run（需二次确认）** | Agent 视图 | 仅在存在活动 run 且无更上层浮层时触发；层序见下 |
| `Cmd/Ctrl+K` | **切换会话**（打开 `SessionList` 的搜索态并聚焦） | Agent 视图 | dock 形态要求焦点在面板内（§3.4 L-7）；与 `/`（库检索）不冲突 |
| `Cmd/Ctrl+Shift+P` | **打开权限面板**（右栏切到「权限」页签并聚焦 `ToolPermissionPanel`） | Agent 视图 | 页面形态直接生效；dock 形态先展开右栏页签再聚焦 |
| `1` `2` `3` `4` | `PermissionDialog` 打开时选择四个选项（1=允许一次 / 2=总是允许 / 3=本次全部允许 / 4=拒绝） | 权限弹窗 | 仅弹窗打开时生效；受 `isTypingTarget` 抑制 |
| `Cmd/Ctrl+.` | 停止流式渲染（已到达文本定型） | Agent 视图 | **只停渲染，不取消 run**；取消 run 必须走 `Esc` + 二次确认 |
| `Backspace` | 删除输入区最后一个附件 chip | Agent 输入区 | 仅当输入框为空时生效 |
| `↑` / `↓` | 输入框为空时在消息引用项之间移动焦点 | Agent 中栏 | 不改变中栏的键盘滚动语义 |

**`Esc` 层序（必须按序判定，一次只处理一层）**：

1. `PermissionDialog` 打开 → 等同**「拒绝」**（`deny`，仅本次 run，不写盘）并关闭；
2. `ConfirmDialog` 打开 → 取消该确认（= 「留在本页」）；
3. 会话切换器 / `ModelPicker` / `AttachmentPicker` 打开 → 关闭该浮层；
4. dock 形态且 Agent 面板为 overlay（视口 ≤ 1280，§3.4 L-4）→ 关闭 overlay（回到阅读器）；
5. 存在活动 run（`planning` / `acting` / `observing` / `waiting_user`）→ 打开取消确认（`agent.cancel.confirm*`，R-5）；
6. 焦点在 Agent 输入框内且无活动 run → `blur` 并**保留草稿**。

**抑制规则**：`isTypingTarget(el)`（§7.2）为 `true` 时，`1..4`、`Backspace`、`↑/↓` 一律不触发；组合键（`Cmd/Ctrl+Enter`、`Cmd/Ctrl+K`、`Cmd/Ctrl+Shift+P`、`Cmd/Ctrl+.`、`Esc`）仍生效。**Agent 视图不新增任何单字符快捷键**，避免与阅读器的 `j/k/n/p/t/o/h/m` 冲突。

---

## 8. 无障碍（WCAG 2.1 AA 基线）

| # | 要求 | 判据 |
|---|---|---|
| A1 | 全部交互元素可聚焦、可操作 | Tab 顺序 = DOM 顺序；无 `tabindex="-1"` 的可交互元素；分隔条 `role="separator"` + `aria-orientation="vertical"` + `tabindex="0"` |
| A2 | `aria-label` 一律使用 i18n key 的**解析结果**（`t('reader.toolbar.translate')`），禁止硬编码字符串 | ESLint 自定义规则 `fr/a11y-i18n-label` 阻断字面量 |
| A3 | 颜色对比度 ≥ 4.5:1（正文）、≥ 3:1（大字号/图形边界） | 令牌表已按此选值；CI 用 `axe-core` + `@axe-core/playwright` 扫描 `/library`、`/reader`、`/settings`、`/agent`、`/project/:projectId` 零 `serious`/`critical` |
| A4 | 阅读区提供"仅键盘"跳转 | `Tab` 可进入阅读区（`tabindex="0"`，`role="document"`），进入后 `j/k` 逐句、`n/p` 逐段；`aria-live="polite"` 播报当前句 `Sentence.text` 前 80 字符 |
| A5 | 动效遵循 `prefers-reduced-motion` | 该媒体查询为 `reduce` 时：关闭骨架屏 shimmer、关闭 800 ms 闪烁（改静态描边）、滚动同步改为瞬时跳转（`behavior:'auto'`） |
| A6 | 状态变化可被读屏感知 | 解析/翻译进度用 `role="progressbar"` + `aria-valuenow/min/max`；toast 用 `role="status"`；致命错误用 `role="alert"` |
| A7 | 主题不影响语义 | 暗色模式仅为 CSS 变量覆盖，禁止改变 DOM 结构或文案 |
| A8 | 字号可放大至 200% 不破版 | 中栏 `max-width: 72ch`，字号放大时按 `rem` 等比；横向不出现滚动条 |
| A9 | **对话流为 `aria-live="polite"`** | 会话流容器 = `role="log"` + `aria-live="polite"` + `aria-relevant="additions text"`；流式消息在定型前 `aria-busy="true"`，读屏只播报定型后的完整段落（**不得逐字播报**）；run 状态变化用 `role="status"`，运行失败用 `role="alert"` |
| A10 | **工具卡片可聚焦且有状态描述** | 每张 `ToolCallCard`：`tabindex="0"` + `role="group"` + `aria-label` = 工具展示名 + 状态文案 + 风险等级（三者均为 i18n 解析结果，A2）；参数摘要与耗时经 `aria-describedby` 关联到同一节点；`Enter`/`Space` 切换展开；`rejected` 与 `failed` 的 `aria-label` 必须不同 |
| A11 | **权限弹窗为 `role="alertdialog"` 且键盘完全可操作** | `role="alertdialog"` + `aria-modal="true"` + `aria-labelledby`/`aria-describedby`；**焦点陷阱**：`Tab`/`Shift+Tab` 只在弹窗内循环、初始焦点在「拒绝」（安全默认）；`Esc` = 拒绝；倒计时容器 `aria-live="off"`，仅在剩余 **30 s** 与 **10 s** 各播报一次（禁止每秒播报）；四个选项 + 「查看工具详情」均可纯键盘到达并激活 |
| A12 | **Agent 主路径可"仅键盘"完成** | 打开 `/agent` → 切会话（`Cmd/Ctrl+K`）→ 输入 → 发送（`Cmd/Ctrl+Enter`）→ 授权（`1..4`）→ 取消（`Esc` + 确认）→ 打开引用（`Tab` + `Enter`）全链路无鼠标；dock 形态下同一链路在面板内可达（L-7） |

---

## 9. i18n 与文案（V1 必备 key 清单）

命名：`<area>.<component>.<key>`；文件 `apps/desktop/src/renderer/i18n/{zh-CN,en}.json`。**下表 zh-CN 文案为冻结值**（`{x}` 为 ICU 参数）。

### 9.1 `common.*`（通用）

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|---|---|---|---|
| `common.action.confirm` | 确定 | `common.action.cancel` | 取消 | `common.action.retry` | 重试 | `common.action.close` | 关闭 |
| `common.action.undo` | 撤销 | `common.action.export` | 导出 | `common.action.delete` | 删除 | `common.state.loading` | 加载中… |
| `common.state.offline` | 当前处于离线状态，本地功能不受影响 | `common.error.unknown` | 出现未知错误，已记录日志 |  |  |

### 9.2 `library.*`（文献库）

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|---|---|---|---|
| `library.empty.title` | 文献库还是空的 | `library.empty.hint` | 把 PDF 拖进来，或按 {shortcut} 导入 | `library.empty.action` | 导入论文 | `library.loading` | 正在读取文献库… |
| `library.list.count` | 共 {count} 篇 | `library.filter.noResult` | 没有符合当前筛选条件的文献 | `library.import.progress` | 正在导入（{done}/{total}）：{name} | `library.import.done` | 已导入 {count} 篇 |
| `library.import.skippedDuplicate` | 已跳过 {count} 个重复文件 | `library.import.skippedUnsupported` | 已跳过 {count} 个不支持的文件 | `library.import.cancelled` | 导入已中止 | `library.item.missing` | 文件已不在原路径 |
| `library.item.relocate` | 重新定位文件 | `library.search.placeholder` | 搜索标题、作者、摘要或全文 | `library.search.empty` | 没有找到匹配的文献 |  |

### 9.3 `reader.*`（阅读器与横幅）

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|---|---|---|---|
| `reader.loading` | 正在打开文档… | `reader.toolbar.modeOriginal` | 原文 | `reader.toolbar.modeReflow` | 重排 | `reader.toolbar.translate` | 翻译 |
| `reader.toolbar.notes` | 笔记 | `reader.toolbar.outline` | 大纲 | `reader.toolbar.thumbnails` | 缩略图 | `reader.toolbar.zoomIn` | 放大 |
| `reader.toolbar.zoomOut` | 缩小 | `reader.toolbar.fullscreen` | 全屏 | `reader.banner.quickMode` | 快速模式：未检测到解析引擎，当前使用内置规则排版，结构精度可能下降 | `reader.banner.quickMode.action` | 安装解析引擎 |
| `reader.banner.ocrQuality` | 该文件为扫描件，质量可能不佳 | `reader.banner.offlineDegraded` | 当前离线，已为你使用本地排版与缓存译文 | `reader.banner.positionRestoredDegraded` | 未能精确恢复上次位置，已定位到该段落所在页 | `reader.parse.queued` | 解析排队中（第 {position} 位） |
| `reader.parse.progress` | 正在解析… {percent}% | `reader.parse.batch` | 分批解析中：第 {done}/{total} 批 | `reader.parse.cancel` | 取消解析 | `reader.parse.failedHint` | 可先用原文模式阅读，或重试解析 |
| `reader.lowConfidence.hint` | 低置信区域（{score}%），点击可修正排版 | `reader.lowConfidence.count` | 本文有 {count} 处低置信区域 | `reader.patch.saved` | 排版修正已保存，正在重新渲染 | `reader.error.anchorNotFound` | 未能在目标模式中定位该位置，已跳到相近段落 |
| `reader.status.engine` | 解析引擎：{engine} | `reader.status.page` | 第 {page} / {total} 页 | `reader.status.saving` | 正在保存阅读位置… | `reader.status.saved` | 阅读位置已保存 |

### 9.4 `notes.*` / `translation.*`

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|---|---|---|---|
| `notes.empty` | 还没有笔记，选中句子后按 {shortcut} 添加 | `notes.panel.title` | 笔记与高亮 | `notes.action.addHighlight` | 高亮当前句 | `notes.action.addNote` | 添加笔记 |
| `notes.action.exportMarkdown` | 导出为 Markdown | `notes.translationDisabled` | 该文章无法在译文中添加高亮或笔记，请切回原文或对照模式 | `translation.empty` | 尚未翻译，选择「翻译本段」或「翻译全文」开始 | `translation.panel.title` | 对照翻译 |
| `translation.action.translateCurrent` | 翻译本段 | `translation.action.translateAll` | 翻译全文 | `translation.action.cancel` | 取消翻译 | `translation.progress` | 正在翻译 {done}/{total} 段 |
| `translation.paragraphFailed` | 本段翻译失败 | `translation.providerMissing` | 尚未配置翻译服务 | `translation.providerMissing.action` | 打开翻译设置 | `translation.lang.sameAsSource` | 检测到目标语言与原文语言相同 |
| | `translation.glossary.conflict` | 术语表存在冲突词条：{term} | |

### 9.5 `settings.*` / `doctor.*`

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|---|---|---|---|
| `settings.title` | 设置 | `settings.parser.engine` | 解析引擎 | `settings.parser.ocr` | 扫描件 OCR | `settings.translate.provider` | 翻译服务 |
| `settings.translate.apiKeyHint` | 密钥保存在系统凭据库，不写入配置文件 | `settings.appearance.theme` | 主题 | `settings.appearance.themeSystem` | 跟随系统 | `settings.appearance.fontSize` | 正文字号 |
| `settings.cache.usage` | 缓存占用 {size}，上限 {limit} | `settings.cache.clear` | 清理缓存 | `settings.logs.export` | 导出日志（导出前自动脱敏） | `settings.shortcuts.title` | 快捷键 |
| `doctor.title` | 诊断 | `doctor.check.sidecar` | 解析引擎状态 | `doctor.check.database` | 索引数据库完整性 | `doctor.check.index` | 文件与索引一致性 |
| `doctor.action.rebuildIndex` | 重建索引 | `doctor.action.restartSidecar` | 重启解析引擎 | `doctor.report.export` | 导出诊断报告 |  |

### 9.6 `agent.*` / `project.*` / `permission.*`（Agent 与项目工作区 · V1 新增 132 条）

> **工具 key 冻结规则**：14 个工具的展示名 key = `agent.tool.<camelName>.name`，描述 key = `agent.tool.<camelName>.desc`，其中 `<camelName>` = 工具名去下划线转小驼峰（`search_library` → `searchLibrary`）。映射表见 9.6.5，**代码不得硬编码工具文案**（C-5）。

**9.6.1 会话与视图（12）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `agent.view.title` | 研究助手 | `agent.session.new` | 新建会话 |
| `agent.session.list.title` | 会话 | `agent.session.switch` | 切换会话 |
| `agent.session.delete` | 删除会话 | `agent.session.deleteConfirm` | 删除该会话？删除后不可恢复 |
| `agent.session.retention` | 会话默认保留 {days} 天 | `agent.empty.sessions` | 还没有会话，输入问题开始第一个研究会话 |
| `agent.input.placeholder` | 针对你的文献库提问，或描述要做的事 | `agent.action.send` | 发送 |
| `agent.action.copy` | 复制 | `agent.action.openSettings` | 打开设置 |

**9.6.2 运行状态与状态栏（11）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `agent.state.planning` | 思考中… | `agent.state.acting` | 正在执行 {tool} |
| `agent.state.observing` | 正在整理工具结果… | `agent.state.waitingUser` | 等待你的回答 |
| `agent.state.finished` | 已完成 | `agent.state.canceled` | 已取消 |
| `agent.state.failed` | 运行失败 | `agent.status.run` | 步骤 {steps}/{maxSteps} · 工具调用 {calls}/{maxCalls} |
| `agent.status.model` | 模型：{model} | `agent.status.background` | 「{title}」正在后台运行 |
| `agent.status.backToSession` | 返回会话 |  |  |

**9.6.3 取消与二次确认（6）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `agent.cancel.run` | 取消运行 | `agent.cancel.done` | 已取消运行，已产出的消息、笔记与文件均保留 |
| `agent.cancel.confirm` | 当前运行正在执行工具，可能已改动工作区文件；取消后已产出内容会保留 | `agent.cancel.confirmWaitingUser` | 当前运行正在等待你的回答或授权；取消后已产出内容会保留 |
| `agent.cancel.keepInBackground` | 后台继续 | `agent.cancel.stay` | 留在本页 |

**9.6.4 工具卡片（14）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `agent.tool.args` | 参数摘要 | `agent.tool.detail` | 查看详情 |
| `agent.tool.permission` | 权限设置 | `agent.tool.status.running` | 执行中 |
| `agent.tool.status.ok` | 已完成（{duration}） | `agent.tool.status.failed` | 执行失败（{code}） |
| `agent.tool.status.rejected` | 未获授权 | `agent.tool.status.canceled` | 已取消 |
| `agent.tool.sideEffect.none` | 无副作用 | `agent.tool.sideEffect.read` | 只读 |
| `agent.tool.sideEffect.write` | 会写入文件 | `agent.tool.sideEffect.network` | 会联网 |
| `agent.tool.sideEffect.execute` | 会执行代码 | `agent.tool.unavailable` | 该工具当前不可用（依赖缺失，如沙箱或网络） |

**9.6.5 14 个工具的展示名与描述（28）**

| 工具名 | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|---|
| `search_library` | `agent.tool.searchLibrary.name` | 检索文献库 | `agent.tool.searchLibrary.desc` | 在本地文献库中全文检索，返回命中的文献与片段 |
| `get_document_outline` | `agent.tool.getDocumentOutline.name` | 读取文档大纲 | `agent.tool.getDocumentOutline.desc` | 获取文献的章节大纲与结构统计 |
| `read_document` | `agent.tool.readDocument.name` | 精读文档段落 | `agent.tool.readDocument.desc` | 按段落窗口读取文献正文 |
| `read_notes` | `agent.tool.readNotes.name` | 读取笔记与标注 | `agent.tool.readNotes.desc` | 读取指定文献或库范围内的笔记与高亮 |
| `write_note` | `agent.tool.writeNote.name` | 写入笔记 | `agent.tool.writeNote.desc` | 新增笔记或标注（锚点必须有效） |
| `resolve_metadata` | `agent.tool.resolveMetadata.name` | 解析文献元数据 | `agent.tool.resolveMetadata.desc` | 由 DOI、arXiv 编号或标题补全元数据 |
| `search_open_access` | `agent.tool.searchOpenAccess.name` | 检索开放获取版本 | `agent.tool.searchOpenAccess.desc` | 在合规白名单来源中查找可公开获取的 PDF |
| `import_pdf` | `agent.tool.importPdf.name` | 导入 PDF | `agent.tool.importPdf.desc` | 把开放获取链接或本地文件导入文献库 |
| `workspace_list` | `agent.tool.workspaceList.name` | 列出工作区文件 | `agent.tool.workspaceList.desc` | 列出项目工作区中的文件 |
| `workspace_read` | `agent.tool.workspaceRead.name` | 读取工作区文件 | `agent.tool.workspaceRead.desc` | 读取工作区中的文本文件（上限 256 KiB） |
| `workspace_write` | `agent.tool.workspaceWrite.name` | 写入工作区文件 | `agent.tool.workspaceWrite.desc` | 新建或覆盖工作区内的文件 |
| `run_python` | `agent.tool.runPython.name` | 运行 Python | `agent.tool.runPython.desc` | 在本地沙箱中执行 Python 计算或绘图（无网络） |
| `ask_user` | `agent.tool.askUser.name` | 向你提问 | `agent.tool.askUser.desc` | 意图不明确时向你提问以澄清 |
| `finish` | `agent.tool.finish.name` | 结束并给出结论 | `agent.tool.finish.desc` | 结束本次运行并给出最终答复与引用 |

**9.6.6 权限（18）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `permission.dialog.title` | 工具调用授权 | `permission.panel.title` | 工具权限 |
| `permission.option.allowOnce` | 允许一次 | `permission.option.alwaysAllow` | 总是允许 |
| `permission.option.allowAllOnce` | 本次全部允许 | `permission.option.deny` | 拒绝 |
| `permission.timeout` | 剩余 {seconds} 秒，超时将自动拒绝（仅本次运行，不修改权限设置） | `permission.defaultDenyNote` | 未做选择时按「拒绝」处理 |
| `permission.scope.once` | 仅本次运行有效 | `permission.scope.always` | 写入项目权限设置，永久有效 |
| `permission.scope.ask` | 每次调用都询问 | `permission.scope.deny` | 永久拒绝，之后同一工具不再询问 |
| `permission.risk.low` | 风险低：只读或无副作用 | `permission.risk.medium` | 风险中：会联网（有出站审计） |
| `permission.risk.high` | 风险高：会写入文件或执行代码 | `permission.batch.hint` | 本次运行内后续同类写入将不再询问 |
| `permission.denied.hint` | 该工具已被拒绝（{code}），可在权限面板改回 | `permission.panel.empty` | 没有可设置的工具 |

**9.6.7 模型与能力边界（6）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `agent.model.picker` | 模型 | `agent.model.none` | 还没有可用的模型，先配置一个再开始提问 |
| `agent.model.none.action` | 打开模型设置 | `agent.model.unsupportedTools` | 当前模型不支持原生工具调用，已改用文本解析模式，可靠性下降 |
| `agent.capability.browserNotInV1` | V1 不支持浏览器自动化与网页抓取；联网仅限开放获取白名单来源 | `agent.model.lockedDuringRun` | 运行中不能切换模型，将在下次提问生效 |

**9.6.8 引用来源、附件与可信度（10）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `agent.citation.title` | 引用来源 | `agent.citation.empty` | 本次答复没有引用任何工具结果 |
| `agent.citation.open` | 打开该文献 | `agent.citation.toolCall` | 来自工具调用：{tool} |
| `agent.attachment.add` | 添加附件 | `agent.attachment.remove` | 移除附件 |
| `agent.attachment.empty` | 没有可添加的文献或工作区文件 | `agent.attachment.tooLarge` | 该附件内容超过 8,000 字符上限，已截断 |
| `agent.unverified` | 未经验证：该结论未引用任何工具结果 | `agent.injection.suspected` | 工具结果中可能包含指令注入，已按不可信数据处理 |

**9.6.9 项目工作区与技能（17）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `project.fileTree.title` | 工作区文件 | `project.fileTree.empty` | 工作区还是空的，可导入文件，或让 Agent 写入 |
| `project.fileTree.import` | 导入文件 | `project.fileTree.truncated` | 文件过多，仅显示前 {count} 项 |
| `project.fileTree.askAbout` | 就该文件提问 | `project.permission.entry` | 权限设置 |
| `project.export` | 导出项目 zip | `project.export.note` | 导出内容含项目信息、工作区与技能；不含权限设置与会话记录 |
| `project.empty` | 还没有项目工作区 | `project.empty.action` | 新建项目 |
| `project.unavailable` | 项目工作区不可用，可能已被移动或没有访问权限 | `project.unavailable.action` | 重新定位项目 |
| `project.session.title` | 本项目会话 | `agent.skill.title` | 技能 |
| `agent.skill.install` | 安装技能 | `agent.skill.scriptsNotExecuted` | V1 不会执行技能内的脚本 |
| `agent.empty.skills` | 还没有安装技能，可从本地目录安装 |  |  |

**9.6.10 错误兜底（10）**

| key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN | key ↔ zh-CN |
|---|---|---|---|
| `agent.error.unknown` | 运行出错了，已记录日志 | `agent.error.retry` | 重试本次提问 |
| `agent.error.details` | 查看错误详情 | `agent.error.provider` | 尚未配置可用的模型服务 |
| `agent.error.permissionDenied` | 该操作未获授权 | `agent.error.outOfBounds` | 该访问超出允许范围，已阻止 |
| `agent.error.stepLimit` | 已达到步数或工具调用上限，已提前结束并保留产出 | `agent.error.budget` | 上下文超出预算且无法继续压缩 |
| `agent.error.workspace` | 项目工作区不可用，可能已被移动或没有访问权限 | `agent.error.sessionCorrupt` | 部分会话事件无法解析，已跳过 |

> `agent.error.*` 为 `14-agent.md` §12 各错误码的**兜底文案面**（不替代 `11-error-handling.md` 的 `errors.FR-AGT-*` key）：错误卡片主文案取 `errors.<code>`，其下的「建议动作」与降级说明取 `agent.error.*`；两者都缺失时用 `agent.error.unknown`（§6.4 A-6）。

> **总量校验**：以上共 **208 条** ＝ 原 76 条 + Agent 域 **132 条**（要求 ≥ 60，Agent 域要求 ≥ 30）。新增 key 必须同步 `en.json`，缺失即 `pnpm i18n:check` 失败（命令落地见 `AGENTS.md §4`）。Agent 域计数明细：会话与视图 12 + 运行状态 11 + 取消 6 + 工具卡片 14 + 工具名/描述 28 + 权限 18 + 模型与能力 6 + 引用/附件 10 + 项目/技能 17 + 错误兜底 10 = **132**。

---

## 10. 设计令牌（`--fr-*`）

定义于 `packages/ui/src/tokens.css`；暗色通过 `[data-theme="dark"]` 覆盖同名变量（A7）。

### 10.1 颜色（明 / 暗）

| 变量 | 明色 | 暗色 | 用途 |
|---|---|---|---|
| `--fr-bg` | `#ffffff` | `#14161a` | 应用背景 |
| `--fr-bg-subtle` | `#f5f6f8` | `#1b1e24` | 侧栏、卡片底 |
| `--fr-surface` | `#ffffff` | `#20242b` | 浮层、面板 |
| `--fr-border` | `#d8dbe0` | `#333a44` | 分隔线 |
| `--fr-text` | `#1a1d21` | `#e6e8ec` | 正文（对比度 ≥ 12:1） |
| `--fr-text-muted` | `#5a6169` | `#a3abb6` | 次要文本（≥ 4.6:1） |
| `--fr-accent` | `#1f5fd0` | `#6ea8fe` | 主色、链接、焦点 |
| `--fr-accent-weak` | `#e6eefc` | `#1d2b45` | 选中底 |
| `--fr-warn` | `#b25a00` | `#e0a458` | 低置信描边、警告 |
| `--fr-danger` | `#b3261e` | `#f2857d` | 错误 |
| `--fr-ok` | `#1f7a45` | `#5cc98a` | 成功 |
| `--fr-highlight` | `#ffe58a` | `#4a3f18` | 高亮底色 |
| `--fr-highlight-flash` | `#ffd24a` | `#6b5a20` | 800 ms 闪烁色 |
| `--fr-translation-text` | `#3a4048` | `#c3cad4` | 译文正文 |

### 10.2 间距 / 字号 / 行高 / 圆角 / 阴影 / 字体

```css
:root {
  /* 间距：4px 基准 */
  --fr-space-1: 4px;  --fr-space-2: 8px;  --fr-space-3: 12px;  --fr-space-4: 16px;  --fr-space-6: 24px;  --fr-space-8: 32px;
  /* 字号：12 / 14 / 16 / 18 / 21 / 26 */
  --fr-font-size-xs: 12px; --fr-font-size-sm: 14px; --fr-font-size-md: 16px;
  --fr-font-size-lg: 18px; --fr-font-size-xl: 21px; --fr-font-size-2xl: 26px;
  --fr-font-size-reader: var(--fr-font-size-lg);   /* 阅读区可调，设置项覆盖 */
  /* 行高：标题 1.25 ｜ UI 文本 1.5 ｜ 正文阅读 1.75 */
  --fr-line-tight: 1.25; --fr-line-normal: 1.5; --fr-line-reader: 1.75;
  /* 圆角 */
  --fr-radius-sm: 4px; --fr-radius-md: 8px; --fr-radius-lg: 12px; --fr-radius-pill: 999px;
  /* 阴影 */
  --fr-shadow-1: 0 1px 2px rgba(0,0,0,.08); --fr-shadow-2: 0 4px 12px rgba(0,0,0,.12); --fr-shadow-3: 0 12px 32px rgba(0,0,0,.18);
  /* 字体：中文优先栈 —— 先中文字体（避免 CJK 落到西文衬线），再西文兜底 */
  --fr-font-serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun",
                   "Linux Libertine", Georgia, "Times New Roman", serif;
  --fr-font-sans:  "Noto Sans SC", "Source Han Sans SC", "PingFang SC",
                   "Microsoft YaHei", "Segoe UI", system-ui, -apple-system, sans-serif;
  --fr-font-mono:  "JetBrains Mono", "Cascadia Mono", Consolas, "SFMono-Regular", monospace;
  /* 层级 */
  --fr-z-panel: 10; --fr-z-overlay: 100; --fr-z-popover: 200; --fr-z-toast: 300; --fr-z-modal: 400;
}
```

字体规则：重排正文用 `--fr-font-serif`（论文阅读舒适），UI 与库列表用 `--fr-font-sans`，公式（KaTeX）与代码用 `--fr-font-mono`；字体随包分发（子集化，参考调研报告 §3.1 的 `NotoSansSC-Subset` 做法），`font-display: swap`，**不得**依赖网络字体。

---

## 11. 空态与边界

| 场景 | UI 表现 | 可执行动作 | 关联错误码 |
|---|---|---|---|
| 文献库为空 | `EmptyState`（插图 + `library.empty.title/hint/action`），并接受整窗拖放 | 导入论文（`Cmd/Ctrl+O`） | — |
| 解析失败 | 中栏 `ErrorState`（错误码 + 文案 + 建议），原文模式仍可读 | 重试解析、切换 `rule` 引擎、打开诊断、导出日志 | `FR-PARSE-*`、`FR-ANCHOR-*` |
| 无 Python 环境（快速模式） | `QuickModeBanner`（`reader.banner.quickMode`），`StatusBar` 引擎显示 `rule`；低置信描边数量显著增多属预期 | 安装解析引擎（打开设置）、继续阅读（不阻塞） | `FR-PARSE-002`、`FR-PARSE-003` |
| 扫描件质量不佳 | 常驻 `reader.banner.ocrQuality`；OCR 文本覆盖率 < 60% 时重排默认折叠为原文模式并提示 | 切换原文模式、标记纠错区域 | `FR-PARSE-006`、`FR-PARSE-007` |
| 翻译 Provider 未配置 | `TranslationPanel` 显示 `translation.providerMissing` + 「打开翻译设置」；正文不显示译文位 | 打开设置、使用内置词典划词 | `FR-TRANS-001` |
| 离线 | 顶部细条 `common.state.offline`（4 s 后收起为状态栏图标）；翻译用缓存，OA 获取入口禁用并注明原因 | 继续本地阅读、查看缓存的译文 | `FR-NET-001` |
| 超大文档（> 500 页） | 打开前 `ConfirmDialog` 提示解析耗时与分批策略；**不直接拒绝**：先以原文模式打开，解析在后台按 50 页/批推进 | 立即读原文、后台解析、取消 | `FR-PARSE-009` |
| 磁盘空间不足 | 全屏阻断页（仅导入/解析/翻译写入类操作被阻断，阅读不受影响） | 清理缓存、更换缓存目录、导出日志 | `FR-STORE-001` |
| 索引损坏 | `/library` 顶部警告条 + 「打开诊断」，真源文件仍可读 | `fr:app:doctor`（`action: 'rebuildIndex'`）重建索引 | `FR-STORE-004`、`FR-STORE-005` |
| **Agent 首次进入（无会话/无项目/无技能）** | 中栏 `EmptyState`（`agent.empty.sessions`）；左栏 `SessionList` 空（`project.empty`）；右栏文件树 `project.fileTree.empty`、技能页 `agent.empty.skills`；`AgentBanner` 显示 `agent.capability.browserNotInV1` | 直接在输入框提问（自动 `fr:agent:start` 建会话）、`project.empty.action` 新建项目、`agent.skill.install` 安装本地技能 | — |
| **无可用 LLM Provider** | Agent 入口**可见**但中栏输入区替换为引导卡（`agent.model.none` + `agent.error.provider`）；`ModelPicker` 标注无可用项；发送能力禁用；`fr:agent:start` 返回 `llmReady: false`（会话仍创建）；历史会话仍可只读回放 | 打开设置配置 Provider（`agent.model.none.action`）、只读浏览历史会话 | `FR-AGT-001` |
| **模型不支持工具调用** | `AgentBanner` 常驻 `agent.model.unsupportedTools`（降级为 ReAct-文本模式，`14-agent.md` §10.1）；工具卡片照常渲染（来自文本解析） | 在 `ModelPicker` 换模型、继续使用（可靠性下降，不阻断）；文本解析连续失败则按 `FR-AGT-004` 结束 | `FR-AGT-004` |
| **权限被拒（`deny` 终态）** | `ToolCallCard.status='rejected'`（`--fr-text-muted` + `permission.denied.hint`，含错误码）；**不得**渲染成红色失败；`PermissionDialog` 不再弹出（AG-9） | 在权限面板把规则改回 `ask` / `always`（`fr:agent:setPermissionRule`）、追问让 Agent 换一种做法 | `FR-AGT-003` |
| **沙箱越界被拦** | 卡片红色 + `agent.error.outOfBounds`；该码为 **fatal 安全事件**，已记审计（UI 不展示审计正文，仅提示已记录）；run 终止 | 查看错误详情（`agent.error.details`）、追问让 Agent 改在 `workspace/` 内操作、导出日志并上报；**不提供重试入口** | `FR-AGT-008` |
| **上下文超预算** | 中栏尾部错误卡片 `agent.error.budget`，`AgentStatusBar` 转 `--fr-danger`；已产出**全部保留**（AG-6） | 新开会话（推荐，`agent.session.new`）、移除长附件后重试、缩小检索范围 | `FR-AGT-011` |
| **项目工作区不可用** | `ProjectFileTree` 位置渲染 `ErrorState`（`project.unavailable`）；左栏会话列表仍可读；中栏为只读回放，**禁用发送**（无落盘目的地） | 重新定位项目（`project.unavailable.action` → `fr:project:ensure`）、打开诊断、导出日志 | `FR-AGT-012` |
| **取消 run 后保留产出** | 已完成的卡片保持 `ok` 与结果摘要；取消时仍在 `running` 的卡片转 `canceled`（中性色）；顶栏 `agent.state.canceled` + toast `agent.cancel.done`；**不回滚**已写入的笔记与工作区文件 | 继续追问、重试本次提问（`agent.error.retry`）、复制/导出已产出 | `FR-AGT-007` |
| **达到步数/工具调用上限** | 状态栏 `agent.status.run` 达到 `{maxSteps}`/`{maxCalls}` 并转 `--fr-warn`；错误卡片 `agent.error.stepLimit`；已产出保留 | 继续追问（新 run 从当前上下文继续）、缩小任务范围、新开会话 | `FR-AGT-006` |

---

## 12. 性能约束

| # | 约束 | 实现要点 | 指标卡 |
|---|---|---|---|
| PF-1 | 文献库列表 > 100 条必须虚拟化 | `@tanstack/react-virtual`，行高 64px，`overscan: 8` | 1000 条滚动 ≥ 55 fps |
| PF-2 | 重排视图**分段挂载**：每 200 段（`Paragraph`）一批 | 首屏 2 批同步挂载；其余由 `IntersectionObserver(rootMargin:'800px')` 触发；未挂载批占位 `contain-intrinsic-size` | 1000 页首屏 ≤ 3000 ms（`BUDGETS.FIRST_PAINT_1000_PAGES_MS`） |
| PF-3 | 滚动帧率 ≥ 55 fps（`BUDGETS.SCROLL_FPS_MIN`） | 滚动同步 `{passive:true}` + `requestAnimationFrame` 批处理；滚动期间禁止布局读取（`getBoundingClientRect` 结果缓存 1 帧） | Playwright trace 采样 ≥ 55 fps |
| PF-4 | 原文模式按页懒渲染 | 仅渲染可见页 ±2；位图 LRU（`CACHE_MAX_MB=500`，`PAGE_BITMAP_DPI=110`） | 内存峰值 ≤ 1200 MB（`BUDGETS.MEMORY_PEAK_MB`） |
| PF-5 | 冷启动 ≤ 2500 ms（`BUDGETS.COLD_START_MS`） | 路由级 `React.lazy`；`/settings`、`/doctor`、`SearchPalette` 均懒加载 | 冷启动测量 |
| PF-6 | 翻译批量 | 每次请求 ≤ `BUDGETS.TRANSLATE_BATCH_CHARS=4000` 字符；并发上限 2 | 1000 词段落 ≤ 8 s（M4 Gate） |
| PF-7 | **会话事件流虚拟化**：单会话事件 > **200** 条必须虚拟化 | `@tanstack/react-virtual`：`estimateSize = 96px` + `measureElement` 实测动态行高，`overscan: 8`；滚出视口的消息卸载 DOM，但 Markdown 渲染结果按 `seq` 缓存（`Map<seq, ReactNode>`，上限 300 项，LRU 淘汰）；**禁止**为未挂载消息保留图片/公式节点 | 1000 条事件会话滚动 ≥ 55 fps；首屏渲染 ≤ 500 ms |
| PF-8 | **流式文本增量渲染节流**：渲染频率 **≥ 30 ms/帧** | 合并策略：`delta` 写入 ref，用 `requestAnimationFrame` + 30 ms 时间片节流后统一 `setState`；**禁止**逐 token 触发 React 更新；流式期间该 `MessageBubble` 保持 `aria-busy="true"`（A9），收到定型（`message` 事件或 `run_state` 跃迁）后一次性 flush；`Cmd/Ctrl+.` 立即 flush 并停止流式（§7.3） | 单 run 流式期间 ≥ 55 fps；delta 合并率 ≥ 90%（dev 计数器） |
| PF-9 | **空闲时零轮询** | 禁止 `setInterval` / 递归 `setTimeout` 轮询：run 状态、会话列表、文件树、权限表全部**事件驱动**（`fr:agent:event` / `fr:project:changed`），进入页面时一次性拉取；唯一允许的周期计时器是 `PermissionDialog` 打开期间的 1 s 倒计时，弹窗关闭/组件卸载必须 `clearInterval` | 空闲 5 min 内 Agent 相关 IPC 调用数 = **0**；单 run 内存增量 ≤ 200 MB（`14-agent.md` §14） |

> 本章的数值（`PF-1` 100 条、`PF-2` 200 段/±2 页、`PF-7` 200 条事件、`PF-8` 30 ms/帧）均为**实现常量**，若需调整必须同步 `10-testing.md` 指标卡；其余阈值一律引用 `BUDGETS` 或 `14-agent.md` §3.2 的 `AGENT_BUDGETS`（`MAX_STEPS` / `MAX_TOOL_CALLS` / `TOKEN_BUDGET` / `RUN_TIMEOUT_MS`）。**UI 不得复制这些常量**：步数与工具调用数一律取自 `run_state` 事件载荷，上限值取自 `packages/core` 的 `AGENT_BUDGETS`（§6.4 A-1）。

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结：设计原则 P1–P5、路由表、三栏布局与断点、V1 组件契约、双模式同步算法、三套状态机、快捷键表与输入态抑制、无障碍 A1–A8、**76 条 i18n 文案**、`--fr-*` 令牌表、空态矩阵、性能约束 PF-1–PF-6 |
| v1.1 | 2026-10-03 | **V1 纳入内置 Agent**（决策变更，取代原「Agent 放 V2」）：新增 `/agent` 与 `/project/:projectId` 路由及 R-5…R-9 硬规则（离开执行中会话二次确认、并排 ≠ 多标签、`afterSeq` 续接、文件树无特权预览）；§3.3 Agent 三栏骨架 + §3.4 并排形态 L-1…L-8（面板 420/320/720，宽度不写盘）；**14 个 Agent 组件契约**（`ToolCallCard` 的 5 类 `sideEffect` 风险映射、`PermissionDialog` 四选项 + 120 s 倒计时 + 默认拒绝、`ToolPermissionPanel` 持久规则仅 `always/ask/deny`）；`AgentRunUiState` 8 态（UI 新增 `idle`）与 A-1…A-7 硬规则；§7.3 Agent 快捷键与 `Esc` 层序；无障碍 A9–A12（`aria-live` 对话流、工具卡片可聚焦、`role="alertdialog"` 焦点陷阱）；**新增 132 条 i18n（累计 208 条）** 覆盖 14 个工具展示名/描述、权限四选项、`permission.timeout`、`agent.model.unsupportedTools`、`agent.capability.browserNotInV1`、`agent.error.*` 兜底与三类空态；§11 新增 9 条空态/边界；性能 PF-7…PF-9（事件流虚拟化 > 200 条、流式节流 ≥ 30 ms/帧、空闲零轮询） |
| v1.2-M1 | 2026-10-03 | ADR-14：meta schema v2 持久化 reading，v1 校验迁移；M1 最小 PDF.js 锚点与 node:sqlite。preload 增加本地 PDF 选择对话框（只返回授权路径）；仅原文阅读，M2 再验收重排。 |
