# ADR-03 PDF 渲染：PDF.js ✅

- 状态：接受；日期：2026-10-03
- 来源：[技术方案 §2](../../plan/FreeRead-技术方案与里程碑.md)

- **选择**：`pdfjs-dist`（**Apache-2.0**），自建 viewer 而非直接用其 demo viewer。
- **理由**：事实标准、许可宽松、可按页取文本层与坐标（`getTextContent()` 提供我们需要构建锚点的行盒）。
- **被否**：PDFium/WASM（集成复杂、坐标 API 不如 PDF.js 友好）；**PyMuPDF**（AGPL——在新许可下**可用**，但 V1 仍优先 PDF.js：其 `getTextContent()` 的行盒与坐标更贴合锚点构建；PyMuPDF 留作 sidecar 内的解析加速备选）。
- **风险**：大文档内存 → 采用"按页懒渲染 + 位图 LRU 缓存"（见 §6 性能门禁）。
