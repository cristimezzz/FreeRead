# ADR-0010：AI 相关界面采用 Vercel AI Elements（精简版）

- 状态：已接受（开发中，`feat/shadcn-ui` 分支；在 [ADR-0009](0009-shadcn-ui.md) 的 shadcn/ui 之上）
- 日期：2026-10-28

## 背景

问答、总结、翻译、任务条、图谱面板这些 AI 界面是手写的：等待态是静态文字，引用编号只有原生 `title` 提示，总结进度是一条进度条加一行字，任务浮窗是平铺列表。[Vercel AI Elements](https://ai-sdk.dev/elements) 是 shadcn 生态里专门做 AI 界面的组件集（复制进仓库，不是运行时依赖），正好补上这些交互。

## 决定

AI Elements 的组件放在 `src/components/ai-elements/`，**只拿 UI，并且按需精简**：

| 组件 | 用在 | 与上游的差别 |
| --- | --- | --- |
| `shimmer` | 问答等待、总结 / 抽取 / 翻译进度文字 | 动画改成 CSS 关键帧（`index.css` 的 `shimmer-sweep`），不依赖 `motion` |
| `message` | 问答卡片里的问题与回答、重答 / 另起 / 删除分支 | 只留 `Message` / `MessageContent` / `MessageActions` / `MessageAction`，去掉 Streamdown、分支选择器和 `ai` 类型 |
| `inline-citation` | `components/Citation.tsx`（问答、总结、图谱共用）：悬停浮出原文，点击跳回 | 只留悬浮卡和引文样式，不用轮播（embla）和 URL 徽章；用新增的 `ui/hover-card.tsx` |
| `chain-of-thought` | 总结生成的分步进度 | 去掉图片和搜索结果徽章；展开状态用 `useState` |
| `queue` | 任务浮窗按"进行中 / 排队"分组 | 去掉附件和 ScrollArea，滚动由浮窗容器负责 |

不引入的：

- **`ai` SDK / `useChat`**：后端是 Python core，经 `openapi-fetch` 调用，不走 Vercel AI SDK 协议。
- **Streamdown（`MessageResponse`）**：回答是纯文本加 `[b_0012]` 引用标记，子卡片"就此追问"的选段靠 `anchorRanges()` 按字符偏移加下划线。交给 markdown 渲染会打乱偏移，所以回答仍由 `QaCard.renderAnswer` 渲染。
- **`prompt-input`**：39KB，拉 `ai`、`nanoid`、cmdk 等；问答的 `Composer` 已经是 shadcn `Textarea` + `Button` 的圆角输入卡，不换。
- **`conversation`**：问答是树状画布（`QaCanvas`），不是线性对话。

## 后果

- 正面：等待态、引用、进度、任务列表有统一的 AI 交互；没有新增 npm 依赖。
- 负面：精简过的组件与上游不再逐字一致，上游更新要手动对照；`ai-elements/*` 文件头注释写明了删了什么。
- 用 `npx shadcn add @ai-elements/...` 安装时 CLI 会把 streamdown、mermaid、cmdk 等一起装上并询问是否覆盖 `ui/*`：不要直接运行，改为从 registry JSON 取源码后手工精简。
