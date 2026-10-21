// 内联线条图标（1.6px 描边，跟随 currentColor），不依赖图标字体，离线可用。见 ADR-0007。

const PATHS = {
  library: ["M4 19V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v14", "M9 19V7a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v12", "m14.5 6.8 2.9-.8a1 1 0 0 1 1.2.7l2.6 10.6", "M3 19h18"],
  book: ["M12 6.5C10 5 7.5 4.5 4 4.5v13c3.5 0 6 .5 8 2 2-1.5 4.5-2 8-2v-13c-3.5 0-6 .5-8 2z", "M12 6.5v13"],
  settings: [
    "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
    "M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  ],
  back: ["M19 12H5", "m11 18-6-6 6-6"],
  sync: ["M20 11a8 8 0 0 0-14.3-4.9L4 8", "M4 4v4h4", "M4 13a8 8 0 0 0 14.3 4.9L20 16", "M20 20v-4h-4"],
  upload: ["M12 15V3", "m7 8 5-5 5 5", "M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"],
  add: ["M12 5v14M5 12h14"],
  all: ["M5.5 4h13a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M3.5 9h17"],
  folder: ["M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"],
  chevronRight: ["m9 6 6 6-6 6"],
  expandMore: ["m6 9 6 6 6-6"],
  delete: ["M4 7h16", "M10 11v6M14 11v6", "M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12", "M9 7V4h6v3"],
  search: ["M17.5 11a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0z", "m20 20-4.2-4.2"],
  close: ["M6 6l12 12M18 6 6 18"],
  // 窗口按钮（自绘标题栏）
  winMin: ["M6.5 12h11"],
  winMax: ["M7 7h10v10H7z"],
  winRestore: ["M7 9h8v8H7z", "M9.5 9V7H17v7.5h-2"],
  winClose: ["M7 7l10 10M17 7 7 17"],
  summary: ["M5 6h14M5 11h14M5 16h9"],
  qa: ["M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.1A8 8 0 1 1 20 12z"],
  send: ["M12 19V5", "m5 12 7-7 7 7"],
  translate: ["M4 5h8M8 3v2", "M10 5c-.8 3.6-3 6.3-6 8", "M6 9c1 1.8 2.6 3.2 4.5 4", "m12 21 4-9 4 9", "M13.4 18h5.2"],
  glossary: ["M6 4h11a1 1 0 0 1 1 1v15H7a2 2 0 0 1-2-2V5a1 1 0 0 1 1-1z", "M5 18a2 2 0 0 1 2-2h11", "M9 8h5M9 11h3"],
  edit: ["M4 20h4L19 9l-4-4L4 16z", "m13.5 6.5 4 4"],
  graph: [
    "M8 6.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
    "M21 8a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
    "M14.5 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
    "M8 7l8 .6M6.8 8.6l4.2 7.1M17.4 10.2l-4 5.6",
  ],
  alert: ["M20.5 12a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0z", "M12 8v5M12 16h.01"],
  copy: ["M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z", "M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"],
  external: ["M14 4h6v6", "M20 4 11 13", "M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"],
  expand: ["M14 4h6v6", "M10 20H4v-6", "M20 4l-6.5 6.5", "M4 20l6.5-6.5"],
  collapse: ["M20 10h-6V4", "M4 14h6v6", "M14 10l6.5-6.5", "M10 14l-6.5 6.5"],
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, strokeWidth = 1.6 }: { name: IconName; size?: number; strokeWidth?: number }) {
  return (
    <svg
      className="ico"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/** 品牌标记：强调色方块里的一本打开的书。不传 size 时尺寸由 CSS（.mark）决定。 */
export function BrandMark({ size }: { size?: number }) {
  return (
    <span
      className="mark"
      style={size ? { width: size, height: size, borderRadius: Math.round(size * 0.27) } : undefined}
      aria-hidden="true"
    >
      {/* 与应用图标（src-tauri/icons/app-icon.svg）同一个图形 */}
      <svg width="64%" height="64%" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth={1.2} strokeLinejoin="round">
        <path d="M11.2 6.3C9.3 5 7 4.5 3.5 4.5v13.1c3.4 0 5.8.5 7.7 1.8z" />
        <path d="M12.8 6.3C14.7 5 17 4.5 20.5 4.5v13.1c-3.4 0-5.8.5-7.7 1.8z" opacity={0.82} />
      </svg>
    </span>
  );
}
