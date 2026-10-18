# Document IR 规范

- schema_version：`0.1.0`（**定稿**，M0）
- 更新日期：2026-10-17
- JSON Schema：[schemas/ir-0.1.0.json](schemas/ir-0.1.0.json)（由 `models.py` 导出）
- 参考实现：`core/freeread/infra/parsers/`（PyMuPDF / MinerU / Docling / Marker 四个 Normalizer，公共部分见 `normalize_common.py`）
- 决策依据：[ADR-0004](adr/0004-document-ir-as-core.md)
- 机器可读定义：`core/freeread/domain/ir/models.py`（Pydantic，可导出 JSON Schema）

## 1. 目标

Document IR（Intermediate Representation，统一文档模型）是一篇论文解析后的结构化表示，供以下功能共同使用：

- 重排渲染（Reader）
- 原版 PDF ⇄ 重排双向定位
- 块级翻译、总结引用、问答引用、知识图谱溯源

## 2. 顶层结构

```jsonc
{
  "schema_version": "0.1.0",
  "doc_id": "d_3f9a…",               // = "d_" + PDF 文件 sha256 前 16 位
  "source": {
    "pdf_sha256": "3f9a…",           // 完整哈希
    "page_count": 14,
    "pages": [{ "index": 0, "width": 612.0, "height": 792.0 }]   // 单位：PDF 点(pt)
  },
  "meta": {
    "title": "…",
    "authors": [{ "name": "…", "affiliation": "…" }],
    "year": 2024,
    "doi": "10.xxxx/…",
    "venue": "…",
    "language": "en",
    "zotero_key": "ABCD1234"          // 可空
  },
  "parser": {
    "engine": "mineru",
    "engine_version": "x.y.z",
    "normalizer_version": "0.1.0",
    "created_at": "2026-10-17T12:00:00Z",
    "pages_parsed": null               // 只解析了部分页时为页码列表（按页重解析、评测抽样）
  },
  "sections": [ /* 章节树，见 §4 */ ],
  "blocks": [ /* 按阅读顺序排列的块，见 §3 */ ],
  "references": [ /* 参考文献，见 §5 */ ],
  "assets": [ /* 图片等资源，见 §6 */ ]
}
```

## 3. Block

```jsonc
{
  "id": "b_0012",                    // 文档内唯一，按阅读顺序编号，四位起
  "type": "paragraph",
  "section_id": "s_3_2",             // 所属章节，可空（如标题页信息）
  "order": 12,                       // 阅读顺序，从 0 开始
  "level": null,                     // heading：1–4；list_item：嵌套层级；其余为 null
  "text": "We propose … as shown in ⟦EQ1⟧ [12].",  // 纯文本（行内公式用占位符）
  "inlines": [                       // 行内特殊元素，与 text 中的占位符对应
    { "key": "EQ1", "kind": "math", "latex": "\\alpha + \\beta" },
    { "key": null, "kind": "cite", "ref_ids": ["r_12"], "span": [44, 48] }
  ],
  "latex": null,                     // type=equation 时为显示公式 LaTeX
  "html": null,                      // type=table 时为净化后的表格 HTML
  "asset_id": null,                  // type=figure/table 时可指向截图资源
  "caption_of": null,                // type=caption 时，指向所说明的 figure/table 块
  "label": null,                     // 如 "Figure 3"、"Table 2"、"(5)"
  "anchors": [                       // 在原 PDF 中的位置；跨页块有多个
    { "page": 4, "bbox": [72.0, 340.5, 540.0, 420.2] }
  ],
  "content_hash": "sha256:…",        // 规范化 text/latex/html 的哈希，用于重解析后迁移
  "confidence": 0.93,                // 解析置信度，可空
  "flags": []                        // 见 §3.5
}
```

### 3.1 块类型

