# M1-P3b：Normalizer 跟进项与评测回归

ADR-0003 在 M0 评测后列出了三项 Normalizer 跟进（"跟进（M1）"）。本文记录实现方式，以及在 M0 golden 评测集（31 篇、93 个抽样页，见 [docs/m0/parser-eval.md](../m0/parser-eval.md)）上的前后对比。

只改了 Normalizer，没有重跑任何引擎：新数字来自对 M0 已有 raw 输出（`eval-out/<engine>/<doc_id>/raw/`）的重新规范化。

## 改了什么

### 1. 所有 Normalizer：abstract 与 author_info

规则在 `normalize_common.mark_front_matter`，由 `build_document` 调用，所以 PyMuPDF、MinerU、Docling（以及 Marker）都会用到。只作用于前两页，只改 paragraph / other 类块，另外处理被 PyMuPDF 误判为 heading 的作者行。

| 规则 | 结果 |
|---|---|
| 段落以 "Abstract" / "摘要" 开头（`Abstract.`、`ABSTRACT The…`、`Abstract \| …`、`摘要：…`） | abstract；紧随其后、以小写字母开头的同页段落视为分栏续段 |
| "Abstract" / "Summary" / "摘要" 标题之后、下一个标题之前的段落（最多 4 段，跳过窄侧栏） | abstract |
| 标题（title）之后第一个像人名列表的块（拉丁词多数含大写字母，带逗号 / and / & 等分隔符；中文为不含句号的短行） | author_info |
| 作者行之后连续的单位行（University、Institute、Department…、大学、研究所…）或邮箱 / 通讯作者行 | author_info |
| 作者区内的日期、DOI、"Open access"、"Check for updates"、版权行 | 跳过，不终止作者区 |
| 关键词、"Edited by"、"Citation"、"Graphical Abstract"、正文标题、页面下 40% | 作者区结束 |
| "Authors" 标题之后第一个像人名列表的段落（Cell 侧栏） | author_info |
| 作者区之后、同页正文标题之前第一个长段落（≥ 400 字符或 ≥ 150 个汉字），且宽度 ≥ 0.45 页宽或紧跟关键词行 | abstract |

规则偏保守：没有 title 时不猜作者区；title 后第一块不像人名时（例如 Nature 式加粗首段）既不标作者，也不按位置标摘要。

PyMuPDF 另有一处配套修改：题目折行时 PyMuPDF 会拆成两个同字号的块，第二块会被当成作者行，现在并回 title（`pymupdf_fast.normalize_extract`）。

### 2. MinerU：合并同一图注之上的子图，过滤子图标号

`mineru.merge_subfigures`：

- "a"、"(b)"、"C." 这类单字母块一律丢弃。MinerU 把它们识别为 image_caption；被识别成正文的，只在紧挨着图时丢弃。
- 同页 figure 之间间距 ≤ 20 pt 的连成一组，经子图标号连通也算。组下方 40 pt 内若有 "Figure N / Fig. N / 图 N" 图注，水平方向与组重叠，且组的并集内没有压到正文块，就合并为一个 figure：bbox 取并集，阅读顺序上放在图注之前。
- 合并后的 figure 不再沿用引擎导出的单个子图图片（`image_path` 置空）。整图资源照常由解析任务按 bbox 截图生成（docs/02-document-ir.md §3.6）。

20 pt 的阈值来自评测集：同一张图的子图间距都在 17 pt 以内；左右并排的两张独立图（各有图注，如 d_27e305b3be5ac1bf 第 1 页）相距 23 pt。

### 3. Docling：title、reference_entry、footnote

都在 `docling.py` 中，在 `build_document` 之前执行：

- **title**（`mark_title`）：首页没有 title 时，在首页上 45% 的 heading 中，排除栏目名（少于 3 个词，如 "Article"）、以冒号结尾的侧栏小标题、带编号的标题和常见章节名，取框最高的那个作为 title。Docling 几乎总把论文题目标成 section_header。
- **footnote**（`mark_footnotes`）：
  - 任意页：含年份的 Received / Accepted / Published 日期行、收稿日期等中文日期行、通讯作者行、"Full article and list of author affiliations"。
  - 仅首页：Copyright / © / doi、Author contributions、利益声明、"This article contains…"、Present address 等刊物小字；页面下 60% 内以角标开头的单位行；页面下 20% 内的单位行。
