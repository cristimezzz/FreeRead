// 自定义右键菜单：取代 WebView 的默认菜单（刷新、检查等）。全局只有一个，openMenu 打开；
// 渲染用 shadcn 的 DropdownMenu（键盘导航、焦点归还由 Radix 提供）。

import { useEffect, useRef } from "react";
import { create } from "zustand";
import { Icon, type IconName } from "./icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

export type MenuItem =
  | {
      label: string;
      icon?: IconName;
      /** 右侧显示的快捷键提示，例如 "Ctrl+C" */
      shortcut?: string;
      danger?: boolean;
      disabled?: boolean;
      onSelect: () => void;
    }
  | "separator";

interface MenuState {
  menu: { x: number; y: number; items: MenuItem[] } | null;
}

const useMenu = create<MenuState>(() => ({ menu: null }));

/** 在视口坐标 (x, y) 打开菜单；空列表不打开。 */
export function openMenu(x: number, y: number, items: MenuItem[]): void {
  if (!items.length) return;
  // 已经打开时先关掉，下一帧在新位置重新打开（锚点移动后 Radix 不会自己重新定位）
  if (useMenu.getState().menu) {
    useMenu.setState({ menu: null });
    requestAnimationFrame(() => useMenu.setState({ menu: { x, y, items } }));
    return;
  }
  useMenu.setState({ menu: { x, y, items } });
}

export function closeMenu(): void {
  useMenu.setState({ menu: null });
}

export const isMenuOpen = () => useMenu.getState().menu !== null;

/** 快捷键提示里的修饰键：macOS 用 ⌘，其他平台用 Ctrl+ */
export const MOD = typeof navigator !== "undefined" && /Mac/.test(navigator.platform) ? "⌘" : "Ctrl+";

export function ContextMenu() {
  const menu = useMenu((s) => s.menu);
  // 关闭时保留最后的内容播放退出动画
  const last = useRef(menu);
  if (menu) last.current = menu;
  const shown = last.current;

  // 滚动、缩放窗口、窗口失焦时关闭（Radix 只处理点外部和 Esc）
  useEffect(() => {
    if (!menu) return;
    const close = () => closeMenu();
    window.addEventListener("wheel", close, true);
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    return () => {
      window.removeEventListener("wheel", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
    };
  }, [menu]);

  return (
    <DropdownMenu open={Boolean(menu)} onOpenChange={(open) => !open && closeMenu()} modal={false}>
      {/* 0 尺寸的锚点放在指针位置，菜单靠右 / 靠下放不下时由 Radix 翻转 */}
      <DropdownMenuTrigger asChild>
        <span
          aria-hidden="true"
          className="pointer-events-none fixed size-0"
          style={shown ? { left: shown.x, top: shown.y } : undefined}
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={0}
        collisionPadding={8}
        className="min-w-48"
        onContextMenu={(e) => e.preventDefault()}
      >
        {shown?.items.map((it, i) =>
          it === "separator" ? (
            <DropdownMenuSeparator key={`sep-${i}`} />
          ) : (
            <DropdownMenuItem
              key={`${i}-${it.label}`}
              variant={it.danger ? "destructive" : "default"}
              disabled={it.disabled}
              onSelect={() => it.onSelect()}
            >
              <span className="flex size-4 items-center justify-center">{it.icon && <Icon name={it.icon} />}</span>
              {it.label}
              {it.shortcut && <DropdownMenuShortcut>{it.shortcut}</DropdownMenuShortcut>}
            </DropdownMenuItem>
          ),
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** 写入剪贴板；失败（权限、非安全上下文）时退回 execCommand。 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

const TEXT_FIELD =
  'textarea, input:not([type]), input[type="text"], input[type="search"], input[type="url"], input[type="email"], input[type="number"], input[type="password"]';

/**
 * 屏蔽 WebView 默认右键菜单。组件自己处理过的（onContextMenu 里 preventDefault）不再管；
 * 其余情况：文本框给 剪切/复制/粘贴/全选，有选中文字给 复制，其他地方不弹菜单。
 * 返回卸载函数。
 */
export function installDefaultMenu(onError: (message: string) => void): () => void {
  const handler = (e: MouseEvent) => {
    if (e.defaultPrevented) return;
    e.preventDefault();
    const target = e.target instanceof Element ? e.target : null;
    const field = target?.closest<HTMLInputElement | HTMLTextAreaElement>(TEXT_FIELD);
    if (field) {
      openMenu(e.clientX, e.clientY, fieldItems(field, onError));
      return;
    }
    const selected = window.getSelection()?.toString() ?? "";
    if (selected.trim()) {
      openMenu(e.clientX, e.clientY, [
        { label: "复制", icon: "copy", shortcut: `${MOD}C`, onSelect: () => void copyText(selected) },
      ]);
    }
  };
  document.addEventListener("contextmenu", handler);
  return () => document.removeEventListener("contextmenu", handler);
}

function fieldItems(field: HTMLInputElement | HTMLTextAreaElement, onError: (m: string) => void): MenuItem[] {
  const hasSelection = (field.selectionStart ?? 0) !== (field.selectionEnd ?? 0);
  const editable = !field.readOnly && !field.disabled;
  const secret = field.type === "password";
  const run = (cmd: "cut" | "copy") => () => {
    field.focus();
    document.execCommand(cmd);
  };
  return [
    { label: "剪切", shortcut: `${MOD}X`, disabled: !hasSelection || !editable || secret, onSelect: run("cut") },
    { label: "复制", icon: "copy", shortcut: `${MOD}C`, disabled: !hasSelection || secret, onSelect: run("copy") },
    {
      label: "粘贴",
      shortcut: `${MOD}V`,
      disabled: !editable,
      onSelect: async () => {
        field.focus();
        try {
          const text = await navigator.clipboard.readText();
          // insertText 走浏览器的编辑流程：保留撤销记录，也会触发 React 的 onChange
          document.execCommand("insertText", false, text);
        } catch {
          onError(`无法读取剪贴板，请用 ${MOD}V 粘贴`);
        }
      },
    },
    "separator",
    {
      label: "全选",
      shortcut: `${MOD}A`,
      disabled: !field.value,
      onSelect: () => {
        field.focus();
        field.select();
      },
    },
  ];
}
