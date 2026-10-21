// 设计令牌：固定的暖中性色阶（浅色 / 深色）+ 一个强调色，写入 :root。见 ADR-0007。
// 强调色只用于指认（选中项、引用编号、定位高亮、焦点环、进度），主按钮用墨色。

export type ThemeMode = "system" | "light" | "dark";
export type Contrast = "standard" | "medium" | "high";

export const DEFAULT_ACCENT = "#D97757";

export const ACCENT_PRESETS: { name: string; color: string }[] = [
  { name: "陶土", color: "#D97757" },
  { name: "墨蓝", color: "#4F74B8" },
  { name: "苔绿", color: "#6F8546" },
  { name: "石板", color: "#6B6A63" },
];

type Ramp = Record<
  "bg" | "bg2" | "surface" | "ink" | "ink2" | "ink3" | "line" | "line2" | "hover" | "ok" | "err" | "btn" | "btn-ink" | "page" | "scrim",
  string
>;

const LIGHT: Ramp = {
  bg: "#FAF9F5",
  bg2: "#F0EEE6",
  surface: "#FFFFFF",
  ink: "#141413",
  ink2: "#3D3D3A",
  ink3: "#65645E",
  line: "#E6E3DA",
  line2: "#D4D0C4",
  hover: "rgba(20, 20, 19, 0.05)",
  ok: "#3F6B45",
  err: "#A3402F",
  btn: "#141413",
  "btn-ink": "#FAF9F5",
  page: "#FFFFFF",
  scrim: "rgba(20, 20, 19, 0.32)",
};

const DARK: Ramp = {
  bg: "#1F1E1D",
  bg2: "#262624",
  surface: "#30302E",
  ink: "#F3F1EA",
  ink2: "#D6D3C8",
  ink3: "#A6A398",
  line: "#3B3A37",
  line2: "#4C4A45",
  hover: "rgba(255, 255, 255, 0.06)",
  ok: "#9CC79C",
  err: "#EBA08C",
  btn: "#F3F1EA",
  "btn-ink": "#1F1E1D",
  page: "#ECEAE3",
  scrim: "rgba(0, 0, 0, 0.5)",
};

// 提高对比度：次级 / 辅助文字往主文字压，分隔线加深
const CONTRAST: Record<"light" | "dark", Record<Exclude<Contrast, "standard">, Partial<Ramp>>> = {
  light: {
    medium: { ink2: "#2E2E2B", ink3: "#4F4E49", line: "#D4D0C4", line2: "#B9B4A6" },
    high: { ink2: "#1F1F1D", ink3: "#3D3D3A", line: "#B9B4A6", line2: "#8F8A7D" },
  },
  dark: {
    medium: { ink2: "#E4E1D7", ink3: "#C2BFB3", line: "#4C4A45", line2: "#625F58" },
    high: { ink2: "#F3F1EA", ink3: "#D6D3C8", line: "#625F58", line2: "#807C73" },
  },
};

// 强调色文字：浅色向黑、深色向白混合；对比度越高混得越多
const ACCENT_INK: Record<"light" | "dark", Record<Contrast, string>> = {
  light: { standard: "70%", medium: "60%", high: "50%" },
  dark: { standard: "62%", medium: "50%", high: "40%" },
};

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

/** 生成 CSS 变量表（纯函数，便于测试）。 */
export function themeVars(accent: string, dark: boolean, contrast: Contrast): Record<string, string> {
  const tone = dark ? "dark" : "light";
  const ramp: Ramp = { ...(dark ? DARK : LIGHT), ...(contrast === "standard" ? {} : CONTRAST[tone][contrast]) };
  const vars: Record<string, string> = {};
  for (const [k, v] of Object.entries(ramp)) vars[`--${k}`] = v;
  vars["--accent"] = accent;
  vars["--accent-ink"] = `color-mix(in oklab, var(--accent) ${ACCENT_INK[tone][contrast]}, ${dark ? "#fff" : "#000"})`;
  vars["--accent-soft"] = `color-mix(in srgb, var(--accent) ${dark ? 22 : 14}%, transparent)`;
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
  for (const [k, v] of Object.entries(themeVars(accent, dark, contrast))) root.style.setProperty(k, v);
  root.dataset.theme = dark ? "dark" : "light";
  root.style.colorScheme = dark ? "dark" : "light";
}