- **reference_entry**（`mark_reference_runs`）：没有 "References" 标题的版式（如 Nature）下，连续 ≥ 3 条像文献条目的列表项改为 reference_entry。"像文献条目"指以 "Surname, A." / "Surname AB" 开头，且含年份或页码范围。Docling 把编号放在 `marker` 字段里，正文里没有编号，现在把编号补回参考文献条目的开头，使 `Reference.id` 能取到 `r_<编号>`。

### 版本

`NORMALIZER_VERSION` 与 PyMuPDF / MinerU / Docling / Marker 各 Normalizer 的 `version` 均从 0.1.0 升到 0.2.0。解析任务（`services/parse.py`）发现 `normalizer_version` 不一致时，会用已有 raw 重新规范化，不重跑引擎。

## 结果

由 `scripts/m1_normalizer_compare.py` 生成。"之前"是 M0 报告所用的 IR，与 M1-P3 分支（PR #4）上用旧 Normalizer 重新规范化的结果逐项一致；"之后"是本分支对同一批 raw 重新规范化的结果。

### 总体

| 引擎 | 指标 | 之前 | 之后 |
|---|---|---|---|
| pymupdf | 检测 F1 | 0.4723 | 0.4751 |
| pymupdf | 类型准确率 | 65.8% | **70.6%** |
| pymupdf | 粗粒度类型准确率 | 77.7% | 78.3% |
| pymupdf | 阅读顺序 τ | 0.9230 | 0.9233 |
| pymupdf | 文本 NED↓ | 0.0379 | 0.0378 |
| pymupdf | τ（同匹配块） | 0.9228 | 0.9228 |
| pymupdf | 文本 NED↓（含 author_info） | 0.0368 | 0.0366 |
| mineru | 检测 F1 | 0.8810 | **0.9380** |
| mineru | 类型准确率 | 84.1% | **89.2%** |
| mineru | 粗粒度类型准确率 | 93.8% | 93.9% |
| mineru | 阅读顺序 τ | 0.9811 | 0.9809（见下） |
| mineru | 文本 NED↓ | 0.0641 | 0.0642（见下） |
| mineru | 公式召回 | 90.9% | 90.9% |
| mineru | 公式 LaTeX NED↓ | 0.3585 | 0.3585 |
| mineru | τ（同匹配块） | 0.9811 | 0.9811 |
| mineru | 文本 NED↓（含 author_info） | 0.0617 | 0.0617 |
| docling | 检测 F1 | 0.8781 | 0.8781 |
| docling | 类型准确率 | 70.4% | **93.0%** |
| docling | 粗粒度类型准确率 | 83.4% | **94.5%** |
| docling | 阅读顺序 τ | 0.9595 | 0.9595 |
| docling | 文本 NED↓ | 0.0746 | 0.0704 |
| docling | 公式召回 | 72.7% | 72.7% |
| docling | 公式 LaTeX NED↓ | 0.0527 | 0.0527 |
| docling | τ（同匹配块） | 0.9595 | 0.9595 |
| docling | 文本 NED↓（含 author_info） | 0.0731 | 0.0691 |

PyMuPDF 没有公式识别，公式两项均为 0 / –，未列出。

### 各类型 F1

| 类型 | pymupdf | mineru | docling |
|---|---|---|---|
| abstract | 0.00 → 0.65 | 0.00 → 0.93 | 0.00 → 0.85 |
| author_info | 0.00 → 0.68 | 0.00 → 0.87 | 0.00 → 0.82 |
| caption | 0.60 → 0.60 | 0.58 → 0.85 | 0.83 → 0.86 |
| figure | 0.00 → 0.00 | 0.35 → 0.70 | 0.56 → 0.56 |
| footnote | 0.00 → 0.00 | 0.67 → 0.67 | 0.26 → 0.75 |
| heading | 0.22 → 0.22 | 0.91 → 0.91 | 0.70 → 0.77 |
| list_item | 0.00 → 0.00 | 0.00 → 0.00 | 0.15 → 0.56 |
| paragraph | 0.37 → 0.37 | 0.81 → 0.85 | 0.75 → 0.85 |
| reference_entry | 0.13 → 0.13 | 0.99 → 0.99 | 0.57 → 0.995 |
| title | 0.68 → 0.81 | 0.97 → 0.97 | 0.00 → 0.98 |
| equation / table / other | 不变 | 不变 | 不变 |

