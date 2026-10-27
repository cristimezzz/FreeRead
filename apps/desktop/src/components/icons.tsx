// 图标：lucide-react（shadcn 默认图标库），按应用里的语义名称取用，离线可用。见 ADR-0009。

import {
  AlignLeft,
  ArrowLeft,
  ArrowUp,
  BookA,
  BookOpen,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Copy,
  ExternalLink,
  Folder,
  Inbox,
  Languages,
  Library,
  type LucideIcon,
  Maximize2,
  MessageCircle,
  Minimize2,
  Minus,
  Pencil,
  Plus,
  RefreshCw,
  Scan,
  Search,
  Settings,
  Square,
  Trash2,
  Upload,
  Waypoints,
  X,
} from "lucide-react";

const ICONS = {
  library: Library,
  book: BookOpen,
  settings: Settings,
  back: ArrowLeft,
  sync: RefreshCw,
  upload: Upload,
  add: Plus,
  all: Inbox,
  folder: Folder,
  chevronRight: ChevronRight,
  expandMore: ChevronDown,
  delete: Trash2,
  search: Search,
  close: X,
  // 窗口按钮（自绘标题栏）
  winMin: Minus,
  winMax: Square,
  winRestore: Copy,
  winClose: X,
  summary: AlignLeft,
  qa: MessageCircle,
  send: ArrowUp,
  translate: Languages,
  glossary: BookA,
  edit: Pencil,
  graph: Waypoints,
  alert: CircleAlert,
  copy: Copy,
  external: ExternalLink,
  expand: Maximize2,
  collapse: Minimize2,
  fit: Scan,
} satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICONS;

export function Icon({
  name,
  size = 16,
  strokeWidth = 1.75,
  className,
}: {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  const C = ICONS[name];
  return <C className={className} size={size} strokeWidth={strokeWidth} aria-hidden="true" />;
}

export function BrandMark({ size }: { size?: number }) {
  return (
    <span
      className="inline-flex size-8 flex-none items-center justify-center rounded-lg bg-brand text-white"
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
