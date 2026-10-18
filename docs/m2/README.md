# M2-1：嵌入任务与混合检索

- 日期：2026-10-18
- 关联：[路线图 M2](../04-roadmap.md)、[架构 §5.7](../01-architecture.md)、[数据模型](../03-data-model.md)、[ADR-0002](../adr/0002-local-first-sqlite.md)、[ADR-0005](../adr/0005-llm-gateway.md)

## 结论速览

| 项目 | 结果 |
|---|---|
| 嵌入来源 | 默认用内置本地模型 multilingual-e5-small（int8 ONNX，129 MB，384 维），首次使用时下载；也可以改用大模型服务的嵌入接口（需要隐私确认） |
| 任务链 | `parse` / `parse_hq` 完成 → `embed`（并发 1）；下载模型完成、启动时、保存设置时给未嵌入的文档补排队 |
| 检索 | FTS5（trigram）关键词 + sqlite-vec 语义，RRF 融合为块级结果；没有向量时只走关键词 |
| 界面 | 设置 › 检索（来源、下载、下载源、自动建索引、重建）；阅读器 Ctrl+F 搜索面板，点结果同时定位重排视图和原版 |
| 嵌入耗时（本机 CPU） | 每篇 5–9 s（70–145 个 chunk）；MinerU 升级后重新嵌入 |
| 单篇检索延迟 | 向量 <1 ms + FTS；接口整体在几十毫秒内，主要花在算查询向量上 |
| 打包 | NSIS 安装包 36.01 → **53.75 MiB**；sidecar onedir 81.3 → 154.7 MB（186 个文件）；sidecar 热启动与 M1 持平（本机 1594 ms，CI 1546 ms），详见下文「安装包（CI）」；打包版本地模型推理、向量与全文检索实测正常 |

## 设计

### 嵌入来源

ADR-0005 要求嵌入"稳定且最好在本地"。选了 [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) 的 int8 ONNX 版（`Xenova/multilingual-e5-small` 的 `onnx/model_quantized.onnx`，MIT）：

- 中英文都支持，中文问句能找到英文段落（跨语言）；
- CPU 上 32 段 × 200 token 约 0.6 s，不需要 GPU；
- 只依赖 `onnxruntime`、`tokenizers`、`numpy`，不引入 torch。

模型文件固定到 HF 的某个 revision，逐个校验 sha256（`infra/embedding/registry.py`）。下载器（`infra/embedding/downloader.py`）写 `.part`、支持断点续传、校验后改名，是通用的，打包版 MinerU 的首次下载可以复用。默认从 `huggingface.co` 下载，设置里可改成镜像（如 `hf-mirror.com`）。

模型不会自动下载：用户在设置里点"下载模型"后才下载，下载完成自动给所有已解析文档排队。没有模型时关键词搜索照常可用。

选"大模型服务"时用 `routes["embed"]` 指定的服务（网关的 `embed` 早已实现，逐条缓存），和翻译一样需要先允许向该服务发送文档内容。

### 分块（`infra/search/chunker.py`）

- 只取可翻译的块类型和表格；公式块、图、参考文献、作者信息不参与；
- 行内公式占位符展开为 LaTeX，其余占位符去掉；表格取单元格文本；
- 标题块不单独成 chunk，作为所在 section 的标题加在每个 chunk 前面；
- 同一 section 内相邻的短块合并到约 256 token，超过 480 token 的块按句子拆，没有句末标点的超长文本按长度硬切；
- 每个 chunk 记录覆盖的 `block_ids` 和文本 sha256。重新解析后文本没变的 chunk 复用旧向量。快速模式 → MinerU 时块切分不同，实际上几乎全部重算。

### 存储

- `blocks_fts`（FTS5，trigram 分词）：中文不需要分词；少于 3 个字符的词（如"结构"）退回 `LIKE`。不用 FTS5 自带的 `snippet()`：trigram 下它按三字组计长度，片段只有二十几个字，还会把高亮截在词中间。
- `embedding_chunks` + `vec_chunks_<dim>`（vec0，`doc_id` 为分区键，cosine 距离，`chunk_size=128`）。详见[数据模型](../03-data-model.md)。
- 换来源 / 模型后向量不可混用：索引清空，所有文档重新排队。