Docling 的类型准确率已高于 MinerU（93.0% 对 89.2%）。不过 Docling 的检测 F1、公式召回不变，M0 "默认用 MinerU"的结论不受影响。

### 关于 MinerU 的两处微小变差

按 4 位小数，MinerU 有两项总体数字略差：阅读顺序 τ 0.9811 → 0.9809，文本 NED 0.0641 → 0.0642。按 M0 报告的精度（3 位）两项都不变。按类别看，双栏、表格多、长附录的 τ 降了 0.0003–0.0022，扫描版的文本 NED 升了 0.0009。这些都是参与计算的块变了，不是同样的块变差了：

- **τ**：子图合并后，golden 中 59 张 figure 的匹配数从 40 升到 53；新匹配上的 13 张进入了 τ 的计算。其中少数在 golden 中的阅读顺序与 MinerU 不同，例如 d_2d8e7b5188a46ca6 第 1 页，golden 把右栏图注续段排在整图之前。只在新旧两版都匹配上的块上计算（"τ（同匹配块）"），τ 为 0.9811 → 0.9811，没有变化。
- **文本 NED**：`metrics.TEXTUAL` 不含 author_info。作者行原先被标成 paragraph，计入了文本 NED；现在标成 author_info，就不计入了。Normalizer 没有改任何块的文本。把粗粒度为文本类的匹配块都算上（"文本 NED（含 author_info）"），为 0.0617 → 0.0617。

如果要求"所有原始数字一律不得变差"，这两项不满足。把阈值放宽到不再合并这些图，或把作者行留作 paragraph，可以让数字不变，但那正是本次要修的问题，所以没有这样做。

## 已知误判与局限

- d_09b2864c931e924e（Nature Reviews）的 "Abstract | …" 段落被标成 abstract，golden 标的是 paragraph。按 GUIDELINES，这一条更可能是 golden 标注不一致。
- d_27e305b3be5ac1bf（老版 Nature letter，题目在页面中部）作者行下方的两行单位被标成 author_info，golden 按 GUIDELINES 第 4 条记为 footnote。
- PyMuPDF 的 abstract / author_info F1 只有 0.65 / 0.68，原因多在 PyMuPDF 本身：块边界与 golden 对不上，或者 title 识别错了，作者区规则以 title 为起点。
- Docling 的作者区：d_45a0a08492648684 中 Docling 把 "Check for updates" 与作者行合成了一块，规则跳过了它。
- MinerU 的 figure F1 仍只有 0.70。没有图注的多块图（如 Cell 的 Graphical Abstract）不合并；上下两张独立的图贴得很近（< 20 pt）且共用下方图注时会被合成一张，例如 d_cf3224806f31b924 第 6 页，golden 为两张。59 张 golden figure 中仍有 6 张没匹配上。
- 收稿日期、版权行等刊物小字在 PyMuPDF / MinerU 中仍是 paragraph（golden 为 footnote）。footnote 规则目前只加在 Docling 上（ADR-0003 的范围）；`docling.mark_footnotes` 可以直接搬到公共层，留作后续。

## 未验证

- **Marker**：Normalizer 版本一并升到 0.2.0（公共规则对它同样生效），但 Marker 已不在评测集中，没有回归数字。
- **真实文献库上的重新规范化**：只有 `tests/test_parse.py` 的单测覆盖了"版本变化 → 只重新规范化"这条路径，没有在真实数据目录上跑过。
- **合并后整图的截图**：figure 的 bbox 已是并集。按 IR 约定，截图由解析任务按 bbox 生成；本次没有检查生成的 PNG。

## 复现

```bash
# 前提：eval-out/ 中已有 M0 的 raw 输出（scripts/m0_run_parsers.py），golden 已合并（scripts/m0_golden.py merge）
cp -r eval-out eval-out-m0                                  # 保存旧 IR
core/.venv/Scripts/python scripts/m0_run_parsers.py --renormalize   # 用新 Normalizer 重新生成 IR
core/.venv/Scripts/python scripts/m1_normalizer_compare.py --before eval-out-m0 --after eval-out
```
