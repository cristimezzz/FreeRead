// 动效小工具：退出动画期间保持挂载、一次性脉冲高亮。时长与缓动在 global.css 的 --dur-* / --ease 里。

import { useEffect, useState } from "react";

/** 与 global.css 的 --dur 一致；用户要求减少动效时为 0。 */
export function exitMs(): number {
  if (typeof window === "undefined" || !window.matchMedia) return 0;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 200;
}

/**
 * 关闭时先保留挂载，播放退出动画再卸载。
 * 返回 mounted（是否渲染）与 closing（是否处于退出动画，配合 data-state="closing"）。
 */
export function usePresence(open: boolean): { mounted: boolean; closing: boolean } {
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const ms = exitMs();
    if (!ms) {
      setMounted(false);
      return;
    }
    const t = setTimeout(() => setMounted(false), ms);
    return () => clearTimeout(t);
  }, [open]);
  return { mounted: open || mounted, closing: !open && mounted };
}

/** 让元素播放一次 .pulse 动画（定位跳转后提示落点）；重复调用会重新开始。 */
export function pulse(el: Element | null | undefined): void {
  if (!el) return;
  el.classList.remove("pulse");
  void (el as HTMLElement).offsetWidth; // 强制重排，重新触发动画
  el.classList.add("pulse");
  el.addEventListener("animationend", () => el.classList.remove("pulse"), { once: true });
}
