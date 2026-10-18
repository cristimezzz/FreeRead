# M0 技术验证：总结

- 完成日期：2026-10-18
- 路线图：[04-roadmap.md](../04-roadmap.md)

| 任务 | 结论 | 详情 |
|---|---|---|
| 评测集 | 从本地 Zotero 库选出 31 篇：双栏 24、含公式 8、表格多 11、扫描版 2、中文 5、长附录 5 | [parser-eval.md § 评测集](parser-eval.md#评测集) |
| 解析引擎对比 | 默认 MinerU，备选 Docling，快速模式 PyMuPDF，移除 Marker | [parser-eval.md](parser-eval.md) |
| Normalizer 原型 | PyMuPDF / MinerU / Docling / Marker 四个 Normalizer，输出均通过 IR 0.1 校验 | `core/freeread/infra/parsers/` |
| Tauri 2 + sidecar | 可行；安装包 17.6 MiB，两种退出方式均无残留进程；建议改用 onedir 并做代码签名 | [m0-tauri-sidecar.md](../m0-tauri-sidecar.md) |
| Zotero 7 本地 API | 可行；6 个分类、47 个条目、67/67 个 PDF 路径全部解析成功 | [zotero-local-api.md](zotero-local-api.md) |

## 交付物

- 评测报告：[parser-eval.md](parser-eval.md)
- ADR-0003 定稿：[adr/0003-pluggable-parser.md](../adr/0003-pluggable-parser.md)
- IR 0.1 定稿：[02-document-ir.md](../02-document-ir.md)，JSON Schema [schemas/ir-0.1.0.json](../schemas/ir-0.1.0.json)

## 需要在 M1 决定或处理的事项

1. ~~PyMuPDF 的 AGPL 许可~~：已决定 FreeRead 采用 AGPL-3.0-or-later，PyMuPDF 可以直接分发。MinerU 仍按"用户首次使用时下载、独立进程运行"的方式提供（见 ADR-0003）。
2. **MinerU 模型权重的许可证**：分发前逐个确认；权重改为首次使用时下载。
3. **代码签名与 onedir 打包**：Kaspersky 等主动防御会拦截无签名的新 exe。——M1-P7 已改为 onedir（见 [m1/README.md](../m1/README.md)）；代码签名仍待做。
4. ~~**常驻解析 worker**~~：M1-P3 已实现 MinerU 常驻 worker（`core/freeread/infra/parsers/resident.py`），空闲后自动退出。
5. **Normalizer 改进**：见 ADR-0003 的"跟进"。
6. ~~**Zotero 中没有父条目的独立 PDF** 是否导入~~：M1-P2 决定导入（`item_type = attachment`，`extra.standalone = true`，见 [01-architecture.md](../01-architecture.md)）。
