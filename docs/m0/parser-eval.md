# M0 解析引擎评测报告

- 日期：2026-10-18
- 结论落地：[ADR-0003](../adr/0003-pluggable-parser.md)（已接受）
- 原始数据：[parser-eval-results.json](parser-eval-results.json)（由 `scripts/m0_report.py` 生成）
- 复现步骤见文末

## 结论

1. **默认高质量引擎：MinerU 4.x（`effort=medium`，本地版面 / 公式 / OCR / 表格模型，不使用 VLM）。** 它在块类型、阅读顺序、标题、参考文献和扫描页上都明显领先。在 4GB 显存的笔记本 GPU 上可以跑（峰值显存约 2.6 GB）。如果 sidecar 常驻一个解析 worker 进程，每页边际耗时约 0.6 秒。
2. **备选高质量引擎：Docling 2.x（MIT）。** 检测率与 MinerU 持平，图、图注和表格结构更好，但类型判断较弱：标题记成 section_header，参考文献记成 list_item，脚注识别差。适合作为"许可证最宽松"的选项，以及按页重解析时的第二意见。
3. **快速模式：PyMuPDF。** 31 篇共 460 页不到 20 秒。阅读顺序可用（τ = 0.92），但块切分和类型很粗，没有公式和表格，扫描页完全不可用。它的作用是让用户在模型下载完或解析完成之前就能先读。**PyMuPDF 是 AGPL-3.0 / 商业双许可**；FreeRead 已决定采用 AGPL-3.0-or-later，因此可以直接分发 PyMuPDF。
4. **Marker 已从候选中移除。** 在 4GB 显存上，它的 surya OCR 会把显存占满并溢出到共享内存。3 个抽样页的耗时在 57–695 秒之间，第 4 篇跑了 16 分钟以上仍未完成，无法作为默认引擎。另外，Marker 2.x 需要 Docker vLLM 或单独下载的 llama-server，许可证（GPL-3.0，模型权重有商用限制）也不适合分发。
5. **IR 0.1 可以定稿。** PyMuPDF、MinerU、Docling 三个 Normalizer 在 31 篇共 460 页（1,380 页次）的输出上都通过了 IR 校验，问题数为 0（Marker Normalizer 在已完成的 3 篇上同样为 0）。实现过程中确定的约定已经写进 [IR 规范 §3.5–3.6](../02-document-ir.md)。

## 评测集

本地 Zotero 库（通过 Zotero 7 本地 API 读取，见 [zotero-local-api.md](zotero-local-api.md)）中的 **31 篇** PDF，按特征自动打标签后分层抽样，清单见 `core/tests/fixtures/pdfs/manifest.yaml`。PDF 不入库。

| 类别 | 篇数 | 说明 |
|---|---|---|
| 双栏 | 24 | Nature / Science / Cell / PNAS 等版式 |
| 含公式 | 8 | 按数学字体占比判定；本库以生物论文为主，显示公式总数较少 |
| 表格多 | 11 | |
| 扫描版 | 2 | 把两篇老论文栅格化成无文本层的图片 PDF（`synthetic_scan`）；库中另有 1997 年 Nature 原始扫描件（带 OCR 文本层） |
| 中文 | 5 | PDFMathTranslate 生成的 zh-CN 单语译本（版式与英文原版相同，文字为中文） |
| 长附录 | 5 | 25 页以上 |

去重时发现同一篇 Science 论文有两份下载（Zotero 中一份没有标题），已移除其中一份，所以是 31 篇而不是 32 篇。

## Golden 的构造

用户选择了"完全自动生成"，因此 golden 不依赖人工标注，构造方式如下（规范见 `core/tests/golden/GUIDELINES.md`）：

1. **抽页**：每篇抽 3 页（首页、正文中段、表格最多的页或参考文献页），共 93 页。其中 1 页因 PDF 文本层与渲染错位、无法可靠标注而排除，最终为 **92 页、1,159 个块**。
2. **共识**：同一页上，MinerU 与 Docling 的块按 IoU ≥ 0.5 聚类；两者类型一致的簇直接采纳（727 块）。
3. **规则**：参考文献列表中"一方判为 list_item、一方判为 reference_entry"的块统一为 reference_entry（119 块）。
4. **Claude 复核**：其余簇（类型冲突、只有一个引擎检测到），由 Claude 对照页面渲染图逐页按标注规范裁决：删除页眉 / 水印 / 标志，统一"一个图注对应一张整图"，修正 title / author_info / abstract / footnote 等类型，必要时补框。共 313 块，修正记录见 `core/tests/golden/corrections/*.yaml`。
5. **文本**：从 PDF 文本层按框截取，不依赖任何引擎；扫描页取两个引擎 OCR 结果中较长的一份，不做逐字校对。

**偏差与局限**（解读数字前请注意）：

