# ADR-0005：统一 LLM Gateway，按任务路由模型

- 状态：已接受（M1-P4 实现，2026-10-18）
- 日期：2026-10-17

## 背景

翻译、总结、问答、图谱抽取、嵌入对模型的要求不同：翻译量大、对成本敏感；问答和总结需要强推理；嵌入需要稳定且最好在本地。用户可能使用不同的提供方，包括本地模型。

## 备选方案

1. 直接使用 LangChain / LlamaIndex 等框架。
2. 使用 LiteLLM 等多提供方 SDK。
3. 自建薄的 Gateway 层，内部可以调用 LiteLLM 或各家官方 SDK。

## 决定

选择方案 3。自建 `LLMGateway`，对上暴露 `complete / stream / embed`，统一处理：

- 按 `TaskKind` 路由 provider 和 model（用户在设置中配置）；
- 响应缓存（`llm_cache`）、限流、重试；
- 用量与费用审计（`llm_calls`）；
- 提示词以 `prompt_id@version` 引用，模板存放在 `core/prompts/`。

不在核心路径上依赖大型编排框架，以保持提示词、缓存和引用格式完全可控。

## 后果

- 正面：替换模型不影响业务代码；缓存和成本统计集中管理。
- 负面：需要自行维护 provider 适配层（以 OpenAI 兼容协议为主可覆盖大多数情况）。
- 跟进：提示词修改必须提升版本号，从而自动使旧缓存失效。

## 实现说明（M1-P4）

- 代码在 `core/freeread/infra/llm/`：`default_gateway.py`（路由、缓存、令牌桶、重试、审计）、`openai_compatible.py`（httpx，不依赖 LiteLLM）、`fake.py`（测试与无密钥开发）、`prompts.py`、`secrets.py`。
- `anthropic` 与 `ollama` 两种 kind 暂时也走 OpenAI 兼容端点；原生适配器按需再加。
- 重试最多 3 次尝试，退避 1s、2s（优先使用 `Retry-After`）；流式调用只在输出第一个 chunk 之前重试。
- `llm_calls` 只记录成功的调用（含缓存命中，命中时 token 记 0，即不计费）；失败只写日志。
- 嵌入按单条文本缓存（`prompt_id` 固定为 `embed@1`）。

## 前缀缓存与缓存质量（2026-11-10）

有两层缓存，互不替代：

- **本地 `llm_cache`**：整条请求（provider、model、`prompt_id@version`、消息、参数）完全相同才命中，命中后不调用服务商。
- **服务商的前缀缓存（prompt cache）**：DeepSeek、通义、Moonshot、OpenAI 等按"请求开头相同的 token 前缀"自动缓存，命中部分的输入 token 更便宜、首字更快。它只看前缀，所以提示词的排列顺序决定命中率。

约定：

- **稳定前缀 + 可变后缀**。提示词 YAML 的 `system`（规则、示例）和可选的 `context`（文档级内容：标题、摘要、整篇文档的术语表、全文）合成一条 system 消息，在同一文档、同一语言内必须逐字节相同；逐次调用变化的内容（当前段落、检索片段、问题）只能放在 `user`。`tests/test_llm_gateway.py` 检查 `system` / `context` 只引用文档级变量。
- **多轮只追加**。问答的追问链用 `Prompt.render(history=...)` 渲染成真正的 user / assistant 轮次，上一问的请求是这一问的前缀。
- **计量**。`Usage.cached_tokens` 读服务商返回的 `prompt_cache_hit_tokens`（DeepSeek）或 `prompt_tokens_details.cached_tokens`（OpenAI 格式），写入 `llm_calls.cached_input_tokens`（迁移 0012）。`scripts/llm_cache_report.py` 按任务输出本地命中率和前缀命中率。
- **预热**。前缀缓存要等第一个请求处理完才建立。system 不短于 1000 字符时，同一前缀的第一个请求先单独发出，其余的等它完成（流式等到首个 chunk，最多等 10 秒，失败或取消也放行）再并发；5 分钟没用过的前缀重新预热。
- **坏回复不进本地缓存**。`complete(accept=...)`：占位符对不上的译文、解析不了的 JSON 照常返回并记账，但不写 `llm_cache`；缓存里已有的坏回复按未命中处理。流式回复为空时也不写。
- `anthropic` 仍走 OpenAI 兼容端点，不支持 `cache_control`，前缀缓存对它不生效；需要时再加原生适配器。
