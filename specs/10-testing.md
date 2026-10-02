# 10 · 测试与评测规范

> 状态：**冻结**。`pnpm verify` 是本地与 CI 的唯一入口（见 `00-conventions.md` §7）。
> 原则：**门禁化的质量**——质量指标不是"报告"，而是**能阻断合并的阈值**。

---

## 1. 测试分层与覆盖率

| 层 | 范围 | 工具 | 覆盖率要求 | 运行时机 |
|---|---|---|---|---|
| 单元测试 | `packages/core`、`render-reflow`、`translate`、`fetch` 的纯函数 | Vitest | `core`/`render-reflow` **分支 ≥ 90%**；其余 ≥ 70% | 每次提交 |
| 契约测试 | `schemas/*.json` ↔ 生成类型 ↔ IPC 通道 ↔ sidecar 协议 | Vitest + AJV | 100% 通道被覆盖 | 每次提交 |
| 集成测试 | main 进程服务（LibraryService/NoteService/TranslateService） + 真实 SQLite（内存/临时目录） | Vitest (node env) | 关键路径 100% | 每次提交 |
| 解析评测 | 黄金集 50 篇：块 F1 / 句子 IoU / 覆盖率 / 顺序 | `pnpm eval:anchor` | 见 §3 门禁 | PR 跑小集(10)，夜间跑全集(50) |
| 端到端（E2E） | 打包后的 Electron 应用 | Playwright (`_electron`) | 场景清单 100% | 每次 PR（冒烟 7 条）+ 夜间（全量 21 条） |
| 性能基准 | 首屏/滚动/冷启动/内存/解析耗时 | Playwright + 自研 `bench` | 见 §4 | 夜间 + 发布前 |

**测试文件命名**：`*.test.ts`（单元/集成）、`*.contract.test.ts`、`*.e2e.ts`（Playwright）。测试与源码同目录。

---

## 2. 黄金集（`fixtures/golden/`）

```
fixtures/golden/
├─ README.md                     # 每篇的来源、许可、标注者、标注日期
├─ index.json                    # 清单：{id, file, category, source, license, sha256, pages}
├─ <id>/
│  ├─ paper.pdf                  # 原始文件
│  ├─ expected/blocks.json       # 人工标注的 DocAnchorModel 子集（blocks + outline + figures）
│  ├─ expected/sentences.json    # 20 条句子的 LineRef 真值
│  └─ expected/meta.json         # 期望的 meta（title/doi/year 用于元数据评测）
└─ synthetic/                    # 合成样本（无版权风险，用于规则单测）
```

**构成（50 篇）**：双栏正文 15 ｜ 公式密集 10 ｜ 表格/图注 10 ｜ 扫描件 8 ｜ 中文期刊 7。

**硬性要求**

1. **全部样本必须有可再分发授权**（OA/CC/自制）：提交前在 `README.md` 写明来源与许可，CI 校验 `index.json` 每条都有 `license` 字段；
2. **禁止**提交来路不明的付费文献、用户笔记或任何个人数据；
3. 扫描件子集允许使用**合成生成**（用 LibreOffice 把文本转 PDF 后降采样）；
4. 标注规范见 `fixtures/golden/README.md`（与 `03-anchor-model.md` §7 的指标定义一一对应）。

---

## 3. 锚点评测门禁（`pnpm eval:anchor`）

实现：`packages/core/src/eval/anchor-metrics.ts`；输出 `eval-report.json` + 控制台表格。

| 指标 | 计算 | 阈值 | 级别 |
|---|---|---|---|
| 块结构 F1 | 同页 + IoU ≥ 0.5 + `type` 一致 视为 TP | ≥ 0.90 | **P0 阻断** |
| 句子↔行 IoU | 见 03 §7 定义（字符级集合） | ≥ 0.98 | **P0 阻断** |
| 内容覆盖率 | 非 `abandon` 块覆盖字符 / 文本层总字符 | = 100% | **P0 阻断** |
| 阅读顺序 τ | Kendall τ vs 真值 | ≥ 0.95 | P1 |
| 公式保护率 | 未被错误切分/改写的公式块比例 | ≥ 99% | **P0 阻断** |
| 确定性 | 两次构建字节一致 | 100% | **P0 阻断** |

**回归策略**：夜间全量结果写入 `eval-history.jsonl`；任何 P0 指标相对上一基线下降 > 0.5% → 自动开 issue 并标记 `regression`。

PR 门禁：跑 `--set golden --limit 10 --seed 0`（固定随机子集，保证可复现）。

