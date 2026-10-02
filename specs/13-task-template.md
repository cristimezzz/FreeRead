# 13 · 任务卡模板与完成定义

> 状态：**冻结**。本文件是"vibe coding"的**工作协议**：人类用它下任务，AI 代理按它执行与自检。
> 原则：**任务卡即上下文**——一张卡必须自足，AI 不需要追问即可开工。

---

## 1. 任务卡模板（复制即用）

```markdown
### T-<编号> <动词开头的标题>

- **归属里程碑**：M0–M7（见方案 §5）
- **负责包/目录**（写权限范围，勿越界）：`packages/core/src/anchor/`
- **依赖任务**：T-00x（未完成不得开工）
- **相关规范**：`specs/03-anchor-model.md` §6.3、§6.5；`specs/10-testing.md` §3
- **输入**：已有代码/数据/接口（给出确切路径与签名）
- **输出（必须逐条可验证）**：
  1. `packages/core/src/anchor/build.ts` 导出 `buildDocAnchorModel(input): DocAnchorModel`
  2. 单测 `build.test.ts` 覆盖 T1–T10（`10-testing.md` §3 或 `03-anchor-model.md` §10）
  3. `pnpm eval:anchor --set golden --limit 10` 输出 IoU ≥ 0.98
- **验收标准（Gate）**：
  - [ ] `pnpm verify` 全绿
  - [ ] 指标：<具体数值>
  - [ ] 新增 i18n key：<列出>（zh-CN + en）
  - [ ] 新增错误码：<列出>（已在 `11-error-handling.md` 登记）
- **禁止事项**：见 `specs/README.md` F1–F9（尤其：不得在 renderer 触碰 fs/net）
- **预估**：<人日>
- **交付说明要求**：按 §3 的报告格式回复
```

---

## 2. 完成定义（DoD）

见 `00-conventions.md` §8（9 条）。**补充说明**：

- 任务卡里的"输出"与"验收标准"是 DoD 的**具体化**，二者冲突时以任务卡为准；
- 若实现中发现规范不完整：**先补规范**（同一 PR 内提交 `spec:` 前缀 commit），再实现；
- 若验收标准中的数值无法达标：不得"调低阈值"，必须回报并给出三选一建议（缩小范围 / 换算法 / 延长工期）。

---

## 3. AI 代理的交付报告格式（强制）

```markdown
## 交付报告 T-0xx
- 状态：完成 / 部分完成（说明缺口）/ 阻塞（说明原因）
- 变更文件：<路径:行数>（逐条）
- 规范遵循：引用了哪些规范条目；是否有规范修订（有则给 commit）
- 验证证据：
  - `pnpm verify` → 通过（typecheck/lint/test/coverage 摘要）
  - `pnpm eval:anchor ...` → F1 0.93 / IoU 0.991 / 覆盖率 100%
  - 新增测试：<用例名与断言>
- 未决问题：<可选>
- 风险与建议：<可选>
```

**禁止**：只贴"已完成"，不给证据；**禁止**在报告里声称跑过未实际执行的命令。

---

## 4. 示例任务卡（可直接派发）

### T-001 建立 monorepo 骨架与质量门禁

- **归属里程碑**：M0 ｜ **写权限**：仓库根、`.github/`、`scripts/`、各包 `package.json`
- **依赖**：无
- **相关规范**：`specs/00-conventions.md` §2/§4/§7；`specs/01-architecture.md` §7
- **输出**
  1. pnpm workspaces + Turborepo；目录结构与方案 §3.2 完全一致
  2. `tsconfig.base.json` 按 `00-conventions.md` §2 配置；所有包 `extends`
  3. ESLint + boundaries + `no-restricted-imports`（renderer 禁 fs/net/electron）
  4. CI：`ci.yml`（typecheck/lint/test/build）、`license.yml`（黑名单 + notices）
  5. `pnpm verify`、`pnpm gen`、`pnpm license`、`pnpm forbid` 四个脚本可运行
