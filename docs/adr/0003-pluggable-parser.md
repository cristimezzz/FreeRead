# ADR-0003：可插拔的 PDF 解析引擎

- 状态：**已接受**（M0 评测后定稿）
- 日期：2026-10-17 提议；2026-10-18 接受
- 依据：[M0 解析引擎评测报告](../m0/parser-eval.md)

## 背景

解析质量决定了重排、翻译、问答的上限。各解析引擎在版面检测、公式识别、表格还原、速度、硬件要求上差异很大，而且这个领域迭代很快。

## 候选引擎

| 引擎 | 特点 | 硬件 | M0 结论 |
|---|---|---|---|
| MinerU 4.x | 版面、公式（LaTeX）、表格、OCR；原生区分标题 / 参考文献 / 脚注 | GPU 可选（4GB 可用） | **默认高质量引擎** |
| Docling 2.x | 结构化输出、TableFormer 表格、MIT 许可 | CPU / GPU | **备选高质量引擎** |
| Marker 1.x | 输出 Markdown / JSON | GPU | **移除**：4GB 显存下 OCR 溢出到共享内存，单页可达数分钟；GPL 许可 |
| PyMuPDF（快速模式） | 只取文本层和坐标，无公式 / 表格 / OCR | CPU，每页约 0.05 s | **快速模式**（分发前需处理 AGPL，见下） |
| 云端 API | 质量高，无需本地 GPU；文档内容离开本机 | 无 | 未评测，M4 再议 |
| GROBID（辅助） | 参考文献与元数据结构化 | 需 Java 服务 | 未评测 |

## 决定

定义统一的 `Parser` 接口和每个引擎专属的 `Normalizer`，所有引擎输出都转换为 Document IR（`core/freeread/infra/parsers/`）。

1. **默认高质量引擎为 MinerU**（`effort=medium`：本地版面 / 公式 / OCR / 表格模型，不使用 VLM）。M0 评测（31 篇、92 个 golden 页）中，它的类型准确率为 84.1%（Docling 70.4%），阅读顺序 τ 为 0.98（Docling 0.96），参考文献 F1 为 0.99，扫描页检测 F1 为 0.98。峰值显存约 2.6 GB；常驻进程时每页边际耗时约 0.6 s，冷启动加载模型约 40 s。
2. **Docling 作为备选**，可以在设置中切换，也可以按页重解析。它在整图、图注和表格结构上优于 MinerU，许可证最宽松（MIT）。
3. **快速模式为 PyMuPDF**，在高质量解析完成之前先出一版可读的 IR；高质量结果就绪后按 IR §8 的规则迁移。扫描页（无文本层）只能走高质量引擎。
4. **每个重型引擎运行在独立的 Python 环境 / 进程中**，通过 `scripts/engines/run_<engine>.py` 的薄包装调用，原生输出存到 `raw/`。这样可以避免 torch 等依赖冲突，也便于 Normalizer 升级后直接从 `raw/` 重建 IR。
5. **调用 MinerU 时绕过其 CLI 和本地服务**，直接调用 `mineru.backend.analyze.doc_analyze`：MinerU 4.x 的 CLI 默认开启匿名遥测，并且提供把文档上传到 mineru.net 的远程解析选项。FreeRead 必须保证文档不离开本机。

## 后果

- 正面：可以随时替换或新增引擎，不影响上层功能；用户可以按文档选择引擎重新解析。M0 中已有四个 Normalizer 证明了 IR 的通用性。
- 负面：要为每个引擎维护 Normalizer；不同引擎的块粒度不同（例如 MinerU 按子图切图，Docling 给整图），需要评测集持续回归（`scripts/m0_report.py` 可以直接复用）。
- 许可证：
  - MinerU：Apache-2.0 加附加条款（合并口径 MAU 超过 1 亿或月收入超过 2000 万美元需另行取得商业许可；以 MinerU 提供在线服务须显著标明）。其模型权重的许可证需要在分发前逐个确认。
  - Docling：MIT。
  - **PyMuPDF：AGPL-3.0 / 商业双许可**。分发 sidecar 之前，要么把快速模式改为基于 pypdfium2（Apache-2.0 / BSD）实现，要么接受 AGPL 义务。M1 决定。
- 跟进（M1）：
  - MinerU Normalizer 合并"同一图注之上的相邻 figure 块"，并过滤子图标号。
  - Docling Normalizer 补充 title、reference、footnote 的位置 / 关键词规则。
  - 所有 Normalizer 识别 abstract 和 author_info。
  - sidecar 保持一个常驻的解析 worker 进程，摊薄模型加载开销。
  - 模型权重改为首次使用时下载，不打进安装包（与 ADR-0001 一致）。
