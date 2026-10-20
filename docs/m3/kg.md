# M3-1：知识图谱抽取、实体消歧、关系出处

- 日期：2026-10-21（DeepSeek 评测后修订）
- 关联：[路线图 M3](../04-roadmap.md)、[架构 §5.7A](../01-architecture.md)、[数据模型 §6](../03-data-model.md)、[ADR-0002](../adr/0002-local-first-sqlite.md)

## 结论速览

| 项目 | 结果 |
|---|---|
| 抽取 | 后台任务 `kg_extract`：按章节组（约 2500 token）逐组调用模型，一篇内并发 2；实体 7 类、关系 8 类（固定 schema） |
| 出处 | 每条关系必须带本组的出处块；摘句不在原文里就清空并降 confidence；`achieves` 的数值必须在出处块里出现，否则丢弃整条 |
| 消歧 | 只有别名归一化后精确相同才自动合并；嵌入找到的同类候选经模型（`kg_resolve`）判定为同一个的，作为"可能重复"等用户确认或否决；名称里数字不同的不送判定；Claim 不跨文档合并 |
| 用户编辑 | 改名 / 改类型、合并、拆分（按写法）、删除关系；重新抽取不推翻这些操作 |
| 重新解析 | 提及和关系的出处块按块映射迁移；映射不上的关系标"出处已失效" |
| 触发 | 阅读器"图谱"面板手动抽取；设置里"建立语义索引后自动抽取图谱"（默认关） |
| 模型路由 | `kg_extract` 未单独配置时沿用总结的服务（再回退到翻译）；首次发送前需要确认 |
| 界面 | 阅读器侧栏"图谱"：可能重复（合并 / 不是）、数值结果、按类型分组的实体、关系与出处跳转、改名 / 合并 / 拆分 / 删除关系 |

## 设计

### 数据（迁移 `0008_kg`）

- `kg_entities`：全库共享。`origin=user` 表示用户改过；向量（float32 小端）和产生它的嵌入模型存在行里，消歧时只和同一模型的向量比较。
- `kg_entity_aliases`：含规范名，`alias_norm` 精确命中即同一实体。
- `kg_mentions`：实体在哪篇、哪个块里出现，记原文写法（拆分按写法分）。
- `kg_relations`：出处 `(doc_id, source_block_id)` 必填；`src_surface` / `dst_surface` 是原文写法；`status` 为 `ok` / `stale` / `rejected`。
- `kg_distinct`：用户拆开的实体对，以及否决过的合并建议。
- `kg_merge_suggestions`（迁移 `0009`）：可能重复的实体对（本篇实体 → 已有实体、相似度、产生它的文档）。确认后并入、否决后写 `kg_distinct`，两种情况都删除这一行。

向量没有放进 vec0：维度随嵌入模型变，实体数在万级，按类型取出来用 numpy 暴力算就够。

### 名称归一化（`domain/kg/normalize.py`）

NFKC、casefold，希腊字母写成拉丁名，去掉空白、连字符、下划线和撇号，去掉首尾标点和英文所有格。点保留（`GPT-3.5` ≠ `GPT-35`），不做词干化（`Transformer` 与 `Transformers` 库可能不是一个东西）。`全称 (缩写)` 拆成两个别名。

### 抽取与校验（`domain/kg/extract.py`、`services/kg.py`）

- 分组复用总结的 `group_blocks`，输入复用 `source_blocks`（页眉页脚等不发送）。标题块只作小标题，不能被引用。
- 每组回复解析失败时不走缓存重试一次；单组失败不影响其他组，全部失败时任务失败，错误信息带第一个失败原因。
- 服务商返回 401 / 402 / 403（密钥无效、余额不足、无权限）时不再调用剩下的组，整个任务失败并显示服务商的说明（如 `HTTP 402: Insufficient Balance`），不写入部分结果。
- 实体的提及：模型给出的块，加上别名在本组块里实际出现的位置（拉丁文字按词边界，`BERT` 不命中 `RoBERTa`）。既没有提及也没有关系的实体丢弃。
- 数值核对按数值比较：`85.30` = `85.3`，`1,234` = `1234`；名称里的数字（`ResNet-50` 的 50、`F1` 的 1）不算，紧挨中文的数字（"为66.5h"、"增加41倍"）算。模型把 85.3% 换算成 0.853 会被丢弃，提示词要求原样抄写。显示用模型给的原写法（`<50`、`0.07 ± 0.05`），核对用其中第一个数。
- 摘句核对忽略大小写、所有空白（PDF 换行会在中文里插空格、在英文里吞空格）和连字符写法；用省略号截断的摘句各段按顺序都找得到也算。
- 同一篇内，同类型且任一别名归一化相同的实体合并；关系按 (src, dst, type, block) 去重。
- 写入在一个事务里：删除该文档的提及和非 rejected 的关系，再写入新的；之后回收没有提及也没有关系的自动实体。