| type | 说明 | 主要字段 | 翻译 |
|---|---|---|---|
| `title` | 论文标题 | text | 是 |
| `author_info` | 作者、单位 | text | 否 |
| `abstract` | 摘要 | text, inlines | 是 |
| `heading` | 章节标题，`level` 字段 1–4 | text, level | 是 |
| `paragraph` | 正文段落 | text, inlines | 是 |
| `list_item` | 列表项，`level` 字段表示嵌套 | text, inlines | 是 |
| `equation` | 独立显示公式 | latex, label | 否 |
| `figure` | 图 | asset_id, label | 否 |
| `table` | 表格 | html, asset_id, label | 可选 |
| `caption` | 图 / 表注 | text, caption_of | 是 |
| `code` | 代码 / 算法块 | text | 否 |
| `footnote` | 脚注 | text | 是 |
| `reference_entry` | 参考文献条目原文 | text | 否 |
| `other` | 无法归类（页眉页脚默认丢弃，不进入 IR） | text | 否 |

### 3.2 坐标约定

- 单位为 PDF 点（pt），原点在页面**左上角**，y 轴向下；`bbox = [x0, y0, x1, y1]`。
- 页码 `page` 从 0 开始。
- Normalizer 负责把各引擎的坐标（像素、左下原点等）统一转换到此约定。

### 3.3 ID 规则

- `doc_id`：`d_` + PDF sha256 前 16 位十六进制。
- `block.id`：`b_` + 四位以上的阅读顺序号，如 `b_0012`。**同一次解析内稳定**；重新解析后通过 `content_hash` 迁移（§8）。
- `section.id`：`s_` + 章节编号路径（取自标题文本开头的 `3.2` 之类编号），如 `s_3_2`；无编号或编号重复的章节用顺序号 `s_u7`。章节层级取 heading 的 `level`。
- 全局引用一个块时使用 `doc_id#block_id`，如 `d_3f9a…#b_0012`。

### 3.4 行内元素

`inlines.kind` 取值：`math`（行内公式）、`cite`（文献引用）、`xref`（指向图 / 表 / 公式 / 章节的内部引用，带 `target_block_id`）、`url`、`code`。

- `math` 必须在 `text` 中以 `⟦KEY⟧` 占位，翻译时保持占位符不变。
- `cite`、`xref`、`url` 可以用 `span`（字符区间，左闭右开）标注在 `text` 中的位置，也可以用占位符；翻译前统一转换为占位符。

### 3.5 flags 取值

| flag | 含义 |
|---|---|
| `ocr` | 文本来自 OCR（扫描页或文本层不可用） |
| `fast_mode` | 由 PyMuPDF 快速模式产生（无公式 / 表格识别） |
| `no_latex` | 引擎识别出公式区域但没有给出 LaTeX |
| `ir_warning` | 该块未通过 §7 的某条规则检查（详情见解析日志） |
| `low_confidence` | 解析置信度低于阈值 |
| `user_edited` | 用户手动修改过 |

### 3.6 Normalizer 约定（M0 实践确定）

- **页眉、页脚、页码**一律丢弃，不进入 IR。
- **跨栏 / 跨页续段**合并为一个块，`anchors` 按顺序列出每一段的位置；块的 `section_id` 取第一段所在章节。
- **图内文字**（坐标轴标签、子图标号等）不单独成块。
- **表格 HTML** 中的行内公式统一写作 `<math>LaTeX</math>`；单元格内的其他标签只保留 `table/tr/td/th`（含 `rowspan`/`colspan`）、`math`、`sup`、`sub`、`b`、`i`。
- **图 / 表** 一律登记一个 `Asset`（`path` 为 `assets/<asset_id>.png`，由解析任务按 bbox 截图生成），因此 `figure` 总有 `asset_id`，`table` 在没有 HTML 时也能显示截图。
- **参考文献**：引擎直接给出的 reference 块，或"References / Bibliography / 参考文献"标题之后的段落与列表项，都视为 `reference_entry`；条目以编号开头时 `Reference.id` 为 `r_<编号>`，否则为 `r_x<序号>`。
- **多面板图**：同一图注之上、相互紧邻的子图合并为一个 `figure`（bbox 取并集）；子图标号（a、(b)…）不成块。
- **前置内容**：首页题目之后的作者 / 单位 / 邮箱行记为 `author_info`，摘要段落记为 `abstract`；规则见 `normalize_common.mark_front_matter` 与 docs/m1/normalizer-followups.md。
- **图注配对**：`caption_of` 指向同页、距离最近、且与图注标签（Figure / Table / 图 / 表）类型一致的 figure / table。
- `meta.language` 在 Zotero 元数据缺失时按正文 CJK 字符占比推断（> 20% 记为 `zh`）。