- **验收**
  - [ ] `pnpm build` 成功产出三平台空壳安装包
  - [ ] 故意引入 `dependency-cruiser` 循环依赖 → CI 失败；移除后通过
  - [ ] 故意在 renderer 写 `import fs from 'fs'` → lint 失败
  - [ ] 故意加一个 `SSPL` 依赖 → `license` 失败
- **预估**：1.5 人日

### T-002 锚点模型构建器（rule 引擎）

- **归属里程碑**：M2 ｜ **写权限**：`packages/core/src/anchor/**`
- **依赖**：T-001
- **相关规范**：`specs/03-anchor-model.md`（全文）、`specs/schemas/doc-anchor-model.schema.json`
- **输出**
  1. `buildDocAnchorModel(input): DocAnchorModel`（输入：`LineBox[]` + `RawBlock[]` + `pageSize`）
  2. 算法 A1（块-行关联）与 A2（句子切分）按 03 §6.3/§6.5 实现，阈值取自规范（`0.60`、`25` 字符等），**不得魔数散落**
  3. 满足 INV-1..10，不变量失败抛 `FR-ANCHOR-00x`
  4. 单测覆盖 03 §10 的 T1–T10
  5. 评测脚本 `packages/core/src/eval/anchor-metrics.ts` + CLI
- **验收**
  - [ ] `pnpm test packages/core` 通过，分支覆盖 ≥ 90%
  - [ ] 合成样本上 T1–T10 全绿
  - [ ] 峰值内存增量 ≤ 40 MB / 100 页；单页构建 ≤ 8 ms
- **预估**：4 人日

### T-003 阅读位置恢复（"位置永不丢失"）

- **归属里程碑**：M1 ｜ **写权限**：`packages/core/src/progress/**`、`apps/desktop/src/main/services/note-service/**`
- **依赖**：T-001（可独立于 T-002 先做，用简化锚点）
- **相关规范**：`specs/02-domain-model.md` §3.2（closing 必须同步写入）、`specs/06-ipc-contract.md`（`fr:notes:updateProgress`）
- **输出**
  1. `saveProgress(docId, {sentenceId, page, scrollRatio})`：**同步**写 `meta.json`（原子写），失败降级写 `OpLogEntry`
  2. `resolveProgress(docId, model)`：返回可恢复的 `sentenceId` 与滚动偏移；锚点缺失时按 `page` 回退
  3. E2E 用例 E4（开关 5 次全中）
- **验收**
  - [ ] E4 通过（5/5）
  - [ ] 强杀进程后重开仍恢复（E14）
  - [ ] 单元测试覆盖：sentenceId 丢失 / 页码越界 / 文件只读 三种异常
- **预估**：2 人日

### T-004 Agent 运行时（会话 + 工具执行 + 审计）

- **归属里程碑**：M6（**V1 交付**）｜ **写权限**：`packages/agent/src/**`
- **依赖**：T-001（骨架）、T-002（锚点，`read_document` 需要）
- **相关规范**：`specs/14-agent.md`（全文，尤其 §3 运行模型、§4.1 工具清单、§8 事件流）、`specs/schemas/agent-session.schema.json`
- **输出**
  1. `AgentRunner`：状态机 `planning→acting→observing`（§3.1），预算常量取自 `AGENT_BUDGETS`，支持 `cancel`
  2. **14 个工具**全部实现并注册（§4.1），每个含 zod `inputSchema`、`sideEffect`、`defaultRule`、`timeoutMs`
  3. 会话事件流写入 `sessions/<sessionId>.jsonl`（append-only，逐行过 schema 校验）
  4. `LlmProvider` 两个实现（`ollama` / `openai-compatible`）+ `supportsTools=false` 的 ReAct-文本模式降级
  5. 工具实现**不得**出现裸 `fs`/`fetch`（走注入的受限上下文）
- **验收**
  - [ ] 单元：工具表数量与名称与 `14-agent.md` §4.1 **逐一一致**（14/14）；事件流序列化/回放往返一致
  - [ ] 集成：`FakeLlmProvider` 脚本化调用序列 → 断言执行顺序、审计行数、`finish` 载荷含 `citations`
  - [ ] 取消 run 后已有产出保留（E18）
  - [ ] `pnpm verify` 全绿；`packages/agent` 分支覆盖 ≥ 90%