### 消歧（`domain/kg/resolve.py`）

1. 别名精确命中（同类型）：直接用已有实体。
2. 其余实体嵌入 `"类型: 名称 — 描述"`，在同类型、同一嵌入模型的实体里取余弦最高的 3 个，第一个满足"≥ 0.86 且名称里的数字一致（或一边没有数字）"的作为候选。
3. 候选对每 40 对一次调用 `kg_resolve@2`，模型要在 same / narrower / broader / related / different 里选一种。**选 same 的也不自动合并**，只写成合并建议，等用户在图谱面板里确认或否决；调用或解析失败不产生建议。否决过的实体对（`kg_distinct`）不再建议。
4. 嵌入来源不可用时只做第 1 步。用户改名 / 拆分会清空向量，下次抽取时补算；换嵌入模型后旧向量也按需补算。
5. 用户拆分出来的写法：抽取结果里以这个写法出现的提及和关系端点归到拆出来的实体（`kg_distinct`），新别名也不会再加回原实体。

原计划是"高相似度直接合并、模糊区间交给模型判定后合并"。测量后先改成嵌入只做候选、模型判定后合并；DeepSeek 评测里模型判定的误合并率仍有 10%–40%（见下文），最后改成模型判定也只产生建议。重新抽取时先删掉该文档产生的建议再重新生成；候选是本篇旧的自动实体、随后被回收时，建议级联删除。

### 用户编辑

- 改名：旧名留作别名；改类型、描述。实体变成 `origin=user`，重新抽取时不会被回收。
- 合并：别名、提及、关系端点都转给目标实体，源实体删除，产生的自环关系删除。
- 拆分：选中的别名连同以这些写法出现的提及、关系端点拆成新实体，写入 `kg_distinct`。至少要给原实体留一个别名。
- 删除关系：标 `rejected`，不再显示；重新抽取得到同一条 (src, dst, type, block) 时跳过。

### 提示词

- `kg_extract@2`：输入标题、组标题和 `[b_xxxx] 文本` 行；输出 `{"entities": [{id, type, name, aliases, description, block_ids}], "relations": [{src, dst, type, block_id, evidence, attrs, confidence}]}`。要求 name 不翻译、关系只引用给出的块号、摘句逐字抄写、`achieves` 的数值原样抄写（保留 <、±、%）、表格里每个结果单独一条；没有数值的结果不写成 achieves；幅度、倍数、消融差值要在 setting 里写明。
- `kg_resolve@2`：成对判定关系类别（same / narrower / broader / related / different），给出细胞系、版本、测量对象等反例。

v1 → v2 的原因见下文 §DeepSeek 评测。

### 接口

- `POST /documents/{doc_id}/kg/extract` → 202 `JobOut`；同一文档已有任务时返回它；模型不可用时 409，`detail = {code, message, provider_id}`。
- `GET /documents/{doc_id}/kg` → `{doc_id, kg_status, entities, relations}`：实体含本篇出现的块和出现在几篇文献；不返回 rejected 的关系。
- `GET /kg/entities?q=&type=&limit=`：按名称 / 别名搜索（合并时选目标）。
- `GET /kg/entities/{id}`：全库的提及和关系，带文献标题。
- `PATCH /kg/entities/{id} {name?, type?, description?}`；`POST /kg/entities/{id}/merge {source_ids}`；`POST /kg/entities/{id}/split {aliases}` → 新实体；`DELETE /kg/relations/{id}` → 204。
- `GET /documents/{doc_id}/kg` 里的 `suggestions`：涉及本篇实体的合并建议（`{id, score, entity, candidate}`）。`POST /kg/suggestions/{id}/accept` → 把 entity 并入 candidate，返回合并后的实体；`POST /kg/suggestions/{id}/dismiss` → 204，记为不是同一个。
- `GET /kg/subgraph?doc_id=|entity_id=`：本篇子图，或实体加一跳邻居（供下一项图谱浏览视图）。
- `DocumentOut` 新增 `kg_status`（`pending / extracting / ready / failed`）；已有图谱时重新抽取失败会回到 `ready`。