---

## 4. 性能基准与门禁

| 指标 | 场景 | 阈值（来自 `BUDGETS`） | 级别 |
|---|---|---|---|
| 首屏渲染 | 1000 页 PDF 打开至可滚动 | ≤ 3000 ms | P1 |
| 滚动帧率 | 连续滚动 10 s | ≥ 55 fps | P1 |
| 冷启动 | 启动到可交互 | ≤ 2500 ms | P1 |
| sidecar 健康检查 | 已启动情况下 | ≤ 1500 ms | P1 |
| 内存峰值 | 同时打开 5 篇（含 1 篇 1000 页） | ≤ 1200 MB | P1 |
| 锚点构建 | 100 页（rule 引擎） | ≤ 2500 ms | P1 |
| 翻译端到端 | 1000 词，本地 7B | ≤ 8000 ms | P2 |
| 打包体积 | Windows 安装包 | ≤ 260 MB（含 sidecar 时 ≤ 600 MB） | P2 |
| **Agent 空闲零轮询** | 打开 Agent 面板并静置 **60 s**（无 run 进行中、无会话打开） | IPC 调用 = 0 **且** 出站请求 = 0（`FakeNetGuard` 计数 + 主进程 IPC 计数双断言） | P1 |
| **Agent 单 run 内存增量** | 一次 20 步问答（含 1 次 `run_python`），基线 = run 前 RSS | ≤ 200 MB（超限记 `FR-SYS-002` 候选并阻断） | P1 |
| **Agent 事件流虚拟化** | 会话事件 > 200 条时连续滚动 10 s | ≥ 55 fps（列表必须虚拟化，禁止全量挂载 DOM） | P2 |

> Agent 的三项门禁**不得**用"冷启动不变慢"代替：冷启动只证明入口不拖慢，不证明空闲不轮询与 run 结束后的内存可回收（断言 run 结束后 RSS 回落到基线 + 50 MB 以内）。

基准必须固定机器参数（CI 用自托管 runner），并在报告中记录环境；**禁止**用不同机器比较阈值。

---

## 5. E2E 场景清单（Playwright，`apps/desktop/e2e/`）

| # | 场景 | 断言要点 |
|---|---|---|
| E1 | 冷启动 → 空库 | 首屏可交互 ≤ 2500 ms；显示空态与"导入"引导 |
| E2 | 导入 3 篇 PDF | 去重生效；卡片出现；索引写入 |
| E3 | 打开论文 → 阅读 | 原文模式可滚动；重排模式可切换 |
| E4 | **位置恢复** | 滚到第 N 段 → 关闭 → 重开 → 落在同一 `sentenceId`（重复 5 次全中） |
| E5 | 双模式同步 | 点重排句子 → 原文对应行高亮（< 300 ms） |
| E6 | 高亮与笔记 | 创建 → 重启后仍在 → 两模式位置一致 |
| E7 | 低置信纠错 | 触发 `score<0.6` 描边 → 改类型 → 保存 patch → 重渲染生效 |
| E8 | 翻译（mock provider） | 段落内出现译文；术语表命中；公式占位符保留 |
| E9 | 翻译失败降级 | provider 500 → 显示原文 + 面板提示（引用 `FR-TRANS-*`） |
| E10 | 无 sidecar 快速模式 | 强制 sidecar 失败 → 横幅出现；阅读不阻塞；rule 引擎出块 |
| E11 | 离线 | 断网 → 阅读/笔记/翻译(本地)全部可用；网络类操作提示不阻塞 |
| E12 | NetGuard 拦截 | 尝试访问黑名单域名 → 抛 `FR-NET-003`，UI 提示合规文案，**不重试** |
| E13 | Zotero 只读导入 | 导入 20 条 → `zotero.sqlite` 的 mtime/hash 不变 |
| E14 | 崩溃恢复 | 强杀 renderer → 重启后恢复到上次句子 |
| E15 | 文献库搜索 | FTS5 命中标题/摘要/正文；中文查询可用 |
| E16 | **Agent 会话问答的引用可追溯（AG-10）** | 在项目会话中提问 → `finish` 的 `citations[]` 每项 `callId` 都能在事件流中命中一条 `tool_result`；答复中的每个结论至少被引用一次；无引用时 UI 标注「未经验证」（断言该标注出现） |
| E17 | **权限 `ask` 三条分支 + 超时** | 触发 `workspace_write` 权限弹窗：①「允许一次」→ 本 run 内同工具不再询问，`permission` 事件 `decision=once`/`byUser=true`；②「总是允许」→ `permissions.json` 写入 `always`，**重启应用后仍不询问**；③「拒绝」→ 工具未执行并返回 `FR-AGT-003`，同项目后续调用**直接失败且不再弹窗**（AG-9）；④ 弹窗静置至超时 → `decision=deny`/`byUser=false` 且 `permissions.json` **未被修改**（该分支用可注入超时缩短，不真实等待 120 s） |
| E18 | **取消 run 保留已有产出** | run 进行中点「停止」→ `run_state=canceled` + `FR-AGT-007`；已落盘的笔记与工作区文件仍在；事件流可完整回放；同一会话可继续追问且上下文保留取消前内容 |
| E19 | **项目文件读写与导出 zip** | `workspace_write` 后 `workspace_list` 能列出该文件；`fr:project:exportZip` 产物含 `project.json` + `workspace/` + `skills/`，**不含** `permissions.json` 与 `sessions/`（解压后逐项断言）；导入的文件出现在工作区且不覆盖同名文件 |
| E20 | **`run_python` 沙箱** | 无网络（脚本内 `socket`/`urlopen` 失败）；`PYTHON_TIMEOUT_MS`（20 s）超时后 Worker 被终止且**无产物落盘**；超过 `PYTHON_MEMORY_MB`（512 MB）被回收并返回 `FR-AGT-005`；正常脚本的 stdout 由主进程代写工作区（AG-5） |
| E21 | **不支持工具调用的模型 → ReAct-文本模式** | Provider `supportsTools === false`：会话开始显示「当前模型不支持原生工具调用，可靠性下降」横幅；模型输出的严格 JSON `{"tool":…,"args":{…}}` 被解析并执行（UI 出现工具卡片）；解析失败 → 重试 1 次 → 仍失败则以 `FR-AGT-004` 结束 run（不静默重试，`14-agent.md` §10.1） |

