# M0 首批黄金集

10 篇 JMLR 2024 论文，PDF 原样保存。每篇第一页均明确标注 CC-BY-4.0；
作者保留版权，FreeRead 不更改论文。来源、标题、作者、页数、SHA256 与许可证据
逐项记录在 [index.json](index.json)，原始 BibTeX 在各论文目录。
许可全文：[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode)。
期刊授权政策：[JMLR 作者指南](https://jmlr.org/author-info.html#pub)。

本批覆盖英文单栏、数学公式、表格与图注；不代表 M2 最终 50 篇的全部类别。
当前仅用于导入/打包/协议开发，`annotationStatus=pending-M2`；标注者与标注日期为空，
因为尚未进行人工锚点标注。禁止用本批声称已达到 F1/IoU 质量门禁。

M2 标注规则：按 specs/03-anchor-model.md §7，在原始 PDF point 坐标中人工标注
blocks/outline/figures，选择每篇 20 条句子及 LineRef；存入各目录 expected/。
记录标注者/日期与复核人，扫描件和中文样本后续补齐。

采集工具 `scripts/collect-fixtures.py` 需要 Python 3.11 与 pypdf，仅供维护者刷新，
CI 使用已提交原始 PDF，不联网采集。`pnpm fixtures:check` 验证许可、索引、文件头尾与哈希。
