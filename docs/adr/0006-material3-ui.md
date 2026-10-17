# ADR-0006：前端采用 Material 3，使用官方 @material/web 组件

- 状态：已接受
- 日期：2026-10-18

## 背景

M1 开始实现文献库、阅读器、导入和设置界面，需要统一的视觉风格和组件库。我们按 M1 范围做了 Ant Design、Apple（macOS）、Material 3 三版界面稿进行对比（[Ant Design 稿](https://claude.ai/artifact/VZGSmyEtMiRToJjzii1M7i)、[Apple / M3 稿](https://claude.ai/artifact/8q23cKwhSe79o8Fo8x4u8h)），最终选定 Material 3。

另一个需求：配色不固定，设置里提供几套主题色供用户选择。

约束：

- 前端是 Tauri 2 + React 19 + TypeScript；Windows 上运行在 WebView2（Chromium）里。
- 阅读区（重排视图）有自己的排版需求：衬线正文、KaTeX 公式、按块高亮，不依赖组件库。

## 备选方案

1. **MUI + 自定义 M3 主题**：React 生态成熟，组件齐全（含 Data Grid、Tree View）；但 MUI 默认是 Material 2 的视觉，M3 的形状、色彩角色和状态层都要靠主题覆盖，长期看会和规范逐渐偏离。
2. **官方 `@material/web`（Material Web Components）**：Google 维护的 M3 参考实现，样式和交互与规范一致，以 `--md-sys-*` CSS 变量换肤；但它是 Lit 写的 Web Components，组件不全，且官方目前标注为维护模式（等待新的维护者）。
3. **自研组件，只沿用 M3 设计令牌**：完全可控，但工作量大。

## 决定

选择方案 2：使用 `@material/web`，并配合 `@material/material-color-utilities` 生成配色。

- **组件**：按钮、FAB、图标按钮、复选框、单选、开关、滑块、选择框、文本框、列表、菜单、对话框、标签页、chips、进度条直接使用 `@material/web`；分段按钮、导航栏 / 抽屉、卡片、徽标从 `@material/web/labs/` 引入。
- **React 集成**：React 19 原生支持自定义元素的属性和事件，直接写 `<md-filled-button>`；在 `src/components/` 里为常用组件补 TypeScript 的 JSX 类型声明，必要时包一层薄封装。
- **官方没有的组件**自己实现，只使用 M3 令牌（`--md-sys-color-*`、`--md-sys-shape-*`、`--md-sys-typescale-*`），包括：导航栏（navigation rail）、顶部应用栏、侧边面板（side sheet）、Snackbar、Tooltip、文献列表 / 表格、分类树。
- **配色**：设置 › 外观提供几套预设主题色（紫、蓝、青、绿、琥珀、玫红），外加"跟随系统强调色"和"自定义"。所选种子色交给 `material-color-utilities`（Tonal Spot 方案）生成浅色、深色两套色彩角色，写入 `:root` 的 `--md-sys-color-*`；还支持浅色 / 深色 / 跟随系统，以及标准 / 中 / 高三档对比度。
- **字体**：界面用 Roboto + 思源黑体；重排正文用衬线体（Source Serif 4 + 思源宋体），不受主题字体影响。
- **阅读区高亮**：原版 ⇄ 重排的定位高亮使用 tertiary 色彩角色，与主色区分开，换主题时跟着变。

## 后果

- 正面：视觉和交互与 M3 规范一致；换肤只需改 CSS 变量，主题选择实现简单；Web Components 不绑定框架。
- 负面：`@material/web` 处于维护模式，新特性和问题修复可能变慢；表格、树、导航栏等需要自己实现；Web Components 在 React 里的类型提示和 SSR 支持弱于 React 原生组件（本项目不做 SSR，影响有限）。
- 跟进：
  - M1 先封装 `ThemeProvider`（种子色 → CSS 变量，持久化在 `/settings`），并补齐 JSX 类型声明。
  - 自研组件放在 `src/components/m3/`，只引用 `--md-sys-*` 令牌，不写死颜色。
  - 持续关注 `@material/web` 的维护状态；如果长期无人维护，评估把已用组件 fork 到仓库内，或迁移到方案 1。