### 融合（`infra/search/hybrid.py`、`services/search.py`）

两路各取前 50：FTS 按 bm25 排块；向量按距离排 chunk，再展开成块（块取所在 chunk 的名次）。RRF（k=60）只看名次，不需要把 bm25 和余弦距离归一化到同一尺度。英文问句里的虚词（which、how、were…）不参与关键词匹配，否则会命中一堆无关段落。

接口：`GET /documents/{doc_id}/search?q=&k=` 返回 `{query, modes, hits[{doc_id, block_id, type, page, score, sources, snippet}]}`，片段里的命中词用 `\x02` / `\x03` 包起来。以后的总结和问答通过 `SearchService.search_document` 取上下文。

## 测量

### 检索效果（评测集两篇，本地模型）

| 文档 | 查询 | 前几条 |
|---|---|---|
| mRNA 设计（中文译本） | 密码子优化 | 4 条都是讨论密码子优化与稳定性关系的段落（关键词 + 语义） |
| 同上 | 怎么评估 mRNA 的稳定性 | 扩展数据图 8、图 4、图 5 的说明（化学稳定性实验）和讨论段 |
| 同上 | 算法的时间复杂度是多少 | 纯语义命中：讨论算法效率的段落、图 3（运行时间随序列长度二次方增长） |
| 群体表观基因组（英文） | how many individuals were sequenced | 第 1 条即 "...individuals whose genomes were also sequenced..." |
| 同上 | 用了什么数据集（中文问英文文档） | 较差：前几条是链接列表、"ALL LINKS ARE ACTIVE IN THE ONLINE PDF" 等短块 |

跨语言的笼统问句是 e5-small 的弱项，短而杂的块容易排上来。可以考虑：过滤过短 / 链接类 chunk，或者提供更大的模型（bge-m3，约 570 MB int8）作为可选项。

### 向量检索延迟（sqlite-vec 0.1.9，384 维，每篇 150 个 chunk，随机向量，本机）

| chunk 数 | 存储 | 全库 KNN（k=50） | 单篇 KNN |
|---|---|---|---|
| 1 万（66 篇），`chunk_size` 默认 1024 | 101 MB | 94 ms | 2.2 ms |
| 1 万，`chunk_size=128` | 25 MB | 24 ms | 0.3 ms |
| 1 万，doc_id 作普通列（不分区） | 15 MB | 15 ms | 12.4 ms |
| 10 万（666 篇），默认 1024 | 1009 MB | 895 ms | 1.7 ms |
| 10 万，`chunk_size=128` | 254 MB | 246 ms | 0.4 ms |
| 10 万，不分区 | 151 MB | 151 ms | 128 ms |

vec0 每个分区至少占一个存储块，默认 1024 行时一篇论文的分区大部分是空的，文件是向量本身的 6–7 倍。选了分区 + `chunk_size=128`：单篇检索（M2 的总结、问答）最快，空间约为向量本身的 1.7 倍。全库检索是暴力扫描，10 万 chunk 约 0.25 s；ADR-0002 设想的 1 万篇（约 150 万 chunk）会到秒级，M3 做跨文献检索时需要重新评估（量化、ANN，或按 ADR-0002 换 LanceDB，接口已经是 `VectorIndex`）。

## 实现中的坑

