# ADR-06 OCR：PaddleOCR(中文优先) / Tesseract(轻量兜底) ✅

- 状态：接受；日期：2026-10-03
- 来源：[技术方案 §2](../../plan/FreeRead-技术方案与里程碑.md)

- **选择**：默认 **PaddleOCR (Apache-2.0)**（sidecar 内）；无 OCR 需求或资源受限时用 **Tesseract (Apache-2.0)**。
- **理由**：Scholaread 用 Tesseract，其中文效果一般；PaddleOCR 在中文扫描件上明显更好且许可宽松。
- **风险**：模型下载体积 → 首次启用时下载并校验 SHA256。
