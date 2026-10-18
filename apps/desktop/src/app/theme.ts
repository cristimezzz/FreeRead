// 种子色 → M3 色彩角色（Tonal Spot），写入 :root 的 --md-sys-color-*。见 ADR-0006。

import {
  Hct,
  MaterialDynamicColors,
  SchemeTonalSpot,
  argbFromHex,
  hexFromArgb,
} from "@material/material-color-utilities";

export type ThemeMode = "system" | "light" | "dark";
export type Contrast = "standard" | "medium" | "high";

export const PRESET_SEEDS: { name: string; color: string }[] = [
  { name: "紫", color: "#6750A4" },
  { name: "蓝", color: "#1F5FAD" },
  { name: "青", color: "#006A6A" },
  { name: "绿", color: "#3B6939" },
  { name: "琥珀", color: "#8B5000" },
  { name: "玫红", color: "#9C4061" },
];

const CONTRAST_LEVEL: Record<Contrast, number> = { standard: 0, medium: 0.5, high: 1 };

const ROLES = [
  "primary",
  "onPrimary",
  "primaryContainer",
  "onPrimaryContainer",
  "secondary",
  "onSecondary",
  "secondaryContainer",
  "onSecondaryContainer",
  "tertiary",
  "onTertiary",
  "tertiaryContainer",
  "onTertiaryContainer",
  "error",
  "onError",
  "errorContainer",
  "onErrorContainer",
  "background",
  "onBackground",
  "surface",
  "onSurface",
  "surfaceVariant",
  "onSurfaceVariant",
  "surfaceDim",
  "surfaceBright",
  "surfaceContainerLowest",
  "surfaceContainerLow",
  "surfaceContainer",
  "surfaceContainerHigh",
  "surfaceContainerHighest",
  "inverseSurface",
  "inverseOnSurface",
  "inversePrimary",
  "outline",
  "outlineVariant",
  "shadow",
  "scrim",
  "surfaceTint",
] as const;

const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

/** 生成 CSS 变量表（纯函数，便于测试）。 */
export function themeVars(seed: string, dark: boolean, contrast: Contrast): Record<string, string> {
  const scheme = new SchemeTonalSpot(Hct.fromInt(argbFromHex(seed)), dark, CONTRAST_LEVEL[contrast]);
  const vars: Record<string, string> = {};
  for (const role of ROLES) {
    vars[`--md-sys-color-${kebab(role)}`] = hexFromArgb(MaterialDynamicColors[role].getArgb(scheme));
  }
  return vars;
}

export function resolveDark(mode: ThemeMode): boolean {
  if (mode === "system") return window.matchMedia("(prefers-color-scheme: dark)").matches;
  return mode === "dark";
}

export function applyTheme(seed: string, mode: ThemeMode, contrast: Contrast): void {
  const dark = resolveDark(mode);
  const root = document.documentElement;
  for (const [k, v] of Object.entries(themeVars(seed, dark, contrast))) root.style.setProperty(k, v);
  root.dataset.theme = dark ? "dark" : "light";
  root.style.colorScheme = dark ? "dark" : "light";
}