冒烟子集（每次 PR）：E1、E3、E4、E6、E10、**E16、E17**。

---

## 6. Agent 测试（`packages/agent` + `packages/core/src/agent/`）

> 权威定义：[`14-agent.md`](./14-agent.md)（不变量 AG-1..AG-10、预算 §3.2、14 个工具 §4.1、权限 §5、注入防护 §6.3、事件流 §8、技能 §9）。
> 覆盖率：`packages/agent` 分支 **≥ 90%**（与 `core` 同级）。权限判定、上下文裁剪、事件流序列化必须是**纯函数**并可单测，禁止只用 E2E 兜底。
> 本节的 4 类用例（单元 / 契约 / 集成 / 沙箱）对应 `14-agent.md` §14 的测试要求，缺一即 PR 门禁失败。

### 6.1 单元测试

**AG-U1 权限判定 4×4 矩阵** —— 规则从 `permissions.json` 注入，判定入口 `decide(tool, ctx) → { action: 'allow' | 'prompt' | 'reject'; code? }`：

| 规则 \ 情形 | ① 首次请求 | ② 同 run 内重复调用 | ③ 新 run（跨 run） | ④ 询问超时 120 s 无响应 |
|---|---|---|---|---|
| `always` | allow（不弹窗） | allow | allow | 不适用（不产生询问） |
| `once` | 询问 →「允许一次」后记 run 级授权 | allow（本 run 免询问） | 不持久化 → 回落 `defaultRule`（`write`/`execute` 类 = `ask`，再次询问） | 不适用（无 `once` 记录即无询问） |
| `ask` | 询问 | 再次询问 | 询问 | `deny`：**仅本次 run，不写盘**，`permission` 事件 `byUser=false` |
| `deny` | `FR-AGT-003`，**不弹窗** | 同左 | 同左（AG-9 终态） | 不适用（不产生询问） |

断言补充：① `once` 授权在 run 结束时清除，同项目下一个 run 不再免询问；② `always`/`deny` 落盘后**重启进程仍生效**；③ `ask` 超时**不得**写入 `permissions.json`；④ 四条路径各自产生 1 条 `permission` 事件（AG-2，含 `deny`）；⑤ 通配 `*` 规则在 V1 **不生效**（`14-agent.md` §5.1）。