- golden 的框来自 MinerU 与 Docling，因此对这两个引擎有利；PyMuPDF 没有参与共识，它的检测 F1 偏低，有一部分是"粒度不同"而不是"错误"。
- 两个引擎都漏掉的块不在 golden 中（复核时只补了明显缺失的整图）。
- 文本取自 PDF 文本层，所以 PyMuPDF 的文本 NED 天然最低，这一项不能说明它"识别更准"。
- 公式只有 11 个，而且 golden 的 LaTeX 取两个引擎中较长的一份，LaTeX NED 有明显偏差，**只作参考**。
- abstract、author_info、other 这几类只有 golden 会标（三个 Normalizer 都不产出），所以三家这几项都是 0；粗粒度准确率把它们并入"文本"类后可以比较。

## 结果

### 总体质量（golden 抽样页）

| 引擎 | 检测 F1 | 类型准确率 | 粗粒度类型准确率 | 阅读顺序 τ | 文本 NED↓ | 公式召回 | 公式 LaTeX NED↓ |
|---|---|---|---|---|---|---|---|
| pymupdf | 0.472 | 65.8% | 77.7% | 0.923 | 0.038 | 0.0% | – |
| mineru | 0.881 | 84.1% | 93.8% | 0.981 | 0.064 | 90.9% | 0.358 |
| docling | 0.878 | 70.4% | 83.4% | 0.960 | 0.075 | 72.7% | 0.053 |

### 按类别：检测 F1 / 粗粒度类型准确率 / 阅读顺序 τ

| 类别 | pymupdf | mineru | docling |
|---|---|---|---|
| 全部（31 篇） | 0.47 / 77.7% / 0.92 | 0.88 / 93.8% / 0.98 | 0.88 / 83.4% / 0.96 |
| 双栏（24 篇） | 0.49 / 81.9% / 0.94 | 0.87 / 93.9% / 0.99 | 0.89 / 85.2% / 0.96 |
| 含公式（8 篇） | 0.53 / 91.6% / 0.94 | 0.83 / 95.0% / 0.98 | 0.91 / 93.2% / 0.92 |
| 表格多（11 篇） | 0.36 / 73.8% / 0.89 | 0.84 / 96.4% / 0.99 | 0.88 / 72.9% / 0.96 |
| 扫描版（2 篇） | 0.00 / – / – | 0.98 / 96.4% / 0.97 | 0.84 / 84.7% / 0.98 |
| 中文（5 篇） | 0.34 / 76.3% / 0.99 | 0.76 / 94.6% / 1.00 | 0.79 / 94.1% / 0.91 |
| 长附录（5 篇） | 0.38 / 51.4% / 0.97 | 0.82 / 89.3% / 0.99 | 0.88 / 65.6% / 0.97 |

### 各类型 F1（全部）

| 类型 | pymupdf | mineru | docling |
|---|---|---|---|
| abstract | 0.00 | 0.00 | 0.00 |
| author_info | 0.00 | 0.00 | 0.00 |
| caption | 0.60 | 0.58 | 0.83 |
| equation | 0.00 | 0.83 | 0.84 |
| figure | 0.00 | 0.35 | 0.56 |
| footnote | 0.00 | 0.67 | 0.26 |
| heading | 0.22 | 0.91 | 0.70 |
| list_item | 0.00 | 0.00 | 0.15 |
| other | 0.00 | 0.00 | 0.00 |
| paragraph | 0.37 | 0.81 | 0.75 |
| reference_entry | 0.13 | 0.99 | 0.57 |
| table | 0.00 | 0.91 | 1.00 |
| title | 0.68 | 0.97 | 0.00 |

### 速度与资源（RTX 3050 Ti Laptop 4GB / Windows 11）

| 引擎 | 成功 / 运行 | 处理页数 | 秒/页（中位） | 启动开销（拟合） | 边际秒/页（拟合） | 峰值内存 | 峰值显存（中位 / 最大） | IR 校验问题 |
|---|---|---|---|---|---|---|---|---|
| pymupdf | 31 / 31 | 460 | 0.02 | -0.3 s | 0.05 | 87 MB | 0 / 0 MB | 0（0 篇） |
| mineru | 31 / 31 | 460 | 3.55 | 42.3 s | 0.61 | 4675 MB | 2058 / 2649 MB | 0（0 篇） |
| docling | 31 / 31 | 460 | 3.28 | 27.6 s | 1.66 | 4631 MB | 2211 / 2925 MB | 0（0 篇） |

说明：检测以 IoU ≥ 0.5 一对一匹配；类型准确率只在已匹配的块上计算；粗粒度把 title/heading、paragraph/abstract/list_item/footnote/author_info 等合并；阅读顺序 τ 是匹配块相对顺序的 Kendall τ（逐页计算后按对数加权）。速度一栏的"启动开销 / 边际秒每页"由耗时对页数做线性拟合得到；每篇文档都是新起的进程，所以"秒/页（中位）"包含模型加载时间。MinerU 前 8 篇首次运行时与 Tauri 编译并行，已单独重跑并取重跑后的耗时。

### Marker（已移除，3 篇数据）

