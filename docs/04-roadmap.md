# 路线图

- 版本：0.1（草案）
- 更新日期：2026-10-18

时间为单人全职的粗略估计，随 M0 结论调整。

## M0 技术验证（1–2 周）

目标：消除最大的技术风险，确定 IR。

- [x] 建立评测集：20–50 篇代表性 PDF（双栏、公式密集、表格多、扫描版、中文论文、长附录）。（本地 Zotero 库 31 篇，[清单](../core/tests/fixtures/pdfs/manifest.yaml)）
- [x] 对比至少两个高质量解析引擎 + PyMuPDF 快速模式：块类型准确率、阅读顺序、公式质量、耗时、显存占用。（MinerU / Docling / PyMuPDF，Marker 因 4GB 显存下过慢移除；[报告](m0/parser-eval.md)）
- [x] 用选定引擎实现 Normalizer 原型，输出符合 [IR 0.1](02-document-ir.md) 的 JSON。（四个引擎的 Normalizer，校验问题 0）
- [x] 验证 Tauri 2 + Python sidecar 在 Windows 上的打包、启动时间、进程退出清理（[结果](m0-tauri-sidecar.md)）。
- [x] 验证 Zotero 7 本地 API 能取到条目、分类和附件路径。（[结果](m0/zotero-local-api.md)）

**交付**：评测报告、ADR-0003 定稿、IR 0.1 定稿。——已完成，见 [M0 总结](m0/README.md)。

## M1 MVP：导入、重排、翻译（4–6 周）

- [x] Core Service 骨架：FastAPI、SQLite + Alembic、任务队列、SSE。
- [x] Zotero 本地 API 导入 + 手动导入 PDF。
- [x] 解析任务链：import → parse；IR 入库。（Normalizer 跟进项另行处理）
- [x] 前端：文献库列表、分类树；阅读器（pdf.js 原版视图 + 重排视图）；双向定位。
- [x] LLM Gateway：OpenAI 兼容 provider、缓存、用量记录；钥匙串保存密钥。
- [x] 块级翻译：可视区域优先、占位保护、对照 / 交替 / 仅译文显示。

**验收**：从 Zotero 导入一个分类，打开任意一篇论文，3 分钟内可阅读重排版并看到逐段译文；断网后已翻译内容仍可阅读。

- [x] 打包：sidecar 改为 PyInstaller onedir，经 `bundle.resources` 安装；NSIS 安装包复测体积、启动时间、退出残留。
- 验收结果（2026-10-18，[详情](m1/README.md)）：打包版 sidecar + 本机 Zotero + mock LLM 下，39 s 内看到重排版和逐段译文，离线可读 ✅。本机安装版的文件对话框导入、钥匙串保存与重启后读取、翻译也已实测通过 ✅；未用真实 LLM 复测。
- [x] 收尾：启用 Tauri CSP；合并后 figure 截图逐张检查；Normalizer 升级后启动时自动重新规范化旧 IR（补验证时发现此前不会触发，[详情](m1/normalizer-followups.md#补充验证2026-10-18)）。

**M1 已完成（2026-10-18）**。需要用户操作的发布前事项：代码签名、用真实 LLM provider 复测、启用 CSP 后在安装版里点一遍（见 [m1/README.md 遗留](m1/README.md#遗留)）。

转入 M2 的跟进：

- [x] sidecar 启动失败或中途退出时，壳把 `Terminated` 事件推给前端（`core-terminated` 事件 + `core_status` 命令，前端立即报错并显示 stderr 末尾）。
- [ ] footnote 规则（`docling.mark_footnotes`）移到公共层，PyMuPDF / MinerU 共用。
- [ ] sidecar 启动时间出现 1.03 s / 1.52 s 两档跳变，查原因。
- [x] 打包版的 MinerU / Docling：设置里一键安装到数据目录下的独立环境（`infra/parsers/installer.py`：uv + 托管 Python 3.12 + 固定版本的引擎包）。未在安装版上实测完整安装（需下载数 GB）。

## M2 理解：总结与单篇问答（3–4 周）

- [x] 嵌入任务、sqlite-vec 检索 + FTS5 混合检索。（内置本地嵌入模型，阅读器文内搜索；[详情](m2/README.md)）
- [x] 分层总结，结构化模板，引用可跳转。（评测集 29 篇引用覆盖率 100%；忠实度人工抽检、耗时优化见[详情](m2/summary.md)）
- [x] 单篇论文问答（线性对话），答案带引用并校验。（评测集 186 题展示引用 100% 有效；[详情](m2/qa.md)）
- [x] 术语表（自动抽取 + 编辑），整篇后台翻译。（翻译时注入段落里出现的术语；[详情](m2/glossary.md)）
- [x] 高亮批注；导出 Markdown。（重排视图选中原文高亮 / 批注，重新解析后按原文重新定位；[详情](m2/annotations.md)）
- [x] Zotero sqlite 快照导入；增量同步。（Zotero 没运行时自动改读快照；本地 API 增量，每 7 天全量；[详情](m2/zotero-sync.md)）

**验收**：评测集上总结的引用覆盖率 ≥ 90%；问答答案中的引用 100% 指向存在的块。

## M3 关联：知识图谱与图状问答（4–6 周）

- [x] 知识图谱抽取任务、实体消歧、关系出处。（按章节组抽取，关系必带出处块、数值核对原文；别名精确相同自动合并，嵌入 + 模型判定的作为可能重复由用户确认；阅读器图谱面板可合并 / 拆分；[详情](m3/kg.md)）
- [ ] 参考文献与本地库关联（`linked_doc_id`），文献引用图。
- [ ] 跨文献混合检索问答（向量 + 图扩展）。
- [ ] 图谱浏览视图（Cytoscape.js）。
- [ ] 问答画布：问答树、分叉追问、固定原文片段、拖入实体（React Flow）。

**验收**：在一个 30 篇论文的分类上，能回答"哪些方法在数据集 X 上用指标 Y 报告了结果，数值是多少"，答案中每个数值都能跳转到原文。

## M4 生态与打磨（持续）

- [ ] Zotero Web API 同步与写回（总结作为笔记）。
- [ ] 分类级综述、多篇论文对比表。
- [ ] 更多解析引擎。
- [x] 云端 / 自部署解析服务：MinerU（mineru-api、mineru.net）与 docling-serve（ADR-0008）。
- [ ] 导出到 Obsidian / Logseq。
- [ ] macOS、Linux 打包；自动更新。
- [ ] 插件机制（自定义总结模板、提示词、解析引擎）。

## 风险跟踪

| 风险 | 影响 | 应对 | 负责里程碑 |
|---|---|---|---|
| 解析质量不足 | 所有功能 | 多引擎、保留原版兜底、按页重解析 | M0 / M1 |
| 用户无 GPU | 解析慢或质量差 | 快速模式 + 可选云解析 | M1 |
| LLM 成本过高 | 用户流失 | 缓存、按需翻译、按任务选廉价模型、费用面板 | M1 / M2 |
| Python sidecar 打包问题 | 无法分发 | M0 提前验证 | M0 |
| 实体消歧不准 | 图谱噪声大 | 保守合并、出处可查、用户可手动合并 / 拆分 | M3 |
