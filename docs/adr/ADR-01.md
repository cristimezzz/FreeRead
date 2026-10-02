# ADR-01 应用形态：Electron + TypeScript ✅

- 状态：接受；日期：2026-10-03
- 来源：[技术方案 §2](../../plan/FreeRead-技术方案与里程碑.md)

| 维度 | 内容 |
|---|---|
| **选择** | Electron 3x + TypeScript 5.x + React 19 + Vite；`electron-builder` 打包，`electron-updater` 更新 |
| **理由** | ① 目标能力（多标签内嵌浏览器、屏幕截图 OCR、Pyodide 沙箱、本地 sidecar 管理）在 Electron 上最成熟；② PDF.js / KaTeX / Mermaid 生态都是 Web 技术；③ 与 Scholaread 同构，迁移与对标成本最低；④ 团队招聘面最广 |
| **被否** | **Tauri 2**：体积/内存更优，但多 WebView 管理、sidecar、跨平台 WebView 差异（WebView2/WebKit）会显著增加 V1 成本 → 列为 **V2 评估项**；**PyQt/Qt**：Web 渲染与前端生态劣势；**纯 Web PWA**：无法满足本地文件、离线解析、系统级截图 |
| **风险** | 安装包体积大（预计 150–250 MB，含 Python sidecar）→ 用 sidecar 按需下载（首次启用重排时下载）来规避 |
