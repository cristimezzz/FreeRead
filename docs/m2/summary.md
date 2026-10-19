# M2-2：分层总结、结构化模板、引用可跳转

- 日期：2026-10-19
- 关联：[路线图 M2](../04-roadmap.md)、[架构 §5.6](../01-architecture.md)、[数据模型 summaries](../03-data-model.md)、[M2-1 检索](README.md)

## 结论速览

| 项目 | 结果 |
|---|---|
| 生成方式 | 按需：阅读器右侧"总结"面板里点"生成"，SSE 推送章节进度，结果存库，再打开直接显示 |
| 结构 | Map（按一级章节分组，各组出带引用的要点）→ Reduce（按模板分节汇总） |
| 模板 | `paper`（研究问题 / 方法 / 实验与结果 / 结论 / 局限 / 可复用点）、`brief`（一句话总结 / 关键要点 / 局限） |
| 引用 | 每条要点带块编号，点击后重排视图居中定位、原版视图高亮；没有有效引用的要点标"未溯源" |
| 换模板 | Map 全部命中缓存，只多一次 Reduce 调用（本机 mock 下 11 组的论文从约 5 s 降到 1.6 s） |
| 路由与隐私 | 未单独设置时沿用翻译的服务（设置 › 总结 › "与翻译相同"）；首次发送前弹确认框，和翻译共用同意记录 |
| 验收（引用覆盖率 ≥ 90%） | **待测**：评测脚本已就绪，假模型下链路跑通；真实模型数据需要配置 API Key 后运行，见下文 |

## 设计

### Map：分组（`domain/summary/grouping.py`）

- 每个块沿 section 的 `parent_id` 找到根章节（通常是一级标题），按根章节分组。第一个标题之前的块（论文标题、摘要）单独成一组"标题与摘要"。
- 只送可检索的块（可翻译类型和表格），正文用 `block_plain_text` 展开占位符。参考文献、作者信息、公式块不送。标题块只作为组内的小标题行，不带编号，避免模型引用标题。
- 相邻小组合并到约 3000 token，超过 6000 token 的组按块边界切开（标题加"（续）"）。评测集里一篇 14 页的英文论文切成 9 组，28 页的中文译本切成 11 组。
- 每个块在提示词里写成 `[b_0012] 文本`，要求模型原样抄写编号。

### 提示词（`core/prompts/`）

- `summarize_map@1`：只依据给出的内容提炼 3–8 个要点，每条给 1–3 个块编号，只输出 `{"points": [...]}`。
- `summarize_reduce@1`：输入各组要点（要点后面带编号）和模板的小节说明，按模板 key 输出 `{"sections": [...]}`。合并要点时合并编号（最多 4 个）；论文没涉及的小节输出空列表。
- 模板在 `core/prompts/templates/summary.yaml`，每个模板有版本号，写进 `prompt_version`。
- Map 提示词与模板无关，所以同一篇论文换模板时 Map 调用全部命中 `llm_cache`，这就是"分层"带来的复用。

### 校验（`domain/summary/citations.py`）

