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
