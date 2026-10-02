# 03 · 锚点模型规范（Anchor Model）· **核心**

> 状态：**冻结**。本文件定义的模型是整个项目的地基：阅读位置恢复、高亮、笔记、翻译对齐、纠错补丁全部建立在它之上。
> 修改本文件必须 bump `schemaVersion` 并提供迁移（见 §8），且需要 ADR。

---

## 1. 目的

把一篇 PDF 变成**可寻址的结构**：给定任意一个句子，能立刻得到它在原始 PDF 上的位置（页 + 矩形 + 行区间）；反之，给定 PDF 上的任意一行，能定位到它在重排视图中的句子。**这是"双模式阅读 + 对照翻译 + 稳定笔记"的充要条件。**

---

## 2. 不变量（Invariants）

实现与测试**必须**保证以下不变量，违反视为 P0 缺陷：

| ID | 不变量 |
|---|---|
| INV-1 | 每个 `Block.id` 在整个 `DocAnchorModel` 内唯一；`Sentence.id` 亦唯一 |
| INV-2 | 每个 `Sentence` 至少含 1 个 `LineRef`；`LineRef.page` 等于其所属 `Sentence.page` |
| INV-3 | 每个 `Paragraph` 至少含 1 个 `Block`；`Block` 可属于 0 个或多个 `Paragraph`（跨段引用场景允许重复） |
| INV-4 | 所有 `Rect` 位于其页面的 `pageSize` 之内（允许 ≤ 2 pt 的浮点溢出容差） |
| INV-5 | `LineRef` 的 `[begin, begin+len)` 必须落在该 `lineId` 文本长度内 |
| INV-6 | **内容无丢失**：除 `type === 'abandon'` 的块外，PDF 文本层中每个非空字符都被至少一个 `Sentence` 覆盖 |
| INV-7 | **顺序单调**：按 `order` 升序遍历时，页面号单调不减（同一页内按 y 再 x 排序） |
| INV-8 | `score ∈ [0,1]`；`score < 0.60` 的块必须在 UI 中可被识别为"低置信"（用于纠错入口） |
| INV-9 | 序列化后的 `blocks.json` 通过 `schemas/doc-anchor-model.schema.json` 校验 |
| INV-10 | 同一 `docId` + 同一引擎版本，重复解析产出**逐字节一致**的 `blocks.json`（确定性要求） |

---

## 3. 坐标系与单位

| 项 | 规定 |
|---|---|
| 单位 | **PDF point**（1 pt = 1/72 inch） |
| 原点 | 页面**左上角**，x 向右、y 向下（与 PDF.js viewport `scale=1` 一致） |
| 旋转 | 依据页面 `/Rotate` 归一化：**输出的 `pageSize` 与 `Rect` 均为"视觉方向"**（用户看到的方向） |
| 页面尺寸来源 | `page.view`（CropBox ∩ MediaBox）经旋转归一化后的 `{w,h}` |
| 缩放 | 模型中**不存缩放**；UI 缩放时按 `scale` 线性变换 |
| 精度 | 保留 3 位小数；序列化时去掉尾部零（保证 INV-10 的字节一致性） |

> 与 Scholaread 的差异：其 `region.json` 用 PDF pt、`sr_5` 布局用 1191×1582 栅格坐标（两套并行）。我们**只保留 pt 一套**，栅格坐标仅在内部模型推理时存在，输出前必须换算。

---

## 4. 标识符

| 对象 | 规则 | 示例 |
|---|---|---|
| Block | `b_{page}_{seq}`，`seq` 从 1 开始，按 `order` 递增 | `b_3_7` |
| Sentence | `s_{blockId}_{seq}`，`seq` 从 1 开始 | `s_b_3_7_2` |
| Paragraph | `pa_{page}_{seq}` | `pa_3_4` |
| Heading（大纲项） | `h_{sha1(title+page)}` 前 16 位 | `h_2961d2c2b8f9fc26` |
| Figure | `fig_{page}_{seq}` | `fig_2_1` |
| 引用条目 | `ref_{seq}`（按出现顺序） | `ref_38` |

`seq` 由构建器按 `order` 指派；**同一输入必须得到同一 ID**（INV-10）。禁止使用随机数、时间戳或 Map 迭代顺序不稳定的来源。

---

## 5. 数据结构

**权威定义**：`schemas/doc-anchor-model.schema.json`（JSON Schema 2020-12），生成的 TS 类型为 `packages/core/src/anchor.generated.ts`。