## 测量

`scripts/m3_kg_resolve_eval.py`：用内置 multilingual-e5-small 对 22 对手写名称（10 对同一个、12 对不是同一个）算余弦。

| 类型 | A | B | 同一个 | 余弦 | 判定 |
|---|---|---|---|---|---|
| Dataset | ImageNet | ILSVRC 2012 | 是 | 0.929 | 送判定 |
| Dataset | ImageNet | ImageNet-1k | 是 | 0.920 | 送判定 |
| Model | BERT | Bidirectional Encoder Representations from Transformers | 是 | 0.864 | 送判定 |
| Method | LSTM | long short-term memory | 是 | 0.891 | 送判定 |
| Method | self-attention | intra-attention | 是 | 0.955 | 送判定 |
| Metric | top-1 accuracy | top-1 acc | 是 | 0.973 | 送判定 |
| Metric | BLEU | BLEU score | 是 | 0.978 | 送判定 |
| Dataset | COCO | MS COCO | 是 | 0.978 | 送判定 |
| Method | Transformer | Transformer architecture | 是 | 0.958 | 送判定 |
| Task | machine translation | 神经机器翻译 | 是 | 0.903 | 送判定 |
| Model | BERT-base | BERT-large | 否 | 0.966 | 送判定 |
| Dataset | ImageNet-1k | ImageNet-21k | 否 | 0.973 | 新建 |
| Model | GPT-2 | GPT-3 | 否 | 0.963 | 新建 |
| Model | Transformer | Transformer-XL | 否 | 0.963 | 送判定 |
| Model | ResNet-50 | ResNet-101 | 否 | 0.953 | 新建 |
| Dataset | CIFAR-10 | CIFAR-100 | 否 | 0.977 | 新建 |
| Metric | top-1 accuracy | top-5 accuracy | 否 | 0.966 | 新建 |
| Metric | BLEU | ROUGE-L | 否 | 0.941 | 送判定 |
| Dataset | WMT14 En-De | WMT14 En-Fr | 否 | 0.987 | 送判定 |
| Method | dropout | DropConnect | 否 | 0.961 | 送判定 |
| Model | BERT | RoBERTa | 否 | 0.948 | 送判定 |
| Task | image classification | object detection | 否 | 0.944 | 送判定 |

同一个 0.864–0.978，不是同一个 0.941–0.987，两段大面积重叠：如果按 0.95 直接合并，12 对里有 9 对会被误合并。所以嵌入只用来找候选（阈值 0.86，10 对同一个都能进判定），合并与否由模型决定；数字不同的 5 对在送判定前就排除了。

## DeepSeek 评测

`scripts/m3_kg_eval.py`，deepseek-chat（`kg_extract@1` / `kg_resolve@1`），评测集 31 篇（PyMuPDF 快速解析），内置 e5 找候选，4 篇并发、每篇 3 组并发。

| 项目 | 结果 |
|---|---|
| 文档 | 29 / 31 篇；另 2 篇是扫描版，没有文字层（任务失败："文档里没有可抽取图谱的正文"） |
| 耗时 / 调用 | 200 s；342 次调用，输入 86.6 万 / 输出 60.4 万 token |
| 规模 | 3565 个实体、3608 条关系（uses 1376、part_of 1139、evaluated_on 251、achieves 222…）；308 个实体出现在 2 篇以上 |
| **出处块存在** | **3608 / 3608** |
| 丢弃 | 数值核对不上 170、出处不在本组 9、关系不合法 91、实体不合法或无出处 45；失败的组 0 |
| 摘句 | 948 条核对不上被清空（26%） |
| 消歧 | 嵌入候选送判定 2696 对，判为同一个 119 对 |

人工抽检（逐篇 `eval-out/m3-kg/<doc_id>.md`）发现的问题和处理：

