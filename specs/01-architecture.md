# 01 · 架构规范

> 状态：**冻结**。本文件定义进程、模块、依赖方向与启动时序；边界由 `eslint-plugin-boundaries` + `no-restricted-imports` 机检（见 `00-conventions.md` §4）。

---

## 1. 进程与线程模型

| 进程/线程 | 职责 | 禁止 |
|---|---|---|
| **main（Electron 主进程）** | 窗口与视图、文件系统、SQLite、sidecar 生命周期、NetGuard、IPC 服务端 | 不跑模型推理、不做 UI 布局 |
| **renderer（每窗口一个）** | 全部 UI、重排 HTML 渲染、锚点总线路由 | **禁止** fs / net / child_process / electron 直接调用（README F1） |
| **utility worker（Node worker_threads）** | 纯 JS 规则解析（rule 引擎）、锚点构建、句子切分等 CPU 密集任务 | 不阻塞主进程事件循环 |
| **parser sidecar（Python 子进程）** | Docling / Marker / GROBID / PaddleOCR 推理 | **禁止**任何出站网络；只监听 127.0.0.1 |
| **PDF.js worker（renderer 内 web worker）** | PDF 解析与渲染 | 不访问文件系统（通过 ArrayBuffer 传输） |
| **Agent 运行时（main 内，V1）** | 会话编排、工具执行、权限门禁、审计落盘；`run_python` 转发到 Pyodide worker | 不经 `NetGuard` 出网；不直接读写文献库真源文件（AG-4） |
| **Pyodide worker（utilityProcess，V1）** | `run_python` 沙箱：numpy/pandas/matplotlib，无网络、无宿主文件系统（AG-5） | 禁止 `socket`/`fs` 访问；超 `PYTHON_TIMEOUT_MS` 强制终止 |

**资源上限（硬约束）**：主进程堆 ≤ 512 MB；每个 renderer ≤ 800 MB；worker ≤ 256 MB；sidecar ≤ 4 GB（模型推理）；**Agent 单 run 内存增量 ≤ 200 MB**（`14-agent.md` §14）。超限时优先降级 sidecar，其次终止 Agent run，最后关闭非活动阅读标签。

---

## 2. 模块图与依赖方向

```
                 ┌──────────────────── renderer ────────────────────┐
                 │  views/ (LibraryView, ReaderView, SettingsView)   │
                 │  components/ (ui 组件，无业务)                     │
                 │  state/ (zustand stores)                          │
                 │  ipc-client (由 schemas/ipc-channels.json 生成)    │
                 └───────────────▲───────────────────────────────────┘
                                 │ window.fr.*（preload 白名单）
                 ┌───────────────┴───────────────────────────────────┐
                 │  main                                             │
                 │   services/  LibraryService · NoteService          │
                 │              TranslateService · FetchService       │
                 │              ParserClient · UpdateService          │
                 │   infra/     SqliteStore · FileStore · NetGuard    │
                 │              Logger · Keychain · WorkerPool        │
                 └───────────────▲───────────────────────────────────┘
                                 │ 纯函数 / 类型
     ┌───────────────────────────┴────────────────────────────────────┐
     │ packages: core · render-reflow · parser-protocol · translate   │
     │           fetch · zotero · ui                                  │
     └────────────────────────────────────────────────────────────────┘
```

**依赖方向规则（唯一合法方向，禁止反向）**

```
renderer → ui, core(类型), ipc-client
main     → core, render-reflow(仅导出), parser-protocol, translate, fetch, zotero, ui(仅文案常量)
core     → (无)
render-reflow → core
translate → core
fetch     → core, NetGuard
zotero    → core
ui        → core(类型)
```

- **禁止循环依赖**（`dependency-cruiser` 检查，CI 阻断）。
- `core` 必须是**纯函数 + 纯类型**：不 import `electron`、`fs`、`react`，不使用全局可变状态；随机性与时钟必须注入（便于 INV-10 的确定性测试）。

---

## 3. 启动时序（含时间预算）

```
t0      app ready
t0+50   Keychain 解锁（若无密钥则跳过）
t0+80   打开 SQLite（WAL），校验 schema_migrations；不一致→后台迁移并提示
t0+150  注册 preload 与 IPC 通道（由 schemas/ipc-channels.json 生成）
t0+200  创建主窗口 → renderer 首屏（书架骨架）
t0+400  sidecar 探测：若本会话已启动则复用其**握手令牌**（**不使用端口缓存/端口复用**，
        见 04 §S2：每次 spawn 随机端口 + 主进程持有 token）→ GET /v1/health（预算 1500 ms）
          ├ 成功 → 记录 engine 列表，UI 移除"快速模式"提示
          └ 失败 → 标记 rule 引擎，UI 常驻 QuickModeBanner（不阻塞阅读）
t0+600  懒加载：无活动文档时不构建锚点、不启动 OCR
── 用户打开文档时 ──
      ① 读 blocks.json（命中缓存且 cacheKey 一致）→ 直接渲染
      ② 未命中 → 入解析队列 → 边解析边渲染已就绪页（渐进式）
```

