// 主题：shadcn neutral 色阶（styles/index.css）+ 一个强调色 --brand，深色切 <html> 的 .dark 类。见 ADR-0009。
// 强调色只用于指认（选中项、引用编号、定位高亮、焦点环、进度），主按钮用 --primary。
// 界面风格（ADR-0011）：<html data-style="native|freeread" data-platform="mac|win|linux">，
// 原生风格的令牌与控件形状在 styles/native.css；窗口材质（vibrancy / Mica）由这里经 Tauri 打开。

import { invoke } from "@tauri-apps/api/core";
import { Effect, EffectState, getCurrentWindow } from "@tauri-apps/api/window";
import type { components } from "../api/schema";
import { isTauri } from "../api/core";

export type ThemeMode = "system" | "light" | "dark";
export type Contrast = "standard" | "medium" | "high";
export type Appearance = components["schemas"]["Appearance"];
export type Platform = "mac" | "win" | "linux";
/** 实际生效的外观：freeread，或某个平台的原生风格。 */
export type Look = "freeread" | "mac" | "win";

export const DEFAULT_ACCENT = "#D97757";

export const DEFAULT_APPEARANCE: Appearance = {
  theme_mode: "system",
  style: "native",
  seed_color: DEFAULT_ACCENT,
  follow_system_accent: true,
  contrast: "standard",
};

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

/** 生成写到 :root 行内的 CSS 变量（纯函数，便于测试）：强调色、对比度覆盖、图谱分类色。
 *  原生风格下对比度覆盖写到 --native-* 上，由 native.css 接到各自平台的令牌（原生的分隔线是半透明黑 / 白）。 */
export function themeVars(accent: string, dark: boolean, contrast: Contrast, look: Look = "freeread"): Record<string, string> {
  const tone = dark ? "dark" : "light";
  const vars: Record<string, string> = {};
  if (contrast !== "standard") {
    const over = look === "freeread" ? CONTRAST[tone][contrast] : NATIVE_CONTRAST[tone][contrast];
    Object.assign(vars, over);
  }
  vars["--brand"] = accent;
  vars["--brand-ink"] = `color-mix(in oklab, var(--brand) ${BRAND_INK[tone][contrast]}, ${dark ? "#fff" : "#000"})`;
  vars["--brand-soft"] = `color-mix(in srgb, var(--brand) ${dark ? 22 : 14}%, transparent)`;
  vars["--kg-line"] = KG_LINE[tone];
  for (const [type, colors] of Object.entries(KG_COLORS)) vars[`--kg-${type.toLowerCase()}`] = colors[tone];
  return vars;
}

// 原生风格的对比度覆盖：辅助文字压深，分隔线 / 控件描边加不透明度
const NATIVE_CONTRAST: Record<"light" | "dark", Record<Exclude<Contrast, "standard">, Record<string, string>>> = {
  light: {
    medium: { "--muted-foreground": "rgb(0 0 0 / 66%)", "--native-separator": "rgb(0 0 0 / 18%)", "--native-stroke": "rgb(0 0 0 / 22%)" },
    high: { "--muted-foreground": "rgb(0 0 0 / 80%)", "--native-separator": "rgb(0 0 0 / 36%)", "--native-stroke": "rgb(0 0 0 / 50%)" },
  },
  dark: {
    medium: { "--muted-foreground": "rgb(255 255 255 / 70%)", "--native-separator": "rgb(255 255 255 / 20%)", "--native-stroke": "rgb(255 255 255 / 24%)" },
    high: { "--muted-foreground": "rgb(255 255 255 / 85%)", "--native-separator": "rgb(255 255 255 / 36%)", "--native-stroke": "rgb(255 255 255 / 46%)" },
  },
};

const OVERRIDDEN = ["--muted-foreground", "--border", "--input", "--native-separator", "--native-stroke"];

export function detectPlatform(): Platform {
  if (typeof navigator === "undefined") return "linux";
  const p = navigator.platform || navigator.userAgent;
  if (/Mac/i.test(p)) return "mac";
  if (/Win/i.test(p)) return "win";
  return "linux";
}

export const PLATFORM: Platform = detectPlatform();

