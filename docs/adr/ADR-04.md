# ADR-04 版面解析：Docling(主) + Marker(备) + GROBID(元数据)，Python sidecar ✅

- 状态：接受；日期：2026-10-03
- 来源：[技术方案 §2](../../plan/FreeRead-技术方案与里程碑.md)

| 维度 | 内容 |
|---|---|
| **选择** | 独立 **Python 3.11 sidecar 进程**（`python -m freeread_parser`），通过 **本地 HTTP/JSON-RPC** 暴露 `parse()`；主进程管理其生命周期；**必带纯规则降级路径**（PDF.js 文本行聚类 + XY-Cut） |
| **理由** | ① Docling **MIT**、Marker **Apache**、GROBID **Apache** 的功能/中文覆盖最佳（许可已无约束，主仓为 AGPL-3.0，与 MIT/Apache 单向兼容）；② Python 是这三个项目的原生语言，重写代价极高；③ sidecar 进程用于**隔离模型崩溃与内存峰值**、支持热替换引擎，并让用户可外挂 MinerU/PyMuPDF/PDFMathTranslate 等更重的组件而不影响主进程稳定性 |
| **被否** | 全 ONNX 端侧重写（工期 ×3，且中文表格效果差）；直接内置 pdf2htmlEX（GPLv3 **现已兼容**，但项目自 2020 年起停更、输出为绝对定位 HTML，不适合做语义重排的**主**引擎，仅作参考实现） |
| **风险** | sidecar 体积与启动延迟 → 冷启动预算 ≤ 1.5 s、模型懒加载；无 Python 环境时**自动降级**到规则解析并在 UI 明示"当前为快速模式" |

**Sidecar 协议（冻结版，V1 不再改）**

```
POST http://127.0.0.1:<random-port>/v1/parse
{ "docId": "...", "pdfPath": "...", "options": { "engine": "docling|marker|rule", "ocr": true, "lang": ["en","zh"] } }
→ 202 { "jobId": "..." }
GET /v1/jobs/<jobId>            → { "state": "running|done|failed", "progress": 0.0-1.0, "model": DocAnchorModel|null, "error": null }
POST /v1/cancel/<jobId>
GET  /v1/health                 → { "ok": true, "engines": ["docling","marker","rule"], "version": "..." }
```