```ts
export type PageNo = number;                       // 1-based
export interface Rect { x: number; y: number; w: number; h: number }

export type BlockType =
  | 'title' | 'author' | 'abstract' | 'heading' | 'text'
  | 'figure' | 'figure_caption' | 'table' | 'table_caption'
  | 'formula' | 'inline_formula' | 'reference' | 'aside' | 'abandon';

export interface Block {
  id: string; page: PageNo; rect: Rect; type: BlockType;
  score: number;            // 0..1 置信度
  order: number;            // 全文唯一、从 0 递增的阅读顺序
  text?: string;            // 规范化后的文本（NFC、去连字符换行、保留角标占位）
  lines?: LineRef[];        // 该块覆盖的行（构建期写入，便于调试）
}

export interface LineRef { lineId: number; page: PageNo; begin: number; len: number }

export interface Sentence {
  id: string; blockId: string; page: PageNo; text: string;
  lines: LineRef[];
  kind: 'text' | 'formula' | 'caption' | 'title' | 'reference';
}

export interface Paragraph { id: string; blockIds: string[]; sentenceIds: string[] }

export interface OutlineItem { id: string; title: string; page: PageNo; blockId: string; level: number }

export interface FigureRef { id: string; tag: string; page: PageNo; blockId: string; caption?: string }

export interface ReferenceRef { id: string; tag: string; page: PageNo; text: string; doi?: string }

export interface DocAnchorModel {
  schemaVersion: 1;
  docId: string;
  engine: { name: 'docling' | 'marker' | 'grobid' | 'rule'; version: string };
  pageSize: Record<`${number}`, { w: number; h: number }>;   // key = 页号字符串
  blocks: Block[];
  paragraphs: Paragraph[];
  sentences: Sentence[];
  outline: OutlineItem[];
  figures: FigureRef[];
  references: ReferenceRef[];
  stats: { blockCount: number; sentenceCount: number; lowConfidenceBlocks: number; durationMs: number };
}
```

**字段约定**

- `text` 做 Unicode NFC 规范化；软连字符（U+00AD）与行尾连字符换行需还原（`inter-\nnational` → `international`）；
- 上标引用角标在 `text` 中以 `\u0000ref:N\u0000` 占位（N 为 `references` 索引），避免被误并入句子；
- `aside` 用于页边注、基金信息；`abandon` 用于页眉页脚/水印/版权条 —— **只有 `abandon` 允许在重排视图中不显示**。

---

## 6. 构建流水线

```
PDF ──┬─► [6.1] 文本层提取（PDF.js，主进程/worker） ──► LineBox[]
      └─► [6.2] 版面块识别（sidecar: docling/marker；或 rule 引擎） ──► RawBlock[]
                     │
                     ├─► [6.3] 块-行关联 ──► Block ∩ LineRef
                     ├─► [6.4] 阅读顺序 ──► order 全局唯一
                     ├─► [6.5] 句子切分 ──► Sentence[]
                     ├─► [6.6] 大纲 / 图表 / 参考文献
                     └─► [6.7] 校验（INV-1..10）与序列化
```

### 6.1 文本层提取

- 使用 `page.getTextContent({ includeMarkedContent: false, disableNormalization: false })`；
- 每个 `TextItem` 计算：
  - `lineId`：按 `transform[5]`（y）聚类，容差 `max(2pt, 0.5 × 行高)`；同一行内按 `transform[4]`（x）排序并拼接字符串；
  - `fontSize`、`isSuperscript`（`|fontSize − 中位字号| ≥ 1pt` 且基线抬高）；
- 输出 `LineBox { lineId, page, text, rect, fontSize, superscriptRanges }`；
- **哈希稳定性**：`lineId` 为每页从 0 递增的整数，顺序由排序结果决定（必须稳定排序，禁止依赖对象插入顺序）。

### 6.2 版面块识别

| 引擎 | 场景 | 说明 |
|---|---|---|
| `docling` | 默认（数字版 PDF） | 高质量语义块；输出需换算为 pt |
| `marker` | 表格/公式密集的兜底 | 与 docling 结果不得混用（同一文档只用一个引擎） |
| `grobid` | 仅元数据与参考文献 | 不产出正文块 |
| `rule` | **无 sidecar 时的降级** | 文本行聚类 + XY-Cut 递归切分；`score` 固定按启发式给分（见 §9） |

统一要求：引擎输出必须包含 `type`（映射到本规范的 `BlockType`）、`rect`（pt）、`score`。引擎原生不提供 `score` 时（如 docling 的分类分数），**映射规则**：`score = 0.9`（模型输出）/ `0.5`（启发式兜底）。

