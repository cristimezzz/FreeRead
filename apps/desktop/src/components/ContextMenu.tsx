// 自定义右键菜单：取代 WebView 的默认菜单（刷新、检查等）。全局只有一个，openMenu 打开。

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { create } from "zustand";
import { Icon, type IconName } from "./icons";
import { usePresence } from "./motion";

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
  useMenu.setState({ menu: { x, y, items } });
}

export function closeMenu(): void {
  useMenu.setState({ menu: null });
}

export const isMenuOpen = () => useMenu.getState().menu !== null;

/** 快捷键提示里的修饰键：macOS 用 ⌘，其他平台用 Ctrl+ */
export const MOD = typeof navigator !== "undefined" && /Mac/.test(navigator.platform) ? "⌘" : "Ctrl+";

const EDGE = 8;

export function ContextMenu() {
  const menu = useMenu((s) => s.menu);
  // 关闭时保留最后的内容播放退出动画
  const last = useRef(menu);
  if (menu) last.current = menu;
  const { mounted, closing } = usePresence(Boolean(menu));
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);

  // 量好尺寸后再定位：靠右 / 靠下放不下时往左 / 往上翻
  useLayoutEffect(() => {
    const el = ref.current;
    if (!menu || !el) return;
    const { width, height } = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = menu.x;
    let top = menu.y;
    if (left + width > vw - EDGE) left = Math.max(EDGE, menu.x - width);
    if (top + height > vh - EDGE) top = Math.max(EDGE, vh - height - EDGE);
    setPos({ left, top });
  }, [menu]);

  // 打开时聚焦第一项，关闭后把焦点还给原来的元素
  useEffect(() => {
    if (!menu) return;
    if (!restoreFocus.current) restoreFocus.current = document.activeElement as HTMLElement | null;
    items(ref.current)[0]?.focus();
  }, [menu]);
  useEffect(() => {
    if (menu) return;
    const el = restoreFocus.current;
    restoreFocus.current = null;
    if (el?.isConnected) el.focus({ preventScroll: true });
  }, [menu]);

  useEffect(() => {
    if (!menu) return;
    const outside = (e: Event) => {
      if (!ref.current?.contains(e.target as Node)) closeMenu();
    };
    window.addEventListener("pointerdown", outside, true);
    window.addEventListener("scroll", outside, true);
    window.addEventListener("wheel", outside, true);
    window.addEventListener("resize", closeMenu);
    window.addEventListener("blur", closeMenu);
    return () => {
      window.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("scroll", outside, true);
      window.removeEventListener("wheel", outside, true);
      window.removeEventListener("resize", closeMenu);
      window.removeEventListener("blur", closeMenu);
    };
  }, [menu]);

  if (!mounted || !last.current) return null;
  const shown = last.current;

  const onKeyDown = (e: React.KeyboardEvent) => {
    const list = items(ref.current);
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    const move = (to: number) => list[(to + list.length) % list.length]?.focus();
    switch (e.key) {
      case "ArrowDown":
        move(i + 1);
        break;
      case "ArrowUp":
        move(i < 0 ? -1 : i - 1);
        break;
      case "Home":
        move(0);
        break;
      case "End":
        move(-1);
        break;
      case "Escape":
      case "Tab":
        closeMenu();
        break;
      default:
        return;
    }
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <div
      ref={ref}
      className="ctx-menu"
      role="menu"
      data-state={closing ? "closing" : "open"}
      style={pos ? { left: pos.left, top: pos.top } : { left: shown.x, top: shown.y, visibility: "hidden" }}
      onKeyDown={onKeyDown}
      onContextMenu={(e) => e.preventDefault()}
    >
      {shown.items.map((it, i) =>
        it === "separator" ? (
          <div key={`sep-${i}`} className="ctx-sep" role="separator" />
        ) : (
          <button
            key={`${i}-${it.label}`}
            type="button"
            role="menuitem"
            className={it.danger ? "danger" : undefined}
            disabled={it.disabled}
            tabIndex={-1}
            onClick={() => {
              closeMenu();
              it.onSelect();
            }}
          >
            <span className="ctx-icon">{it.icon && <Icon name={it.icon} size={16} />}</span>
            <span className="ctx-label">{it.label}</span>
            {it.shortcut && <kbd>{it.shortcut}</kbd>}
          </button>
        ),
      )}
    </div>
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

function items(root: HTMLElement | null): HTMLButtonElement[] {
  return root ? Array.from(root.querySelectorAll<HTMLButtonElement>("button[role=menuitem]:not(:disabled)")) : [];
}