/** 界面风格设置在当前平台上实际生效的外观：Linux 没有对应的原生规范，回落到 freeread。 */
export function resolveLook(style: Appearance["style"], platform: Platform = PLATFORM): Look {
  if (style !== "native" || platform === "linux") return "freeread";
  return platform;
}

export function resolveDark(mode: ThemeMode): boolean {
  if (mode === "system") return window.matchMedia("(prefers-color-scheme: dark)").matches;
  return mode === "dark";
}

/** Rust 命令 native_look 的返回（src-tauri/src/native_look.rs）。 */
export type NativeLook = { accent: string | null; material: boolean; glass: boolean };

let nativeLook: NativeLook | null = null;
let lastAppearance: Appearance = DEFAULT_APPEARANCE;
let lastEffects = "";

/** 当前读到的系统强调色（设置页"跟随系统"色块显示用）；还没读到或读不到时为 null。 */
export const systemAccent = () => nativeLook?.accent ?? null;

/** 读一次系统外观（强调色、材质可用性），读到的和上次不同就按最近的设置重新套用。 */
export async function refreshNativeLook(): Promise<void> {
  if (!isTauri()) return;
  try {
    const next = await invoke<NativeLook>("native_look");
    const changed =
      next.accent !== nativeLook?.accent || next.material !== nativeLook?.material || next.glass !== nativeLook?.glass;
    nativeLook = next;
    if (changed) applyTheme(lastAppearance);
  } catch (err) {
    console.warn("native_look failed", err);
  }
}

/** 按外观打开 / 关闭窗口材质，并让窗口（标题栏、材质）跟着深浅色设置走。只在变化时调用 Tauri。
 *  macOS 26+ 用 Liquid Glass；同时传 Sidebar，旧系统上 Tauri 会退回 vibrancy。 */
function applyWindowEffects(look: Look, mode: ThemeMode, glass: boolean): void {
  if (!isTauri()) return;
  const key = `${look}/${mode}/${glass}`;
  if (key === lastEffects) return;
  lastEffects = key;
  const win = getCurrentWindow();
  const run = async () => {
    await win.setTheme(mode === "system" ? null : mode);
    if (look === "mac") {
      const effects = glass ? [Effect.LiquidGlassRegular, Effect.Sidebar] : [Effect.Sidebar];
      await win.setEffects({ effects, state: EffectState.FollowsWindowActiveState });
    }
    else if (look === "win") await win.setEffects({ effects: [Effect.Mica] });
    else await win.clearEffects();
  };
  run().catch((err) => console.warn("window effects failed", err));
}

export function applyTheme(a: Appearance): void {
  lastAppearance = a;
  const dark = resolveDark(a.theme_mode);
  const look = resolveLook(a.style);
  const accent = (a.follow_system_accent && nativeLook?.accent) || a.seed_color;
  const root = document.documentElement;
  // 切换对比度 / 风格时先清掉上一次的覆盖
  for (const k of OVERRIDDEN) root.style.removeProperty(k);
  for (const [k, v] of Object.entries(themeVars(accent, dark, a.contrast, look))) root.style.setProperty(k, v);
  root.classList.toggle("dark", dark);
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.style = look === "freeread" ? "freeread" : "native";
  root.dataset.platform = PLATFORM;
  if (look !== "freeread" && nativeLook?.material) root.dataset.material = "on";
  else delete root.dataset.material;
  // macOS 26+：Liquid Glass 与对应的布局（浮起的玻璃侧栏、胶囊按钮），见 native.css
  const glass = look === "mac" && !!nativeLook?.glass;
  if (glass) root.dataset.glass = "on";
  else delete root.dataset.glass;
  root.style.colorScheme = dark ? "dark" : "light";
  applyWindowEffects(look, a.theme_mode, glass);
}

/** 启动时调用一次：读系统外观，窗口重新获得焦点时再读（用户可能在系统设置里改了强调色）。 */
export function watchNativeLook(): () => void {
  if (!isTauri()) return () => {};
  void refreshNativeLook();
  const onFocus = () => void refreshNativeLook();
  window.addEventListener("focus", onFocus);
  return () => window.removeEventListener("focus", onFocus);
}