| 文档 | 页数 | 耗时 | 峰值显存 | 峰值内存 |
|---|---|---|---|---|
| d_09b2864c931e924e | 3 | 695 s | 3,134 MB | 3,166 MB |
| d_101c3c79f940b28d | 3 | 60 s | 3,670 MB | 2,754 MB |
| d_e7a7f677a36ad72a | 3 | 57 s | 3,677 MB | 2,773 MB |
| d_33a4283b7a7ed8d7 | 3 | > 16 min（手动停止） | — | — |

慢的原因是：Marker 认为某页文本层不可信（OCR 错误检测或版面覆盖率检查未通过）时，会逐行重新识别文字；这时显存溢出到共享内存，每行要 17–40 秒。版本为 marker-pdf 1.10.2；2.x 需要 Docker vLLM 或 llama-server，未测试。

## 主要发现

**MinerU**

- 原生区分 doc_title、paragraph_title（带层级）、ref_text、page_footnote，页眉页脚和页码会自动丢弃，因此类型准确率最高（84.1%，粗粒度 93.8%）。
- 会把多子图的 figure 按子图拆开，并把子图标号（A、B…）识别为 image_caption，所以 figure F1（0.35）和 caption F1（0.58）偏低。这可以在 Normalizer 中合并"同一图注之上的相邻 figure 块"来改进（M1 跟进），M1-P3b 已实现：figure F1 0.35 → 0.70，caption F1 0.58 → 0.85，见 [docs/m1/normalizer-followups.md](../m1/normalizer-followups.md)。
- 扫描页自动走 OCR，两篇合成扫描件的检测 F1 为 0.98。
- 跨页 / 跨栏续段有 `continues_prev` 标记，Normalizer 会据此合并成带多个 anchor 的单块。
- 对 PDFMathTranslate 生成的中文译本（文字重叠、行距异常），检测 F1 下降到 0.76，但类型判断仍然稳定（94.6%）。

**Docling**

- 整图检测好（figure 0.56），表格结构最好（TableFormer，table F1 1.00），图注识别最准（0.83）。
- 论文题目一律记为 section_header，所以 title F1 为 0；参考文献多数记为 list_item（F1 0.57）；作者单位和通讯作者等页脚信息常被记为正文（footnote 0.26）。这些都可以在 Docling Normalizer 里用位置和关键词规则补救。
- 扫描页上常把两栏合并成一个跨栏块；遇到文本层与渲染错位的 PDF 时，坐标会整体偏移（d_56173974a2a49baf）。
- 公式 LaTeX 增强（`do_formula_enrichment`）开启后，公式召回为 72.7%。

**PyMuPDF 快速模式**

- 只依赖文本层，速度比高质量引擎快两个数量级以上。按"通栏带 → 左栏 → 右栏"排序后，阅读顺序 τ 为 0.92。
- 块是 PDF 内部的文本块，粒度常与视觉段落不一致（检测 precision 0.38），heading 的判断依赖字号和粗体，误报多。
- 扫描页没有文本层，输出为空，产品上需要提示"该文档需要高质量解析"。

## 对后续里程碑的影响

- **M1 解析任务**：默认用 MinerU；先用 PyMuPDF 快速模式出一版 IR 供立即阅读，再在后台用 MinerU 替换（按 §8 的 content_hash / IoU 迁移规则）。
- **常驻解析进程**：MinerU 每次启动加载模型约 40 秒，sidecar 应当保留一个长生命周期的解析 worker（与架构 §5.8 的独立进程池一致），而不是每篇文档新起一个进程。
- **显存**：在 4GB 显卡上峰值约 2.6 GB。与 LLM 本地推理（如 Ollama）同时运行时需要排队，并发数保持为 1。
- **Normalizer 改进清单**：MinerU 的子图合并、子图标号过滤；Docling 的 title / reference / footnote 规则；所有引擎都补上 abstract 和 author_info 的识别。
- **许可证**：MinerU 为 Apache-2.0 加附加条款（MAU 超过 1 亿或月收入超过 2000 万美元需另行取得商业许可；提供在线服务须标明使用了 MinerU）；其模型权重的许可证需要在分发前逐个确认。Docling 为 MIT。PyMuPDF 为 AGPL-3.0（与 FreeRead 的 AGPL-3.0-or-later 兼容）。

## 复现

```bash
# 1. 环境（core 开发环境 + 各引擎独立环境；模型缓存在 .engines/cache/）
uv venv --python 3.12 core/.venv && uv pip install --python core/.venv -e "core[dev,parse-fast]" psutil nvidia-ml-py rapidfuzz
bash scripts/m0_setup_engines.sh            # mineru docling
# 2. 评测集（需先启动 Zotero 7）
core/.venv/Scripts/python scripts/m0_build_eval_set.py
core/.venv/Scripts/python scripts/m0_golden.py sample
# 3. 运行引擎
core/.venv/Scripts/python scripts/m0_run_parsers.py
# 4. golden：共识 → 渲染复核图 → 合并修正
core/.venv/Scripts/python scripts/m0_golden.py consensus
core/.venv/Scripts/python scripts/m0_golden.py render
core/.venv/Scripts/python scripts/m0_golden.py merge
# 5. 指标
core/.venv/Scripts/python scripts/m0_report.py
```
