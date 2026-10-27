# ADR-0009：界面组件改用 shadcn/ui + Tailwind CSS

- 状态：已接受（开发中，`feat/shadcn-ui` 分支；取代 [ADR-0007](0007-paper-ink-clay-ui.md) 的组件实现与视觉部分）
- 日期：2026-10-28

## 背景

ADR-0007 用 `src/components/ui.tsx` 里基于原生元素的小组件加一个约 3900 行的 `src/styles/global.css` 实现了"纸张、墨色与陶土"界面。用到现在的问题：

- 控件全部自己维护：分段控件的滑块、对话框的进出动画、右键菜单的定位与键盘导航、任务浮窗的点外部关闭，各写了一遍。新增一个控件（下拉菜单、单选组、折叠区、提示气泡）就要再写一遍样式和交互。
- 原生 `<select>` 的弹出层在不支持 `appearance: base-select` 的 WebView 里样式由系统决定，Linux（WebKitGTK）上和其他平台不一致。
- `global.css` 按页面分段，类名全局共享，删一个页面的样式要逐条确认有没有别处在用。

## 决定

改用 [shadcn/ui](https://ui.shadcn.com)（Radix UI 原语 + Tailwind CSS v4，组件代码复制进仓库），视觉采用 shadcn 默认的 neutral 主题，保留"强调色"设置。

- **组件**：`src/components/ui/` 是 shadcn CLI 生成的组件（button、input、select、switch、toggle-group、slider、progress、dialog、dropdown-menu、popover、tooltip、sonner、sidebar、collapsible、radio-group、checkbox、card、badge 等），按需改动的地方都写了注释（例如 sidebar 去掉 cookie 和 Ctrl+B）。新增控件先 `npx shadcn@latest add <name>`，注意 CLI 生成的 `cn` 导入要指向 `@/lib/utils`。
- **常用封装**：`src/components/controls.tsx` 在 shadcn 组件上包了一层"选项列表 + 回调"的接口：`OptionToggle`（分段控件）、`OptionSelect`（空字符串选项内部换成占位值，Radix Select 不接受空值）、`TextInput`（含 `commitOnChange`）、`LabeledSwitch`、`ProgressBar`（0–1，省略为不确定进度）、`IconButton`（带 Tooltip）、`ActionDialog`、`Spinner`。`SidePanel.tsx` 是阅读器右侧面板的外壳，`StatusTag.tsx` 是解析状态标签。
- **右键菜单**保留 `openMenu(x, y, items)` 的命令式接口，内部渲染受控的 `DropdownMenu`，锚点是放在指针位置的 0 尺寸元素；**提示条**改用 sonner，store 里的 `toast()` 接口不变。
- **侧栏**用 shadcn `Sidebar`（`collapsible="icon"`），收展由页面决定：阅读器里收成图标栏。
- **图标**换成 lucide-react（shadcn 默认图标库），`Icon name=` 的语义名称不变，映射在 `icons.tsx`。
- **令牌**：
  - 中性色阶用 shadcn neutral（`src/styles/index.css` 的 `:root` / `.dark`，OKLCH）；深色切 `<html>` 的 `.dark` 类。
  - shadcn 的 `--accent` 是悬停底色，应用自己的强调色改名为 `--brand`，派生 `--brand-ink`（强调色文字）、`--brand-soft`（浅底）；`--ring` 指向 `--brand`。Tailwind 里对应 `bg-brand`、`text-brand-ink`、`bg-brand-soft`。强调色仍只用于指认：选中项、引用编号、定位高亮、焦点环、进度。主按钮用 `--primary`。
  - "中 / 高"对比度覆盖 `--muted-foreground`、`--border`、`--input`。`app/theme.ts` 只往 `:root` 写强调色、对比度覆盖和图谱分类色（`--kg-*`，three.js 读不了 OKLCH，连线色单独给十六进制 `--kg-line`）。设置项（`appearance.seed_color` 等）不变。
- **字体**不变：界面 IBM Plex Sans，阅读正文 Source Serif 4，编号 IBM Plex Mono，经 `@theme` 接成 Tailwind 的 `font-sans` / `font-serif` / `font-mono`。
- **阅读区保留手写 CSS**：`src/styles/reader.css` 只放 FreeRead 自己的排版——原版 / 重排两栏与分隔条、PDF 页面、重排正文（衬线、KaTeX、按块高亮、对照 / 交替）、引用编号、批注、总结正文、问答画布与卡片、知识图谱、欢迎向导片头。它以 `@import "./reader.css" layer(components)` 引入，工具类能覆盖它。界面其余部分（外壳、文献库、设置、向导、面板外壳、对话框）全部用 Tailwind 工具类。
- **动效**：组件进出动画由 Radix + tw-animate-css 提供；阅读区手写 CSS 继续用 `--dur-*` / `--ease`；系统"减少动效"时全部归零。

## 备选方案

1. **保留自研组件，只把 `global.css` 改成 Tailwind**：样式问题解决一半，但下拉菜单、单选组、提示气泡这些交互仍要自己写。
2. **shadcn/ui 但保留"纸张、墨色与陶土"配色**：把 shadcn 变量映射到暖色阶，外观几乎不变。改动更小，但本次决定同时换成 shadcn 默认风格，作为新版界面在开发分支上评估。

## 后果

- 正面：控件的键盘操作、焦点管理、弹出层定位由 Radix 提供；新增控件一条 CLI 命令；样式跟着组件走，删页面不用担心误删别处的样式；`global.css` 的 3900 行缩到 `reader.css` 约 1200 行。
- 负面：多了 Tailwind、Radix、lucide 等依赖；组件代码在仓库里，shadcn 上游更新需要手动合并；Radix Select 不是原生控件，选项很多时需要滚动。
- 跟进：
  - 在安装版（WebView2 / WebKitGTK）里点一遍自绘标题栏、右键菜单替换默认菜单、拖动分隔条。
  - 观察 shadcn 默认风格下阅读区（衬线正文）与界面（无衬线）的协调程度，决定合入主线前是否微调配色。
