# ADR-10 翻译与 LLM：Provider 抽象 + 本地优先 ✅

- 状态：接受；日期：2026-10-03
- 来源：[技术方案 §2](../../plan/FreeRead-技术方案与里程碑.md)

- **选择**：统一 `TranslatorProvider` / `LlmProvider` 接口，内置实现：
  1. **Ollama**（MIT，本地，默认推荐，零成本零上传）；
  2. **OpenAI 兼容 HTTP**（用户自带 baseURL + key，覆盖 OpenAI/DeepSeek/通义/Kimi/本地 vLLM）；
  3. **无模型时的降级**：仅提供"原文 + 词典式划词"（内置 ECDICT 词库，MIT/CC），保证核心阅读不空洞。
- **理由**：这是与 Scholaread（纯云端、配额制）形成差异的关键；且避免我们承担模型成本与合规责任。
- **被否**：内置免费翻译 API 池（不稳定、违反 ToS）；自建模型网关（V1 无服务器）。
- **风险**：本地模型质量参差 → 在 UI 中提供"术语表 + 译文二次编辑 + 一键切换 Provider"。
