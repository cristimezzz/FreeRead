# ADR-13：M0 工程验收与分阶段边界

- 日期：2026-10-03；状态：接受
- 背景：方案 §5 的 M0 仍写「拦截 AGPL」，与已决 AGPL-3.0 主仓及规范 12 §5 冲突；T-001 写权限不足以覆盖可运行空壳。
- 决策：允许 AGPL/GPLv3，负例使用 SSPL；`pnpm build` 编译，`pnpm build:dist` 在三平台原生 CI runner 产出安装包，M0 不要求 M7 的签名发布。禁止以空文件代替安装包。
- M0 只交付无业务的离线空壳、机器契约生成、工程门禁、ADR 与 10 篇授权 PDF。人工锚点标注及评测属于 M2；M1–M6 的通道生成类型与白名单，但尚未实现的 handler 不注册。
- `*.generated.ts` 属于机器产物，豁免人工文件行数及复杂度限制；生成器本身不豁免。schema 未改，不 bump schemaVersion。
- 依赖下载与授权样本采集属于开发工具，使用构建工具原生网络；应用运行时仍必须经 NetGuard，M0 应用不出网。
- 依赖：按 ADR-01/02/12 引入 Electron、React、Vite、TypeScript、pnpm/Turbo、ESLint/boundaries、dependency-cruiser、Vitest/coverage、Playwright、Prettier、electron-builder、json-schema-to-typescript、zod、AJV。`license-checker-rsc` 在 npm 返回 404，改用 pnpm 原生 `licenses list --json`，省去重复依赖；其输出仍经黑名单/允许表严格校验。仅加载 M0 必需依赖，解析/数据库/LLM/更新依赖在所属里程碑引入。
- 影响：三平台产物的验收必须有实际 CI 或本机证据；仅提交工作流不能声称 CI 全绿。源码无远端时，以随包的对应源码归档提供源码，不虚构下载 URL。
- 许可核验：electron-builder 的传递依赖 `truncate-utf8-bytes` 为 WTFPL，其 [SPDX 正文](https://spdx.org/licenses/WTFPL.html) 无使用/再分发限制，补充允许该标识；禁止许可表保持不变。
- 启动验收：首轮 CI 的 Playwright 启动含 Node/Chromium 调试器连接等待（macOS 5.3 s、Linux 8.4 s）。改为单独启动无调试器 Electron，从进程 spawn 前至 ready-to-show 首帧测量墙钟；阈值保持 2500 ms，功能/权限仍由 Playwright 实测。