**冷启动预算**：`COLD_START_MS = 2500`（到主窗口可交互）。**任何**启动路径不得同步等待 sidecar。

---

## 4. 数据流（一次"打开论文并翻译一段"）

```
用户点击文献
  → renderer: fr:doc:open({citekey})
  → main: LibraryService.getDoc() → 缓存键校验
       ├ 命中：读 blocks.json
       └ 未命中：ParserClient.parse() → sidecar → DocAnchorModel → 原子写盘 + 索引
  → main → renderer: {sessionId, DocAnchorModel, pageSize}
  → ReaderView 挂载 ReflowPane（分批 200 段）+ OriginalPane（懒渲染可视页）
  → 用户点"翻译本段"
  → renderer: fr:translate:translateUnits({docId, lang, unitIds:['pa_3_4']})
  → main: TranslateService
       ├ 查 translation_cache（键见 08 §6）
       ├ 未命中 → 构造批次（≤ 4000 字符）→ Provider.translate()
       └ 结果写 <citekey>/translation/<lang>.jsonl + SQLite
  → main → renderer: 返回译文 → ReflowPane 在同段落内插入 <span class="fr-translation">
```

**关键约定**：所有写操作（blocks/meta/notes/translation/patch）在 main 中**串行化 per citekey**（`FileStore.withLock(citekey, fn)`），避免并发写坏文件。

---

## 5. 错误传播路径

```
底层（zod 校验 / fs / HTTP / sidecar）
  → 抛 AppError(code, {cause, details})          // 见 11-error-handling.md
  → IPC 层捕获 → 序列化为 {ok:false, error:{code, message, details}}
  → renderer ipc-client 解包 → 转成 UI 可消费的 ErrorState
  → UI 按错误码查 i18n 文案 + 建议动作
```

规则：

1. **跨进程只传序列化后的错误**（`code`/`message`/`details`），不传 `Error` 实例或堆栈给 renderer（堆栈只进本地日志）；
2. **不得吞错**：`catch` 必须转成 `AppError` 或重抛；CI 静态检查禁止空 catch；
3. **每个错误码必须有 i18n 文案与建议动作**（`11-error-handling.md` 的表是唯一来源）。

---

## 6. 扩展点

| 扩展点 | 接口 | 位置 | 状态 |
|---|---|---|---|
| 解析引擎 | `ParserProvider`（见 `04-parser-sidecar.md`） | `packages/parser-protocol` | V1 |
| 翻译后端 | `TranslatorProvider`（见 `08-translation.md`） | `packages/translate` | V1 |
| 文献来源 | `FetchProvider`（见 `09-fetch-compliance.md`） | `packages/fetch` | V1 |
| **Agent 工具** | `AgentTool`（见 `14-agent.md` §4.1） | `packages/agent/src/tools/` | **V1** |
| **Agent 技能** | `SKILL.md` 约定（见 `14-agent.md` §9） | `projects/<id>/skills/` | **V1（仅本地安装）** |
| LLM 后端 | `LlmProvider`（见 `14-agent.md` §10） | `packages/agent/src/llm/` | **V1** |
| 阅读器面板 | `registerReaderPanel`（见方案 §3.3） | `packages/core/src/plugin.ts` | V2 |
| 导出格式 | `Exporter`（Markdown/BibTeX/PDF） | `packages/core/src/export/` | V1（Markdown/BibTeX） |

**Agent 工具新增流程（V1 强制）**：声明 `sideEffect`/`defaultRule`/`timeoutMs` → 实现 zod `inputSchema` → 经 `NetGuard` 出网（如需要）→ 加入 §4.1 表格与 `fr:agent:listTools` 返回值 → 补 `14-agent.md` §13 安全清单与单元测试。**新增工具属于规范变更，需 `spec:` 提交。**

**插件沙箱原则**（V2）：插件运行在独立 `utilityProcess`，通过受限 RPC 访问能力；插件**不得**直接获得 `fs`/`net`。

---

## 7. 架构守卫（CI 必须执行）

| 检查 | 工具 | 失败后果 |
|---|---|---|
| 依赖方向与循环 | `dependency-cruiser` + `eslint-plugin-boundaries` | 阻断合并 |
| renderer 零特权 | `no-restricted-imports`（fs/net/electron/child_process） | 阻断合并 |
| 生成物一致性 | `pnpm gen:check`（schemas → `*.generated.ts`） | 阻断合并 |
| 禁用域名 | `scripts/forbid-domains.sh` | 阻断合并 |
| 包体积 | `pnpm size`（renderer 首包 ≤ 1.5 MB gzip；单依赖 > 200 KB 需说明） | 警告→阻断（超 2 MB） |
| 启动预算 | E2E 中的 `cold-start` 用例 | 阻断（> 3 s） |

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结 |
| v1.1 | 2026-10-03 | V1 纳入 Agent：进程表新增 Agent 运行时与 Pyodide worker；资源上限新增单 run ≤ 200 MB；§6 扩展点区分 V1/V2 并新增 Agent 工具/技能/LLM 与「新增工具」强制流程 |