### 6.3 块-行关联（算法 A1）

```
for each page:
  for each lineBox L:
    candidates = blocks on page whose rect 与 L.rect 相交
    if candidates 为空 → 归属最近块（距离 ≤ 12pt），否则新建 type='text' 块（score=0.5）
    选择 overlapRatio 最大的块 B：
      overlapRatio = area(L.rect ∩ B.rect) / area(L.rect)
    要求 overlapRatio ≥ 0.60，否则视为"越界行" → 记 warning，归入最近块
    将 L 按字符区间切成若干 LineRef 追加到 B.lines
```

约束：**一行只属于一个块**（避免内容重复计入；若确需跨块，按字符区间切分）。

### 6.4 阅读顺序

- 优先采用引擎给出的 `order`（docling 的阅读顺序）；
- 后校验 INV-7（页号单调 + 页内 y/x 排序）；违反时**以几何排序覆盖**引擎顺序并记 `warn: order.overridden`；
- 双栏检测：若同页存在两个 x 区间重叠度 < 10% 的列簇，则按"列优先、列内 y 递增"。

### 6.5 句子切分（算法 A2）

```
输入：Block.text（已规范化）+ 保护区间（公式块、上标占位、DOI、URL、小数、缩写）
1. 若 block.type ∈ {formula, inline_formula} → 整块 1 个 Sentence（kind='formula'），不做切分
2. 若 block.type ∈ {figure_caption, table_caption} → 按 ; / 。 / . 切分，最多 3 句（caption 通常很短）
3. 其余：用 Intl.Segmenter(locale, { granularity: 'sentence' }) 初切
4. 后处理合并规则（必须实现）：
   a. 合并"过短片段"：长度 < 25 字符且上一句未以终止符结尾
   b. 保护缩写：Mr. / Dr. / Fig. / Eq. / Tab. / et al. / vs. / e.g. / i.e. / cf. / Approx. / Sec.
   c. 保护引用：形如 [12]、[12,15]、(Smith et al., 2020) 不触发切分
   d. 保护数字：3.14、1,000.5、10.1109/TIT.2020.1234567（DOI）
   e. 保护首字母缩写：J. K. Rowling、U.S.A.
5. 输出 Sentence，按出现顺序指派 seq
```

**句子与行的绑定**：切分在"字符流"上进行，字符流由 `Block` 内 `LineRef` 顺序拼接而成；每个句子记录其覆盖的字符区间，再按行边界反算成 `LineRef[]`。**禁止**用 DOM 或渲染后文本反推。

### 6.6 大纲 / 图表 / 参考文献

| 产出 | 规则 |
|---|---|
| `outline` | 取 `type ∈ {title, heading}` 的块；`level` 由字号（相对正文中位字号）与编号模式（`1.` / `1.1` / `I.`）推定，`−1` 表示文档标题 |
| `figures` | `type ∈ {figure}` 且存在相邻 `figure_caption`（同页、垂直距离 ≤ 24pt 或紧随其后）；`tag` 取图注首部的 `Fig. N` / `Figure N` / `图 N`，缺失时用 `fig_{page}_{seq}` |
| `references` | 优先用 `grobid` 解析结果；否则从 `type === 'reference'` 的块中按行首编号切分；`doi` 用正则 `10\.\d{4,9}/[-._;()/:A-Z0-9]+` 提取 |

### 6.7 校验与序列化

- 校验 INV-1..10；任一不变量失败 → 抛出 `AppError('FR-ANCHOR-00x')`，**不得写入半成品**；
- 序列化：`JSON.stringify(model, replacer)`，其中 replacer 负责数值 3 位小数截断与 `undefined` 剔除；
- 落盘：`library/<citekey>/blocks.json`（见 `05-storage.md`）。

---

## 7. 质量指标（Gate 依据）

| 指标 | 定义 | 阈值 |
|---|---|---|
| **块结构 F1** | 与黄金集标注按"同页 + IoU ≥ 0.5 + 类型一致"匹配后的 F1 | ≥ 0.90 |
| **句子↔行 IoU** | 对每个句子，其预测行字符集合 `P` 与真值行字符集合 `G`（元素为 `(page,lineId,charIndex)`），`IoU = |P∩G| / |P∪G|`；取所有句子的平均 | ≥ 0.98 |
| **内容覆盖率** | 非 `abandon` 块覆盖的文本字符数 / PDF 文本层总字符数 | = 100% |
| **阅读顺序正确率** | `order` 与真值顺序的 Kendall τ | ≥ 0.95 |
| **公式保护率** | 黄金集中公式块未被错误切分或改写文本的比例 | ≥ 99% |
| **确定性** | 同输入两次解析的 `blocks.json` 字节级相同 | 100% |