- **WAL 模式下在显式事务里 DROP vec0 表报 `SQL logic error`**（autocommit 下正常）。所以向量表名带维度（`vec_chunks_384`），换模型时只清空不删表，旧维度的空表由 `drop_unused` 在 autocommit 连接上删除。
- **建 vec0 表、大批量 DML 时 SQLite 会写系统临时目录**，代理会话的沙箱里写不了（见 [M1 本机受限环境](../m1/README.md#本机受限环境更正不是-kaspersky)），报 `unable to open database file`。连接加了 `PRAGMA temp_store = MEMORY`，桌面应用本来也不需要临时文件。
- **嵌入状态变化也会发 `document` 事件**，阅读器原来收到就重新拉 IR、重置翻译请求。现在只在解析引擎 / 版本 / Normalizer 版本变化时才重新拉。
- 搜索结果跳转距离很远时，平滑滚动途中图片加载会改变布局，常常停在半路；远距离改为直接定位。

## 安装包（CI 干净机器）

由 `desktop-build.yml` 的 `scripts/verify_installed.ps1` 测得（[run 39132747977](https://github.com/cristimezzz/FreeRead/actions/runs/39132747977)，PR #14，GitHub Actions `windows-latest`）。M1 数据见 [m1/README.md](../m1/README.md#ci-干净机器github-actions-windows-latest无第三方杀毒)。

| 项目 | M2-1 | M1 |
|---|---|---|
| NSIS 安装包 | **53.75 MiB**（56,363,710 字节） | 36.01 MiB |
| 静默安装耗时 / 安装后目录 | 7.8 s / 159.1 MB，188 个文件 | 5.6 s / 85.7 MB，141 个文件 |
| sidecar 冷启动（每次复制到新目录） | 1633 / 2126 / 2616 / 2054 / 2084 ms，中位数 **2084 ms** | 中位数 1604 ms |
| sidecar 热启动 | 1524 / 1526 / 1546 / 4726 / 4801 ms，中位数 **1546 ms** | 中位数 1524 ms |
| 壳启动到 `/health` 可用（10 次） | 首次 6489 ms，之后 2074–2145 ms，中位数 **2130 ms** | 首次 3948 ms，中位数 1485 ms |
| 正常关闭后 `freeread-core` 清理 | ✅ 5/5，124–153 ms | ✅ 5/5，117–222 ms |
| `taskkill /F` 壳后清理 | ✅ 5/5，104–127 ms | ✅ 5/5，91–116 ms |

- 安装包增加约 17.7 MiB，来自 onnxruntime（38 MB 未压缩）、numpy + OpenBLAS（28 MB）、tokenizers（8 MB）。嵌入模型本身（129 MB）不在安装包里。
- sidecar 热启动和 M1 持平，onnxruntime / tokenizers 在第一次嵌入时才加载，不影响启动。冷启动和壳启动慢了约 0.5–0.6 s，这两项都包含首次读取新文件，原因应该是文件更多更大、Defender 首次扫描更久；本机热启动（1594 ms）没有看到同样的增加。没有单独做实验确认。
- 热启动里两次 4.7–4.8 s 的离群值和 M1 记录的"1.03 s / 1.52 s 两档跳变"不是一回事（量级不同），本次没有查原因。

## 验证

- `core`：171 个测试通过（新增 `tests/test_search.py` 14 个：文本展开、分块、RRF、FTS 中英文与 LIKE 回退、vec0 分区 / 清空 / 删旧表、下载续传与校验、嵌入任务与复用、解析 → 嵌入任务链、换来源后重建、隐私确认、混合检索、API）；`pytest -m slow` 下载真实模型并验证中文问句对英文段落的排序。
- 前端：`tsc`、`vitest` 通过。
- 浏览器模式（开发版 sidecar + Vite）：设置里下载模型（JobsBar 显示进度）→ 自动嵌入；导入评测集两篇 → 快速解析 → 嵌入 → MinerU 升级 → 重新嵌入；阅读器 Ctrl+F 搜索、点结果后重排视图居中定位、原版视图高亮。
- 打包版：`scripts/build_sidecar.ps1` + `scripts/measure_sidecar.ps1`（冒烟加了一次检索）；另外把模型放进数据目录，用打包版导入一篇论文，嵌入完成、`modes=fts,vector`。

## 遗留

- [x] NSIS 安装包体积：53.75 MiB（+17.7 MiB），见「安装包（CI 干净机器）」。
- [ ] 冷启动 / 壳启动在 CI 上慢了约 0.5–0.6 s（怀疑是 Defender 扫描更多文件），热启动有两次 4.7 s 的离群值：在本机安装版上复测确认原因。
- [ ] 跨语言笼统问句效果一般：过滤过短 / 链接类 chunk；评估 bge-m3 作为可选大模型。
- [ ] 全库 / 分类检索（M3 跨文献问答）：`SearchService` 已预留，全库向量检索在百万级 chunk 时需要量化或 ANN。
- [ ] 文献库搜索仍是 LIKE，`items_fts` 未做。