- **预估**：5 人日

### T-005 Agent 权限门禁与沙箱

- **归属里程碑**：M6（**V1 交付**）｜ **写权限**：`packages/agent/src/permission/**`、`packages/agent/src/tools/run-python/**`
- **依赖**：T-004
- **相关规范**：`specs/14-agent.md` §5（权限四规则与判定算法）、§13（安全清单）、AG-3/AG-5/AG-9、`specs/schemas/agent-permissions.schema.json`
- **输出**
  1. `PermissionGate`：四规则判定 + `once` 的 run 级作用域 + `deny` 终态（AG-9）+ 120 s 超时兜底为拒绝
  2. 全部文件类工具经 `assertContainedPath`；越界抛 `FR-AGT-008`
  3. `run_python`：Pyodide worker、无网络、无宿主 fs、`PYTHON_TIMEOUT_MS` 强制终止
  4. 权限变更写 `permissions.json`（原子写）+ 审计 `permission` 事件
- **验收**
  - [ ] 单元：权限 4×4 判定矩阵全通过；超时自动拒绝且 `byUser:false`
  - [ ] 沙箱：`../`、符号链接、UNC、NUL 四类路径逃逸**全部被拒**（E2E 断言）
  - [ ] `run_python` 中断言 `socket`/`fs` 不可用；超时后进程被回收
  - [ ] 越权访问审计可查（会话事件 + `op_log`）
- **预估**：3 人日

---

## 5. 任务拆分粒度指引

### M0 本次认领（2026-10-03）

- **T-001**：骨架与质量门禁；扩展写权限为根配置、`.github/`、`scripts/`、`apps/` 与各 `packages/` 的配置/README/唯一出口及生成产物；依赖无。验收沿用 §4；编译/打包命令按 12 §2 分离，三平台打包由原生 CI runner 执行。
- **T-006**：Electron 离线空壳；写权限 `apps/desktop/**`、`packages/core/src/{index.ts,budgets.ts,error.ts,error.test.ts,budgets.test.ts}`；依赖 T-001 的配置。输出安全窗口、生成 preload 白名单、双语空壳和 Playwright 主路径；失败按 11 §1 的 AppError 转换；用户可见文案不得宣称已有导入或 Agent 功能。
- **T-007**：ADR 落档与首批样本；写权限 `docs/**`、`fixtures/**`、`services/parser/**`、`plugins/**` 及 README/许可产物；依赖 T-001。输出 ADR-01–12 的正式文档及 10 篇授权 PDF、来源/许可/sha256/页数清单；M2 再补人工锚点标注。
- **规范修订写权限**：`specs/README.md`、`specs/00-conventions.md`、本文件、方案 §5 及其变更记录；依据 ADR-13 修复冲突，禁止改 schema 或降低阈值。
- **交付证据**：`docs/m0-delivery.md` 按 §3 报告格式记录逐文件行数、实际命令结果、负例门禁、平台验证缺口。


| 信号 | 结论 |
|---|---|
| 一个任务需要改 3 个以上包 | **太大**，按包拆分 |
| 验收标准里有"并且/同时"超过 3 条 | **太大**，拆成多条 |
| 无法给出可测数值 | **规格不足**，先补规范 |
| 预估 > 5 人日 | 拆到 1–3 人日/卡，便于 AI 代理单轮完成 |
| 依赖未完成的任务 | 不得开工（写进卡片的"依赖任务"） |

**推荐节奏**：每个 AI 会话 = 1 张任务卡 + 1 次 `pnpm verify`；跨会话的任务必须在卡片里注明"接续 T-00x 的哪些产出"。

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结 |
| v1.1 | 2026-10-03 | V1 纳入 Agent：新增示例任务卡 T-004（Agent 运行时）与 T-005（权限门禁与沙箱），并给出可量化的验收标准 |
| v1.2 | 2026-10-03 | 认领 M0 T-001/T-006/T-007；明确跨目录授权、编译/打包及样本分阶段范围（ADR-13） |