**AG-U2 上下文裁剪的预算边界**（`TOKEN_BUDGET = 120_000`）
- 三档边界 `119_999` / `120_000` / `120_001`：前两档不触发、第三档触发 `FR-AGT-011`；
- 裁剪顺序固定：① 先裁项目元信息（上限 2_000 字符）→ ② 最旧的工具结果压缩为 `summary` 一行 → ③ 超出最近 6 轮的对话转 rollup 摘要；
- **不得**裁剪系统提示词与用户当前消息：注入超长用户消息，断言其逐字符保留而其余段被裁；
- 回灌模型的**只有** `ToolResult.summary`（≤ 400 字符），`data` 永不进上下文；`TOOL_RESULT_MAX_CHARS = 8_000` 截断边界断言 `7999/8000/8001`；
- 压缩后仍超预算 → `FR-AGT-011`，run 以 `failed` 结束且**保留已产出内容**（AG-6）。

**AG-U3 工具 zod schema 反例**（14 个工具每个至少 3 条反例）
- 未知字段（严格对象必须拒绝）、类型错、必填缺失、字符串/数组超长；
- `docId` 非 64 位 hex；文件类入参含 `..`、NUL、UNC、工作区外绝对路径；
- 全部以 `FR-AGT-004` 拒绝，且**不得**进入执行器（spy 断言 `execute` 调用次数 = 0）。

**AG-U4 事件流序列化与回放**
- 6 种事件（`message`/`tool_call`/`tool_result`/`permission`/`run`/`error`）逐行通过 `agent-session.schema.json`；`seq` 自 1 单调递增，跳号/重复即失败；
- `tool_call` 只落 `argsHash`（sha256）与 `argsSummary`，**不落完整参数**；断言 JSONL 中不含参数原文、笔记全文、译文全文、API Key（AG-8）；
- 末行截断 / 未知 `type` / 多余字段 → `FR-AGT-010`；
- 回放：仅凭事件流重建的 UI 状态与实时渲染的最终态逐字段相等（append-only，AG-7）。

### 6.2 契约测试

| # | 对象 | 断言要点 |
|---|---|---|
| AG-C1 | 通道与事件全覆盖 | `schemas/ipc-channels.json` 中的 Agent/项目通道 **15 个**（`fr:agent:*` 10 个 + `fr:project:*` 5 个）与 **2 个事件**（`fr:agent:event`、`fr:project:changed`）逐个覆盖：请求 zod 严格校验、`ApiResult<T>` 信封、`errors[]` 只列可 `ok:false` 返回的码（降级类走 `warnings`） |
| AG-C2 | 工具表一致性 | `fr:agent:listTools` 返回的工具**数量 = 14、名称集合与代码内注册表双向 diff 为空**，每项含 `inputSchema`（JSON Schema）、`defaultRule`、`sideEffect`、`timeoutMs`；增删工具必须同 PR 更新 `14-agent.md` §4.1 与本用例快照（快照不匹配即失败） |
| AG-C3 | 权限表 schema | `permissions.json` 通过 `agent-permissions.schema.json`；`rule` ∈ `{always, once, ask, deny}`；`projectId` 非 ULID、未知工具名、未知字段一律拒绝 |
| AG-C4 | 事件 schema | 6 种事件各 1 正例 + 5 反例（`seq = 0`、`argsHash` 非 64 位 hex、`decision` 非法、`state` 非法、多余字段） |
| AG-C5 | 能力协商 | `fr:app:getCapabilities` 返回 **`agent: true`**（V1 起取代原「恒 false」）；`quickMode` 语义不受影响 |

### 6.3 集成测试（`FakeLlmProvider` 脚本驱动 + 真实 SQLite + 临时工作区）