## 4. Section

```jsonc
{ "id": "s_3_2", "title": "3.2 Training Objective", "level": 2,
  "parent_id": "s_3", "heading_block_id": "b_0040",
  "block_range": ["b_0040", "b_0057"] }
```

`sections` 是扁平数组，通过 `parent_id` 组成树。

## 5. Reference

```jsonc
{ "id": "r_12", "raw_block_id": "b_0301",
  "title": "…", "authors": ["…"], "year": 2021, "venue": "…",
  "doi": "…", "arxiv_id": "…",
  "linked_doc_id": null }            // 若该文献也在本地库中，指向其 doc_id
```

`linked_doc_id` 用于构建文献间的引用图，供跨文献问答使用。

## 6. Asset

```jsonc
{ "id": "a_0005", "kind": "image", "path": "assets/a_0005.png",
  "page": 5, "bbox": [ … ], "width_px": 1200, "height_px": 800 }
```

`path` 相对于 `documents/<doc_id>/` 目录。

## 7. 校验规则

除 JSON Schema 外，Validator 还检查：

1. `blocks` 中 `id` 唯一，`order` 连续且与数组顺序一致。
2. 所有 `section_id`、`caption_of`、`asset_id`、`ref_ids`、`target_block_id` 引用都存在。
3. `text` 中的每个 `⟦KEY⟧` 在 `inlines` 中都有对应项，反之亦然。
4. `anchors[].page` 在页数范围内，bbox 落在页面尺寸内（允许 1pt 误差）。
5. `equation` 必须有 `latex`；`table` 必须有 `html` 或 `asset_id`；`figure` 必须有 `asset_id`。

校验失败的项记录为警告并写入 `flags`，不阻断入库（除结构性错误外）。

## 8. 重新解析与迁移

重新解析（更换引擎、Normalizer 升级、按页重解析）会生成新的 block 列表。迁移步骤：

1. 按 `content_hash` 精确匹配新旧块。
2. 未匹配的块，按同页 bbox 重叠率（IoU ≥ 0.5）+ 文本相似度做模糊匹配。
3. 生成 `old_block_id → new_block_id` 映射，更新 translations、summaries 引用、qa 引用、kg 关系的 `source_block_id`。
4. 无法映射的引用标记为 `stale`，在 UI 中提示用户重新生成。

## 9. 版本策略

- `schema_version` 遵循语义化版本。
  - 补丁版本：文档说明修订，结构不变。
  - 次版本：新增可选字段或块类型，旧数据仍有效。
  - 主版本：字段删除或语义变化，需要迁移脚本。
- 读取时若主版本不一致，从 `raw/` 中的引擎原始输出重新运行 Normalizer。

## 10. 示例（片段）

```json
{
  "schema_version": "0.1.0",
  "doc_id": "d_3f9a1c2b7e4d5a60",
  "blocks": [
    { "id": "b_0000", "type": "title", "order": 0, "section_id": null,
      "text": "Attention Is All You Need",
      "anchors": [{ "page": 0, "bbox": [150.2, 98.0, 462.1, 118.5] }],
      "content_hash": "sha256:…", "inlines": [], "flags": [] },
    { "id": "b_0031", "type": "equation", "order": 31, "section_id": "s_3_2",
      "text": "", "latex": "\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V",
      "label": "(1)",
      "anchors": [{ "page": 3, "bbox": [180.0, 402.0, 430.0, 430.0] }],
      "content_hash": "sha256:…", "inlines": [], "flags": [] }
  ]
}
```
