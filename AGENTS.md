# AGENTS.md — FreeRead 项目代理须知

> 本文件是**所有 AI 编码代理进入本仓库的第一入口**。任何实现任务开始前必须读完本文件。
> 项目：**FreeRead** — 本地优先（local-first）的开源论文辅助阅读器。
> 主仓许可：**AGPL-3.0**。当前状态：**规范阶段完成，代码尚未开始（M0 未启动）**。

---

## 1. 三十秒理解这个项目

- **做什么**：PDF 精读工具 —— 原文/重排双模式阅读 + 对照翻译 + 笔记 + 排版纠错 + **内置研究 Agent（V1）**。
- **不做什么**：不做云端账号、不做额度计费、**不做任何付费墙规避**（无 Sci-Hub、无机构代理绕过）、**V1 不做浏览器自动化抓取**。
- **技术栈**：Electron + TypeScript + React；版面解析用 Python sidecar（Docling/Marker/GROBID）；渲染 PDF.js；公式 KaTeX；存储 SQLite + 文件式知识库；翻译与 Agent 走本地 Ollama 或用户自带 Key。
- **架构地基**：**锚点模型**（句子 ↔ PDF 行区间 ↔ 版面区域），所有阅读体验建立在它之上；Agent 建立在**三面受限的能力模型**上（文献库只读 / 项目工作区读写 / NetGuard 白名单出网）。

---

## 2. 必读顺序（不要跳步）

1. `specs/README.md` —— 规范索引、**冻结词汇表**、命名规则、**禁止事项 F1–F9**
2. `specs/00-conventions.md` —— 代码风格、目录、提交、`pnpm verify`、DoD、性能预算 `BUDGETS`
3. 与本任务相关的规范文件（见 `specs/README.md` §2 索引）
4. 相关 `specs/schemas/*.json`（机器可读契约，是**唯一真源**）
5. 上游设计文档：`plan/FreeRead-技术方案与里程碑.md`（选型与里程碑）、`report/Scholaread-调研报告.md`（对标依据）

---

## 3. 硬规则（违反即 PR 被拒）

| 规则 | 说明 |
|---|---|
| **规范优先** | 实现与规范冲突时，先改规范（`spec:` 提交 + ADR），再改代码 |
| **renderer 零特权** | 渲染进程禁止 `fs` / `net` / `child_process` / `electron`；一切走 `window.fr.*`（`specs/06-ipc-contract.md`） |
| **唯一出站通道** | 所有网络请求必须经 `NetGuard`（`specs/09-fetch-compliance.md`）；白名单外一律拒绝 |
| **合规红线** | 代码中不得出现 Sci-Hub / 付费墙绕过 / 机构代理相关逻辑或域名；CI 有 grep 门禁 |
| **类型安全** | 禁止 `any`、`as any`、`@ts-ignore`；外部输入必须 `zod` 校验 |
| **错误不吞** | 一切失败转成 `AppError`，错误码必须在 `specs/11-error-handling.md` 登记 |
| **文案走 i18n** | 禁止硬编码用户可见文本 |
| **测试必写** | `packages/core`、`render-reflow`、`services/parser` 的改动必须带单测 |
| **不手改生成物** | `*.generated.ts` 由 `pnpm gen` 生成；改 schema 不改生成物 |
| **不越界写文件** | 只修改任务卡授权的目录 |

---

## 4. 常用命令

```bash
pnpm install --frozen-lockfile
pnpm gen            # JSON Schema → TypeScript 类型
pnpm verify         # typecheck + lint + test + gen:check + license + forbid（提交前必跑）
pnpm test           # 单元/集成测试
pnpm test:e2e       # Playwright E2E
pnpm eval:anchor --set golden --limit 10   # 锚点评测（小集，PR 用）
pnpm eval:anchor --set golden              # 全量评测（夜间/发布前）
pnpm build:dist     # 三平台打包
```

> 命令尚未落地（M0 前不存在）；M0 的任务卡 T-001 负责把它们建起来。**在此之前不要假装命令可用**。

---

## 5. 目录与所有权

```
apps/desktop/{src/main, src/renderer, src/preload}   # 应用层
apps/cli                                             # 无头运维（doctor/import）
packages/{core, render-reflow, translate, fetch, zotero, ui, parser-protocol, agent}
services/parser                                      # Python sidecar（Docling/Marker/GROBID/OCR）
specs/                                               # ← 本规范集（改动需 spec: 提交 + 变更记录）
plan/  report/                                       # 设计与调研文档（只读参考，除非被要求更新）
fixtures/golden/                                     # 黄金集（仅允许可再分发样本）
```

**写权限按包隔离**：一个任务只改一个包（必要时跨包需在任务卡中写明）。

---

## 6. 工作流程

```
读规范 → 认领任务卡（specs/13-task-template.md 格式）
      → 实现 + 单测 + i18n + 错误码登记
      → pnpm verify（必须全绿）
      → 按 specs/13-task-template.md §3 的格式提交交付报告
```

**遇到规范缺失或歧义时**：不要猜。提交规范修订（`spec:` 提交，含变更记录 + 必要时 ADR），或回报阻塞。**猜测比停下来更昂贵。**

**不要做的事**：不要把任务范围扩大（"顺手重构"）、不要引入新依赖（先按 `00-conventions.md` §10 流程）、不要调低验收阈值。

---

## 7. 质量门禁速查

| 门禁 | 阈值 | 出处 |
|---|---|---|
| 块结构 F1 | ≥ 0.90（P0 阻断） | `specs/03-anchor-model.md` §7 |
| 句子↔行 IoU | ≥ 0.98（P0） | 同上 |
| 内容覆盖率 | 100%（P0） | 同上 |
| 解析确定性 | 两次构建字节一致（P0） | INV-10 |
| 首屏渲染（1000 页） | ≤ 3000 ms | `BUDGETS` |
| 冷启动 | ≤ 2500 ms | `BUDGETS` |
| 位置恢复 | 5/5 全中（P0） | `specs/10-testing.md` E4 |
| core 分支覆盖 | ≥ 90% | `specs/00-conventions.md` §7 |

---

## 8. 当前状态与下一步

| 阶段 | 状态 |
|---|---|
| 调研（Scholaread 对标） | ✅ 完成（`report/`） |
| 技术方案与选型（12 条 ADR） | ✅ 完成（`plan/`） |
| 技术规范集（含 `14-agent.md`） | ✅ 完成（`specs/`） |
| **代码骨架（M0）** | ⏳ **未开始** —— 起点是任务卡 `T-001`（`specs/13-task-template.md` §4） |

**下一步（按顺序）**：T-001 建骨架与门禁 → T-002 锚点构建器 → T-003 位置恢复 → T-004 Agent 运行时 → 其余按 M0–M7 展开。

---

## 9. 已决与待决事项

**已决（2026-10-03）**：

1. **主仓许可 = AGPL-3.0**（见 `plan/…` §12.1）；
2. **接受 Python sidecar**（Docling 主 / Marker 备 / GROBID 元数据，按需下载，无 Python 时降级 `rule`）；
3. **V1 内置 Agent**（取代原 ADR-11 的 V2 计划）：14 个工具、4 级权限、项目工作区、会话事件流；**V1 不含浏览器自动化**（V2 评估）。

**仍待人类决定**：是否引入 CLA 以保留双许可可能（`plan/…` §12.2）。