评测实现：`packages/core/src/eval/anchor-metrics.ts` + CLI `pnpm eval:anchor --set fixtures/golden`。

---

## 8. 序列化与版本

```jsonc
// blocks.json 头部（供人快速识别）
{ "schemaVersion": 1, "docId": "…", "engine": { "name": "docling", "version": "2.x.y" }, … }
```

**版本规则**

| 变更类型 | 处理 |
|---|---|
| 新增可选字段 | `schemaVersion` **不 bump**，但需在变更记录登记 |
| 字段语义变更 / 删除字段 / 类型改变 | **必须 bump**，并实现 `migrateAnchorModel(v1→v2)` |
| 引擎升级导致结构变化 | 不 bump（结构不变），但 `engine.version` 变化 → **触发重解析**（缓存键含引擎版本） |

**缓存键**：`sha256(docId + engine.name + engine.version + schemaVersion + PARSER_RULES_REVISION)`。
`PARSER_RULES_REVISION` 是构建期注入的常量，任何切分/关联规则改动必须 +1（否则缓存命中旧结果）。

---

## 9. 边界情况与降级

| 情况 | 处理 |
|---|---|
| 扫描件（无文本层或文本层 < 20 字符/页） | 走 OCR 通道（`04-parser-sidecar.md` §OCR）；`text` 来自 OCR，`lines` 仍由 OCR 行框合成；`meta.quality = 'ocr'` |
| 无 sidecar / sidecar 启动失败 | 使用 `rule` 引擎；UI 顶部显示"快速模式"横幅（i18n `reader.banner.quickMode`），块 `score` 由启发式给出（同一行数 → 0.5；聚类清晰 → 0.65） |
| 竖排中文 | 行聚类改为按 x 聚类；`LineRef` 顺序按 x 递减；标记 `meta.writingMode='vertical-rl'`（V1 允许布局质量下降，但不得崩溃） |
| 跨页表格/图 | 以"主块 + 续块"表示，续块 `type` 相同，`id` 独立；`figures[].blockId` 指向主块 |
| 数学公式 | 整块为一个 `Sentence(kind='formula')`；文本内联公式用 `inline_formula` 块并从正文句子中**挖空**，以 `\u0000fml:{blockId}\u0000` 占位 |
| 极端页数（> 500 页） | 分页解析（每 50 页一批），最终合并；进度按批上报 |
| 加密/损坏 PDF | 抛 `FR-PARSE-001`，UI 提示不支持，不进入解析队列 |

---

## 10. 测试要求

**必须存在的单测（`packages/core/src/anchor/*.test.ts`）**

| # | 用例 | 断言 |
|---|---|---|
| T1 | 双栏正文 3 行 | 两列各成块，`order` 列优先，INV-7 成立 |
| T2 | `Fig. 1` 缩写 | 不在此处切句 |
| T3 | `[12,15]` 引用 | 不切句，且生成 `references` 占位 |
| T4 | `10.1109/TIT.2020.1234567` | 不切句，DOI 正确提取 |
| T5 | 行尾连字符换行 | `text` 中连字符被还原，`LineRef` 仍跨两行 |
| T6 | 公式块 | 单 `Sentence(kind='formula')`，正文中以占位符引用 |
| T7 | 页眉页脚 | 标为 `abandon`，不计入内容覆盖率 |
| T8 | 扫描件（fixtures/scan-01） | 走 OCR 分支，`meta.quality='ocr'` |
| T9 | 确定性 | 同输入两次构建，序列化字节相同 |
| T10 | 越界块（Rect 超出页面） | 触发 `FR-ANCHOR-004` |

**黄金集**：`fixtures/golden/`（50 篇，见 `10-testing.md` §黄金集），每篇含 `expected/blocks.json` 与 20 条句子映射真值。

---

## 11. 性能预算

| 场景 | 预算 |
|---|---|
| 单页锚点构建（不含模型推理） | ≤ 8 ms |
| 100 页文档纯 JS 构建（rule 引擎） | ≤ 2.5 s |
| 内存增量 | ≤ 40 MB / 100 页 |

---

## 变更记录

| 版本 | 日期 | 变更 | schemaVersion |
|---|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结（含 INV-1..10、A1/A2 算法、指标定义） | 1 |