1. **紧挨中文的数字核对不上**（核对的 bug）：数字前一个字符按 `\w` 判断，中文也算 `\w`，"为66.5h""在68%""增加41倍"都找不到。改为只看拉丁字母和数字。
2. **摘句误判**：PDF 换行在中文里插入空格（"同义保 真度"），英文里又会吞掉空格（"BD Canto II" → "BDCantoII"）。改为去掉所有空白、统一连字符后比较，并接受省略号截断。真正改写过的摘句（如把摘要改述成一句话）仍然清空。
3. **非数值的 value**：被丢弃的 170 条里大约九成 value 是"shortened""更高""显著相关"之类的文字，丢弃是对的；提示词 v2 要求这类结果不写成 achieves。
4. **比较符号丢失**：`均值<50` 显示成 `= 50`。改为显示模型给的原写法。
5. **差值当成绩**："去掉 BFD 后准确率下降 0.4 GDT"被记成 `AlphaFold · GDT = 0.4`。提示词 v2 要求幅度、倍数、消融差值在 setting 里写明。
6. **判定把上下位 / 相关概念当成同一个**：119 对"是"里大约五分之一不对，几乎都是上下位或相关——HEK293T 细胞 ↔ HEK-293、深度生成模型 ↔ deep learning、CD19 CAR 阳性率 ↔ CD19 CARs、immunity-for-intelligence trade-off ↔ immunogenicity。跨语言的同义合并大多正确（流式细胞术 ↔ Flow cytometry、t检验 ↔ Student's t test）。`kg_resolve@2` 改成五选一的关系类别，只有 same 合并。

修正 1、2 后用缓存的 v1 回复离线重放（不联网）：保留的数值结果 222 → 262；仍因核对不上丢弃 128 条，其中真正是数值的只有 12 条（多为模型引错了块）；摘句清空 984 → 512 条（保留摘句的关系 87%）。数值结果抽检（AlphaFold、CodonTransformer 等）：方法、指标、数据集和数值与原文一致，出处跳转正确。

第一次复测 v2（2026-10-21）不能和 v1 直接比较，只作参考：

- 换了模型：deepseek-flash（v1 是 deepseek-chat）。每组输出约 9000 token（v1 约 1800），单次调用中位 34 s、22 次超过 60 s；35 个组失败、1 篇整篇失败，失败原因没有记录下来（当时警告只打在终端里）。
- 数据目录沿用了 v1：v1 的实体还在库里，消歧时和它们比较；整篇失败的那篇显示的还是 v1 的图；报告里的调用数混进了 v1 和离线重放。评测脚本已改为每次运行先清空图谱、只统计本次调用、警告写进 `run.log`。
- 可以看出的趋势：数值核对丢弃 22 条（v1 170），摘句清空 142 条，achieves 460 条；判定为同一个的 47 对里约 4–6 对可疑（v1 约五分之一），但明显的同义也被判成不同，如 HMMER v.3.3 ↔ HMMER v3.3、Cα r.m.s.d. at 95% coverage ↔ r.m.s.d.95、蛋白表达 ↔ protein expression、运行时间 ↔ runtime。

需要用 deepseek-chat 重跑一次，才能分清提示词和模型各自的影响。

第二次复测（deepseek-chat）一开始就遇到账户余额不足（HTTP 402），只有 3 组成功，没有结论。它暴露的问题已修正：之前所有组失败时任务报"模型没有返回可解析的图谱"，掩盖了真实原因；现在遇到 401 / 402 / 403 立即停止并报服务商的错误。

第三次复测（deepseek-chat，v2 提示词）：29 / 31 篇，但 DeepSeek 当天限流严重，79 个组失败（429 限流 371 次、读超时 55 次；同样并发下 v1 没有失败），所以总量（实体、关系、数值结果数）不能和 v1 比，只看成功部分的质量：

- **数值结果明显变好**：保留比较符号和范围（`>5,000`、`∼0.716`、`4.57 ± 0.39%`），倍数写明相对谁（"relative to Benchmark-FL2 in HepG2 cells"），抽检里没有文字 value。主体偶尔不理想（如把"median of 120 phospho-Ser"当成实体）。出处块存在 1223 / 1223。
- **判定没有变好**：判为同一个的 34 对里约 12–14 对不对（v1 约五分之一）：Pearson r 和 Spearman's r 都被并进了 "R"，hQTL ↔ haQTL analysis，脂质多聚复合物 ↔ LNP encapsulation，杰卡德指数 / 序列相似性 ↔ 密码子级匹配率。五选一的类别没有让 deepseek-chat 更谨慎。

