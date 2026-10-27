// 主题：shadcn neutral 色阶（styles/index.css）+ 一个强调色 --brand，深色切 <html> 的 .dark 类。见 ADR-0009。
// 强调色只用于指认（选中项、引用编号、定位高亮、焦点环、进度），主按钮用 --primary。

export type ThemeMode = "system" | "light" | "dark";
export type Contrast = "standard" | "medium" | "high";

export const DEFAULT_ACCENT = "#D97757";

export const ACCENT_PRESETS: { name: string; color: string }[] = [
  { name: "陶土", color: "#D97757" },
  { name: "墨蓝", color: "#4F74B8" },
  { name: "苔绿", color: "#6F8546" },
  { name: "石板", color: "#6B6A63" },
];

// 中性色阶用 shadcn neutral（styles/index.css 的 :root / .dark），这里只写对比度覆盖：
// "中 / 高"把辅助文字往主文字压，分隔线、输入框描边加深
const CONTRAST: Record<"light" | "dark", Record<Exclude<Contrast, "standard">, Record<string, string>>> = {
  light: {
    medium: { "--muted-foreground": "oklch(0.45 0 0)", "--border": "oklch(0.86 0 0)", "--input": "oklch(0.82 0 0)" },
    high: { "--muted-foreground": "oklch(0.32 0 0)", "--border": "oklch(0.72 0 0)", "--input": "oklch(0.62 0 0)" },
  },
  dark: {
    medium: { "--muted-foreground": "oklch(0.8 0 0)", "--border": "oklch(1 0 0 / 18%)", "--input": "oklch(1 0 0 / 24%)" },
    high: { "--muted-foreground": "oklch(0.9 0 0)", "--border": "oklch(1 0 0 / 32%)", "--input": "oklch(1 0 0 / 40%)" },
  },
};

// 强调色文字：浅色向黑、深色向白混合；对比度越高混得越多
const BRAND_INK: Record<"light" | "dark", Record<Contrast, string>> = {
  light: { standard: "70%", medium: "60%", high: "50%" },
  dark: { standard: "62%", medium: "50%", high: "40%" },
};

// 图谱连线色：three.js 读不了 oklch，单独给一组十六进制
const KG_LINE = { light: "#737373", dark: "#a1a1a1" };

// 图谱实体类型的分类色（--kg-method 等）：按这个顺序相邻两色在色觉障碍下也能区分；
// 节点总带文字标签和图例，颜色不是唯一的区分方式。深色是单独选的一组，不是自动反色。
export const KG_COLORS: Record<string, { light: string; dark: string }> = {
  Method: { light: "#C8613F", dark: "#D26E4A" },
  Model: { light: "#4F74B8", dark: "#6A8ED1" },
  Metric: { light: "#B5891C", dark: "#B88A27" },
  Task: { light: "#9A5BA8", dark: "#A974BC" },
  Dataset: { light: "#5E8C3A", dark: "#6E984A" },
  Concept: { light: "#C24D7C", dark: "#CB648D" },
};

/** 生成写到 :root 行内的 CSS 变量（纯函数，便于测试）：强调色、对比度覆盖、图谱分类色。 */
export function themeVars(accent: string, dark: boolean, contrast: Contrast): Record<string, string> {
  const tone = dark ? "dark" : "light";
  const vars: Record<string, string> = { ...(contrast === "standard" ? {} : CONTRAST[tone][contrast]) };
  vars["--brand"] = accent;
  vars["--brand-ink"] = `color-mix(in oklab, var(--brand) ${BRAND_INK[tone][contrast]}, ${dark ? "#fff" : "#000"})`;
  vars["--brand-soft"] = `color-mix(in srgb, var(--brand) ${dark ? 22 : 14}%, transparent)`;
  vars["--kg-line"] = KG_LINE[tone];
  for (const [type, colors] of Object.entries(KG_COLORS)) vars[`--kg-${type.toLowerCase()}`] = colors[tone];
  return vars;
}

export function resolveDark(mode: ThemeMode): boolean {
  if (mode === "system") return window.matchMedia("(prefers-color-scheme: dark)").matches;
  return mode === "dark";
}

export function applyTheme(accent: string, mode: ThemeMode, contrast: Contrast): void {
  const dark = resolveDark(mode);
  const root = document.documentElement;
  // 切换对比度时先清掉上一次的覆盖
  for (const k of ["--muted-foreground", "--border", "--input"]) root.style.removeProperty(k);
  for (const [k, v] of Object.entries(themeVars(accent, dark, contrast))) root.style.setProperty(k, v);
  root.classList.toggle("dark", dark);
  root.dataset.theme = dark ? "dark" : "light";
  root.style.colorScheme = dark ? "dark" : "light";
}
