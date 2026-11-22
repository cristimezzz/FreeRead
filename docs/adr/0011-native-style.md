# ADR-0011：原生界面风格（macOS / WinUI 3）

- 状态：已接受
- 日期：2026-11-22
- 关联：[ADR-0009](0009-shadcn-ui.md)（shadcn/ui 组件与令牌）

## 背景

ADR-0009 之后界面只有一套暖色"纸张"风格，在 macOS 和 Windows 上看起来都不像本地应用：字体是 IBM Plex Sans，侧栏是实色，控件形状和系统不一致，强调色也和系统设置无关。

## 决定

新增"界面风格"设置 `appearance.style`：`native`（默认）/ `freeread`。原生风格在 macOS 上参考 macOS（AppKit 语义色、HIG），在 Windows 上参考 WinUI 3（Fluent 设计令牌）。Linux 没有统一的原生规范，`native` 在 Linux 上等同 `freeread`。

- **切换方式**：`app/theme.ts` 在 `<html>` 上写 `data-style="native|freeread"`、`data-platform="mac|win|linux"`。原生风格的全部差异在 `src/styles/native.css`，按这两个属性覆盖：
  - 令牌：`--background / --card / --popover / --border / --input / --muted-foreground …`、`--radius`、`--font-ui`、`--text-sm`（macOS 13px）。原生专用令牌以 `--native-*` 命名（分隔线、控件描边、控件底色、弹出层底色等），浅 / 深各一组。
  - 控件：按 shadcn 组件的 `data-slot` / `data-variant` / `data-state` 选择器覆盖颜色、圆角、阴影，不改 `components/ui/*` 源码，也不改尺寸——调用处传的高度、内边距照常生效。描边用 `box-shadow: inset` 画，避免 border 改变尺寸。
  - native.css 不进 Tailwind 的 layer，属性选择器的优先级本来就高于单类工具类；只有 `OptionToggle` 写了 `rounded-md!` 的地方用了 `!important`。
- **窗口材质**：macOS 用 NSVisualEffectView（`Effect.Sidebar`，随窗口激活状态），Windows 11 用 Mica（`Effect.Mica`），经 Tauri `setEffects` / `clearEffects` 运行时切换。为此窗口开 `transparent: true`，macOS 需要 `app.macOSPrivateApi: true`（tauri 的 `macos-private-api` feature）。
  - 材质是否可用由 Rust 命令 `native_look`（`src-tauri/src/native_look.rs`）判断：macOS 总可用；Windows 看 `CurrentBuildNumber ≥ 22000`。可用时写 `data-material="on"`，页面底色透明露出材质；否则（Windows 10、浏览器）用不透明的 `--native-window` 兜底。
  - `setTheme` 跟着深浅色设置走，材质与标题栏的深浅和页面一致。
- **Liquid Glass（macOS 26+）**：`native_look` 另报 `glass`（`NSAppKitVersionNumber ≥ 2685`，与 window-vibrancy 的判断一致），此时 `setEffects` 传 `[LiquidGlassRegular, Sidebar]`（Tauri 在旧系统上自动退回 vibrancy），`<html>` 写 `data-glass="on"`，换成 macOS 26 的样子：
  - 侧栏整列透明，顶到窗口上、下、左边缘，不留空隙，全部露出玻璃；内容区不透明，与侧栏之间一条分隔线。玻璃是整窗一层（NSGlassEffectView），只从透明的侧栏露出来。没有侧栏的页面（启动页、欢迎向导）用不透明底。红绿灯位置不变。
  - 控件更圆：按钮、下拉框、分段控件为胶囊形，弹出层 14px、对话框 22px 圆角。
- **布局**：原生风格下侧栏透明；macOS 内容区不透明、与侧栏之间一条分隔线；Windows 内容区是 Mica 上的一层（`LayerFillColorDefault`），位于标题栏下方、左上角 8px 圆角加描边，即 NavigationView 的内容区。
- **字体**：原生风格界面用系统字体（macOS `-apple-system` / 苹方，Windows Segoe UI Variable / 微软雅黑）。阅读正文（Source Serif 4）、编号（IBM Plex Mono）不变。
- **强调色**：`appearance.follow_system_accent`（默认 true）时用系统强调色：macOS `NSColor.controlAccentColor`，Windows `Explorer\Accent\AccentPalette` 的 SystemAccentColor（读不到退到 `DWM\AccentColor`）。窗口重新获得焦点时重读。读不到（Linux、浏览器）时用 `seed_color`。设置页色板第一个是"跟随系统"，点其他色板即关闭跟随。两种风格都可跟随系统强调色。
- **对比度**：原生风格下"中 / 高"对比度覆盖 `--muted-foreground`、`--native-separator`、`--native-stroke`（半透明黑 / 白），不用 freeread 的暖色阶。

## 备选方案

1. **每个平台一套组件**（例如 Windows 上用 Fluent UI Web Components）：最像原生，但要维护两套组件和交互，和 ADR-0009"组件只有一份"的目标相反。
2. **只调颜色和字体，不做窗口材质**：风险小，但侧栏实色与系统应用差距最明显，放弃。

## 后果

- 正面：macOS / Windows 上界面接近系统应用；新增控件只要在 native.css 里按 `data-slot` 补规则；原生与 FreeRead 两套风格共用组件和布局。
- 负面：
  - `macOSPrivateApi` 使应用不能上架 Mac App Store（目前也不上架）。
  - 透明窗口下，凡是没有背景的根元素都会露出材质；新页面的外壳要用 `--background` / `--card` 等令牌，不能假定 body 有实色。
  - native.css 依赖 shadcn 组件的 `data-slot` 名，升级 shadcn 组件时要核对。
- 跟进：在 Windows 11 / Windows 10 安装版上点一遍 Mica、自绘标题栏、各控件；macOS 上检查"降低透明度"辅助功能开启时侧栏的观感；macOS 15 及以下确认退回 vibrancy。