结论：数值抽取的 v2 提示词保留；模型成对判定在两个模型、两版提示词上的误合并都在 10%–40%，自动合并不可靠，需要改策略（见遗留）。

## 验证

- `core`：268 个测试通过，新增 `tests/test_kg.py` 11 个：
  - 归一化与缩写拆分；数值解析与核对；判定规则（数字不同不送判定）；
  - 单组校验：越组块号、未知类型、端点不存在、找不到的数值、编造的摘句；
  - 抽取任务：实体、提及、关系入库，出处块都存在，结束信息，重新抽取不重复；
  - 跨文档：精确别名命中自动合并；嵌入候选经模型判定为同一个的只产生建议，两篇文档都能看到；确认后并入、否决后重新抽取不再建议；模型说不同时不建议；
  - 服务商返回 402 时任务失败并报服务商的错误，不再继续调用；
  - 用户合并 / 拆分 / 改名 / 删除关系后重新抽取不被推翻；
  - 重新解析时出处迁移，映射不上的标 stale；
  - 自动抽取开关、隐私确认、排队去重；API 状态码。
- `test_llm_gateway`：`kg_extract` 现在回退到总结的路由，"未配置"的断言改为只剩嵌入路由时对话任务找不到模型。
- 前端：`tsc`、`vitest` 通过。
- 浏览器模式（开发版 sidecar、Vite、本地 OpenAI 兼容 mock，mock 复用 `test_kg.responder`；内置 e5 模型）：
  - 打开 FooNet 论文 → 图谱 → 抽取图谱，弹出"发送文档内容进行图谱抽取？"，允许后出现 `6 个实体、4 条关系（丢弃 1 条原文里找不到的数值）`；
  - 数值结果 `FooNet · top-1 accuracy = 85.3（ImageNet）`，点出处跳到该段，PDF 上高亮；
  - 打开 BarNet 论文抽取：`与已有实体合并 3 个`，FooNet、ImageNet（别名 ILSVRC、ImageNet-1k）、top-1 accuracy 显示"2 篇"；
  - 在 ImageNet 上拆出 ILSVRC，再用"合并到…"搜索 imagenet 并入，恢复原状；
  - 设置 › 翻译、总结、问答与图谱：图谱抽取的服务、自动抽取开关；打开开关后导入第三篇，解析 → 嵌入 → 抽取图谱自动依次完成。
  - 改成合并建议后（新数据目录）：BarNet 抽取后出现"可能重复（2）"：ImageNet-1k ⇄ ImageNet、ILSVRC ⇄ ImageNet（内置 e5 余弦 0.967 / 0.949），没有自动合并；对 ILSVRC 点"合并"后 ImageNet 显示别名 ILSVRC、"2 篇"，对 ImageNet-1k 点"不是"后建议消失；重新抽取：ILSVRC 按别名精确合并，ImageNet-1k 不再建议。

## 遗留

- [x] 用真实模型在评测集上评估抽取质量（DeepSeek，见 §DeepSeek 评测）。
- [x] 用 deepseek-chat 复测 v2：数值抽取变好；判定的误合并没有减少（见 §DeepSeek 评测）。
- [x] 跨文档消歧策略：只自动合并别名精确命中，模型判定为同一个的作为"可能重复"让用户确认。
- [ ] 用 DeepSeek 看合并建议的数量是否适合人工处理（v1 评测里判为同一个的约 4 对 / 篇）；太多时可以按相似度排序、只显示前几条，或在全库视图里集中处理。
- [ ] 评测时降低并发（如 `--jobs 2 --group-jobs 2`），避开限流。
- [ ] 扫描版 PDF 没有文字层，抽取直接失败；要等 OCR 解析（MinerU）后才能抽取。
- [ ] 表格里的结果：表格块文本是单元格拼接，模型要从表头推断方法 / 数据集，真实模型上要看效果；可能需要按行组织表格文本。
- [ ] 长论文的调用次数与章节组数相当，没有做"只抽取实验章节"之类的裁剪。
- [ ] 全库实体管理（搜索、批量合并、未关联实体清理）放到图谱浏览视图一起做。
- [ ] 跨文献问答、引用图、图谱浏览视图（Cytoscape.js）：路线图 M3 后续项。
