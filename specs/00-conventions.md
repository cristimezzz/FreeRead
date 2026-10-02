# 00 · 编码与协作规范

> 本文件是**强制规范**。AI 代理与人类工程师同等适用。违反者 PR 被拒（部分由 CI 自动阻断）。

---

## 1. 语言约定

| 场景 | 语言 |
|---|---|
| 代码标识符、注释、提交信息、分支名、日志 | **英文** |
| 用户可见文案 | 必须走 i18n key（`zh-CN` 主、`en` 次），**不得硬编码** |
| 规范文档、ADR、PR 描述 | 中文 |
| 错误信息（面向开发者） | 英文；面向用户的提示由错误码映射（`11-error-handling.md`） |

i18n 文件位置：`apps/desktop/src/renderer/i18n/{zh-CN,en}.json`；key 命名见 `README.md` §3。

---

## 2. TypeScript 基线配置

```jsonc
// tsconfig.base.json（所有包 extends 此文件）
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,     // 数组/字典访问必须判空
    "exactOptionalPropertyTypes": true,   // 可选属性不可显式赋 undefined
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "resolveJsonModule": true
  }
}
```

**类型规则**

1. 禁止 `any` / `as any` / `@ts-ignore`（`@ts-expect-error` 需附 issue 链接与理由注释）。
2. 对外部输入（IPC、文件、HTTP、JSON Schema 产物）**必须**用 `zod` 校验后再进入领域层。
3. 领域类型定义在 `packages/core/src/domain/`，**不得**从 `*.generated.ts` 直接 import 到 UI（经 `core` 再导出）。
4. 可辨识联合优先于可选字段组合；穷尽分支用 `switch` + `never` 兜底：
   ```ts
   default: { const _exhaustive: never = value; throw new AppError('FR-SYS-001', { value }); }
   ```
5. 时间统一用 **UTC 毫秒整数**（`number`）；对外暴露 ISO 字符串仅在 `meta.json` 等人类可读文件中。

---

## 3. 目录与文件

- 目录结构以 [方案 §3.2](../plan/FreeRead-技术方案与里程碑.md) 为准，不得擅自新增顶层目录。
- 单文件行数 ≤ **400**（超出则拆分）；单函数 ≤ **60** 行；圈复杂度 ≤ **12**（ESLint 强制）。
- 每个 `packages/*` 必须有：`package.json`（含 `license: AGPL-3.0`）、`README.md`（用途+边界+导出面）、`src/index.ts`（唯一出口）。
- 禁止跨包相对路径导入（如 `../../other-package/src/x`）；必须走包名 + `exports` 字段。

---

## 4. 模块边界（由 `eslint-plugin-boundaries` 机检）

```jsonc
// .eslintrc.boundaries.jsonc（要点）
{
  "rules": {
    "boundaries/element-types": [2, { "default": "disallow", "rules": [
      { "from": "renderer", "allow": ["ui", "core-types", "ipc-client"] },
      { "from": "main",     "allow": ["core", "parser-protocol", "translate", "fetch", "zotero", "ui"] },
      { "from": "core",     "allow": ["core"] },
      { "from": "render-reflow", "allow": ["core"] }
    ]}],
    "no-restricted-imports": [2, { "paths": [
      { "name": "fs", "message": "renderer 禁止直接访问文件系统，请走 IPC（specs/06）" },
      { "name": "node:fs", "message": "同上" },
      { "name": "electron", "message": "renderer 仅可通过 preload 暴露的 window.fr 访问" }
    ]}]
  }
}
```

---

## 5. 日志规范

```ts
logger.info('parse.completed', { doc_id, engine: 'docling', pages: 28, elapsed_ms: 4120 });
```

- 事件名 `domain.action`（小写点分）；字段 `snake_case`；
- 级别：`error`（用户可感知失败）/`warn`（降级、重试）/`info`（生命周期）/`debug`（开发，默认关闭）；
- **脱敏白名单制**：以下字段**禁止**写入日志 —— `api_key`、`token`、`authorization`、文件绝对路径中的用户名段、笔记全文、译文全文（只记长度与 hash）；
- 日志文件：`%APPDATA%/FreeRead/logs/app-YYYY-MM-DD.log`，winston-daily-rotate-file，保留 7 天，默认不上传。

---

## 6. Git 与提交

- 分支：`feat/<scope>-<slug>`、`fix/<scope>-<slug>`、`spec/<slug>`、`chore/<slug>`；
- 提交：Conventional Commits，scope 用包名：
  ```
  feat(core): add sentence segmentation with abbreviation guard
  fix(parser): normalize docling bbox to pdf points
  spec(anchor): bump schemaVersion to 2
  ```
- **原子提交**：一个提交只做一件事；禁止把格式化与逻辑混在一起；
- PR 必须包含：变更摘要、影响的规范条目、测试证据（命令+输出摘要）、截图（涉及 UI 时）；
- **禁止** `--no-verify` 跳过钩子。

---

## 7. 质量门禁（`pnpm verify`，CI 与本地一致）

```bash
pnpm typecheck   # tsc --build --force（所有包）
pnpm lint        # eslint + boundaries + no-restricted-imports
pnpm test        # vitest run --coverage（core/render-reflow 覆盖率 ≥ 90%，其余 ≥ 70%）
pnpm gen:check   # 校验 *.generated.ts 与 schemas 一致（不一致即失败）
pnpm license     # License Gate 黑名单 + THIRD_PARTY_NOTICES 生成
pnpm forbid      # 禁用域名/关键词 grep 门禁（sci-hub 等）
```

`pnpm verify` = 上述全部；**未通过不得合并**。

---

## 8. 完成定义（DoD）

一个任务只有同时满足以下 9 条才算完成：

1. 实现与相关规范一致；规范不足处已补规范（含 ADR 条目）；
2. `pnpm verify` 全绿；
3. 新增/修改逻辑有单测；`core`/`render-reflow` 分支覆盖 ≥ 90%；
4. 涉及 UI 的改动有 Playwright E2E 用例（至少 1 条主路径）；
5. 所有用户可见文案已进 i18n（zh-CN + en）；
6. 所有失败路径返回 `AppError` 且错误码已在 `11-error-handling.md` 登记；
7. 无 `TODO`/`FIXME`/调试输出残留；
8. 相关规范文件与 `README.md` §2 索引状态已更新；
9. PR 描述含"验收标准自测结果"。

---

## 9. 性能预算（写进常量，禁止散落魔数）

```ts
// packages/core/src/budgets.ts
export const BUDGETS = {
  FIRST_PAINT_1000_PAGES_MS: 3000,
  SCROLL_FPS_MIN: 55,
  COLD_START_MS: 2500,
  SIDECAR_HEALTH_MS: 1500,
  MEMORY_PEAK_MB: 1200,
  ANCHOR_IOU_MIN: 0.98,
  BLOCK_F1_MIN: 0.90,
  LOW_CONFIDENCE_THRESHOLD: 0.60,
  PAGE_BITMAP_DPI: 110,
  CACHE_MAX_MB: 500,
  TRANSLATE_BATCH_CHARS: 4000,
} as const;
```

任何新性能阈值都必须加进此文件并在 `10-testing.md` 登记对应指标卡。

---

## 10. 依赖引入流程

1. 先查是否已有同类依赖（禁止重复造轮子/重复引入）；
2. 运行 `pnpm license check <pkg>` 确认不在黑名单；
3. 影响架构的依赖 → 追加 ADR；
4. 提交信息写清"替换了什么/省了什么"；
5. 前端依赖需检查 bundle 体积影响（`pnpm size`），单包 > 200 KB 需说明理由。

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结 |