| # | 用例 | 断言要点 |
|---|---|---|
| AG-I1 | 脚本化工具调用序列 | 脚本 `search_library → read_document → write_note → finish`：事件流 `tool_call` 顺序 = 脚本顺序；每个调用恰好 1 行 `tool_call` + 1 行 `tool_result`（**审计行数 = 2 × 调用数**）+ SQLite `op_log` 1 行 `op='agent.tool'`；`finish` 载荷 `{answer, citations[]}` 的每个 `callId` 都能命中一次 `tool_result`（AG-10） |
| AG-I2 | 无审计则不执行 | 审计写盘失败 → 工具**不执行**并返回错误（AG-2）；断言副作用文件与笔记均未产生 |
| AG-I3 | 预算终止 | 脚本 25 步 → `MAX_STEPS` 命中：`FR-AGT-006`、`run.state=failed`、`steps=24`；脚本 41 次工具调用 → `MAX_TOOL_CALLS` 命中；`RUN_TIMEOUT_MS`（600 s）用 `FakeClock` 推进，断言 `AbortSignal` 已透传到 Provider 与正在执行的工具；三种终止都**保留已产出内容** |
| AG-I4 | 并发 run | 同一 `projectId` 发起第二个 run → 被拒且第一个 run 不受影响（AG-1，`CONCURRENT_RUNS_PER_PROJECT = 1`）；不同项目可并行 |
| AG-I5 | 只读不变量 | run 全程结束后 `paper.pdf`、`blocks.json`、`annotations.jsonl` 的 sha256 与 mtime **均未变化**；`write_note` 经 NoteService 且锚点无效时报错而非静默写入（AG-4） |
| AG-I6 | 注入防护 | 工具结果含 `ignore previous instructions` → 记 `agent.injection.suspected` + UI 提示，run **不中断**；回灌模型的内容包裹在 `⟦tool-result id⟧…⟦/tool-result⟧` 中（`14-agent.md` §6.3） |
| AG-I7 | 技能安装 | 合法技能安装成功并被 `fr:agent:listSkills` 列出；front-matter 非法 / 路径穿越 / 201 个文件 / 21 MiB → `FR-AGT-009`，`skills/` 无残留；同名技能需用户确认覆盖，`license` 不在允许清单直接拒绝 |
| AG-I8 | Provider 缺失与失败 | 无 Provider → `FR-AGT-001`（入口可见 + 引导，不弹阻断式错误）；模型 5xx/超时 → `FR-AGT-002` 自动重试 **≤ 1 次**，仍失败则 run `failed` 并保留已产出内容 |
| AG-I9 | 会话保留与删除 | 会话默认保留 90 天（`FakeClock` 推进断言过期清理）；`fr:agent:deleteSession` 立即删除文件并写审计；`fr:project:changed` 在项目文件变更时发出 |

### 6.4 沙箱与安全测试

| # | 用例 | 断言要点 |
|---|---|---|
| AG-S1 | 路径逃逸 | `workspace_read`/`workspace_write`/`import_pdf` 入参为 `../outside.txt`、指向工作区外的符号链接、`\\server\share\x`、含 NUL 的路径、`C:\Windows\x` → **逐条**返回 `FR-AGT-008`，且磁盘上不产生任何新文件（`realpath` + 包含性校验，`14-agent.md` §4.2） |
| AG-S2 | `run_python` 无网络 | 脚本内 `import socket` 后建连必须失败、`urllib.request.urlopen` 必须失败；Worker 全局无 `fetch`/`XMLHttpRequest`/`WebSocket`（AG-5） |
| AG-S3 | `run_python` 超时终止 | 死循环 / `time.sleep(60)` → `PYTHON_TIMEOUT_MS = 20_000` 到期终止，Worker 被回收，返回 `FR-AGT-005`，工作区无产物 |
| AG-S4 | `run_python` 内存上限 | 分配超过 `PYTHON_MEMORY_MB = 512` → Worker 被杀、返回 `FR-AGT-005`，主进程与其他工具不受影响 |
| AG-S5 | 网络唯一通道 | 静态门禁：工具源码不含 `node:http`/`node:https`/`fetch`/`axios`/`got`；运行期 `FakeNetGuard` 断言三个网络工具的 `purpose` ∈ `{metadata, oa-search, oa-download}`，且每次出站都有审计行（AG-3） |
| AG-S6 | 工具结果不可信 | 工具结果中的 HTML/脚本片段只做纯文本渲染，不得成为可执行内容（注入反例集，配合 `14-agent.md` §6.3） |

---

## 7. Mock 与故障注入

| 替身 | 用途 | 位置 |
|---|---|---|
| `FakeParserSidecar` | 契约测试与 UI 测试（返回固定黄金集结果；可注入延迟/失败/非法 JSON） | `packages/parser-protocol/src/testing/` |
| `FakeTranslatorProvider` | 可控译文与错误（404/429/超时/非法 JSON） | `packages/translate/src/testing/` |
| **`FakeLlmProvider`**（强制，Agent 专用） | **脚本化产出** `LlmChunk` 序列：① `toolCall`（`{id, name, argsJson}`，含参数非法/未知工具名的反例）；② 流式文本（分片边界与空 delta）；③ 错误（401/429/5xx、连接中断、超时、非法 JSON 工具参数）；④ `usage`（`in`/`out`）；`supportsTools` 可切换（`false` → ReAct-文本模式），并记录 `calls: LlmRequest[]` 供断言 | `packages/agent/src/testing/` |
| `FakeNetGuard` | 记录出站请求；按规则放行/拦截（含重定向跨域、私网 IP 用例） | `packages/fetch/src/testing/` |
| `FakeClock` / `FakeId` | 满足确定性要求（INV-10） | `packages/core/src/util/testing/` |
| 文件系统故障 | 磁盘满、只读目录、原子写中断 | 集成测试用 `memfs` 或临时目录 + 权限模拟 |