- 规范化：`b_12`、`B_0012`、`b-12`、`d_…#b_0012`，以及写在正文里的 `[b_0012]` / `（b_1, b_2）`，都统一成 `b_NNNN`，并从正文里去掉。
- Map 阶段只接受本组的块，Reduce 阶段接受全文的块；不在范围内的编号丢弃，计入 `invalid_ids`。
- 没有有效引用的要点标 `untraced`，界面显示"未溯源"。
- 模型回复不是 JSON 时（常见于带了说明文字或 ``` 代码块），先从回复里取第一个完整的 JSON 对象；仍失败就不走缓存重试一次。Map 失败的组跳过并记在 `failed_groups`；全部失败或 Reduce 失败时报错。
- Reduce 把小节名写进 key、或者没写 key 时，按名称或位置对应到模板小节。

### 重新解析

块 ID 在重新解析后可能变化（快速模式 → MinerU）。`ParseService._store` 用迁移译文时的同一份块映射（IR §8）改写总结引用。有引用映射不上时，这条引用被去掉，总结标 `stale`，面板提示"原文已重新解析，可以重新生成"。

### 接口

- `GET /summary/templates`
- `GET /documents/{doc_id}/summaries?lang=`：已有总结，新的在前，离线可读。
- `POST /documents/{doc_id}/summary {template_id, lang?}`：SSE 事件依次为：
  - `progress {stage: map|reduce, done, total, title}`
  - `summary {SummaryOut}`
  - 出错时 `error {code, message, provider_id}`，code 为 `consent_required`、`route_not_configured`、`missing_api_key`、`unknown_template`、`llm_error` 或 `bad_output`
  - 最后 `done`

  面板关闭时请求中止，服务端取消未完成的调用；已完成的 Map 结果在缓存里，下次很快。

## 评测

验收标准是"评测集上总结的引用覆盖率 ≥ 90%"。

- 引用覆盖率 = 有有效引用的要点 / 全部要点（`freeread/eval/summary.py`）。
- 引用有效率 = 有效编号 / 模型给出的全部编号。
- 忠实度（引用的块是否真的支持这条结论）无法自动判断：脚本为每篇生成一份对照稿，把每条要点和它引用的原文并排列出，供人工抽检（PRD 目标为忠实度 ≥ 95%）。

```bash
cd core
# 真实模型（OpenAI 兼容接口），Key 从环境变量读取；--record 录下回复，之后可用 --replay 免费重跑
set FREEREAD_EVAL_API_KEY=sk-...
.venv/Scripts/python ../scripts/m2_summary_eval.py --base-url https://api.deepseek.com/v1 --model deepseek-chat --record ../eval-out/m2-summary/replies.json
# 只验证链路
.venv/Scripts/python ../scripts/m2_summary_eval.py --fake --limit 4
```

输出在 `eval-out/m2-summary/`：`report.md`（汇总表）、`<doc_id>.json`（总结与统计）、`<doc_id>.md`（人工抽检对照稿）。

### 结果

| 运行 | 文档 | 引用覆盖率 | 引用有效率 | 备注 |
|---|---|---|---|---|
| `--fake`（确定性假模型） | 4 篇 | 100%（170 / 170） | 100% | 只证明链路正确：假模型每条都按输入编号引用 |
| 真实模型 | — | **待测** | — | 需要 API Key |

## 验证

- `core`：183 个测试通过。`tests/test_summary.py` 新增 11 个，覆盖：
  - 分组：按根章节分组、标题前单独成组、合并 / 切开、参考文献排除；
  - 引用规范化与校验，JSON 提取；
  - 服务：Map 每组一次、Reduce 一次，换模板命中缓存，同一模板替换旧结果；
  - 回退到翻译路由，隐私确认，JSON 错误重试，小节名对应；
  - 全部失败时报错，重新解析后迁移引用与 `stale`；
  - API 和评测函数。

  `test_llm_gateway` 原来"总结未配置就报错"的断言改为不回退的 `kg_extract`，另加回退测试。翻译的测试没改，确认抽出共用 preflight 后行为不变。
- 前端：`tsc`、`vitest` 通过。
- 浏览器模式（开发版 sidecar、Vite、本地 OpenAI 兼容 mock，mock 用 `summary_responder` 回 JSON），在评测集的 mRNA 论文上：
  - 打开总结面板 → 生成 → 弹出"发送文档内容进行总结？"确认框 → 允许；
  - 进度依次为"正在读各章节（0 / 11）…（9 / 11）→ 正在汇总"，结果显示 6 个小节和引用标签；
  - 点引用后重排视图定位到对应块，原版高亮；
  - 换到"速览"模板再生成，1.6 s 完成；
  - 控制台没有错误。

## 遗留

- [ ] 用真实模型跑评测集，记录引用覆盖率和有效率，并人工抽检忠实度。**需要用户**：提供 API Key。拿到结果前路线图不勾选。
- [ ] 长文档的 Reduce 输入可能很长（各组要点全部拼在一起）。评测时关注输入 token 和耗时，必要时对 Reduce 再分层。
- [ ] 自定义模板（P2，M4 插件机制）；总结写回 Zotero 笔记（M4）。
- [ ] 分类级综述：`scope=collection:<id>` 已预留。