**必须注入的故障**：sidecar 崩溃 / 超时 / 返回非法 JSON / 令牌错误；模型未下载；SQLite 被外部锁定；用户目录权限拒绝；翻译 429；网络 DNS 失败；**Agent**：未配置 LLM Provider / 模型不支持工具调用（`supportsTools === false`）/ 工具审计写盘失败（**审计不可用则不出站、不执行**）/ Pyodide 加载失败 / 权限弹窗超时 120 s / 单步工具超时。

**`FakeLlmProvider` 与 `FakeTranslatorProvider` 的复用关系**（禁止各写一套）

- **同一个 Provider 体系**：二者共用 `08-translation.md` §2 的 Provider 配置与能力协商（`ollama` / `openai-compatible`、Key 存 OS Keychain、`health()` 语义），`14-agent.md` §10 只在其上新增 `chat()` 流式契约；
- **同一个脚本化内核**：`FakeLlmProvider` 复用 `FakeTranslatorProvider` 的脚本驱动参数（`delayMs`、`failTimes`、`mode`、`calls[]` 记录），差异仅在产出类型——前者产出 `LlmChunk`（含 `toolCall` 与 `usage`），后者产出 `string[]`；
- **互为降级替身**：`FakeLlmProvider` 置 `supportsTools:false` 即模拟「只会说话不会调工具」的模型（E21 / AG-I8）；`FakeTranslatorProvider` 经适配器（`translate()` → 单轮 `chat()`）即可充当纯文本 `LlmProvider`。**只改一处脚本即同时影响翻译与 Agent 两条链路的用例**，因此该内核的改动必须同时跑 `translate` 与 `agent` 两个包的测试。

---

## 8. 缺陷分级与 Flaky 政策

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 | 数据丢失、位置丢失、合规越界、**Agent 沙箱越界（`FR-AGT-008`）**、锚点不变量失败 | 阻断发布，24 h 内修复 |
| P1 | 功能不可用、性能超阈值、错误信息缺失 | 阻断发布，当迭代内修复 |
| P2 | 体验瑕疵、文案问题 | 排期修复 |
| P3 | 建议类 | 记录 issue |

**Flaky 政策**：任何 E2E 用例连续 3 次夜间失败 → 自动标记 `flaky` 并从门禁移除，同时开 issue；**禁止**用 `retry` 掩盖不稳定（Playwright `retries: 0`，仅夜间允许 1 次重试用于区分环境抖动）。

---

## 9. CI 作业矩阵

| 工作流 | 触发 | 内容 |
|---|---|---|
| `pr.yml` | PR | `pnpm verify` + 锚点小集(10) + E2E 冒烟(7) |
| `nightly.yml` | 每日 02:00 | 全集评测(50) + 全量 E2E(21) + 性能基准（含 Agent 三项门禁）+ 回归对比 |
| `release.yml` | tag `v*` | 三平台打包 + 签名校验 + 许可合规产物 + 全量 E2E |
| `license.yml` | PR / 每周 | License Gate + `forbid-domains` + `SOURCE_OFFER` 校验 |

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结 |
| v1.1 | 2026-10-03 | V1 内置 Agent（`14-agent.md`）：① E2E 场景 **+E16–E21**（引用可追溯 / 权限 `ask` 三分支与 120 s 超时 / 取消保留产出 / 工作区读写与导出 zip / `run_python` 沙箱 / ReAct-文本模式降级），冒烟子集扩到 7 条、夜间全量 21 条；② 新增 **§6 Agent 测试**（单元 AG-U1..U4、契约 AG-C1..C5、集成 AG-I1..I9、沙箱 AG-S1..S6），原 §6–§8 顺延为 §7–§9；③ 性能门禁新增**空闲零轮询（60 s）**、**单 run 内存增量 ≤ 200 MB**、**事件流虚拟化 ≥ 55 fps**；④ 强制替身新增 **`FakeLlmProvider`** 并明确其与 `FakeTranslatorProvider` 的复用关系；⑤ P0 缺陷定义纳入 `FR-AGT-008` 沙箱越界 |
