// 自绘标题栏：窗口去掉了系统边框（tauri.conf.json decorations: false），
// 这里提供顶部的拖动区（双击最大化）与 最小化 / 最大化 / 关闭 按钮。只在 Tauri 里渲染。

import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useState } from "react";
import { isTauri } from "../api/core";
import { Icon } from "./icons";

const WINBTN =
  "text-foreground/80 hover:bg-foreground/8 hover:text-foreground active:bg-foreground/14 inline-flex h-(--titlebar-h) w-11.5 items-center justify-center transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring";

export function Titlebar() {
  const tauri = isTauri();
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!tauri) return;
    const win = getCurrentWindow();
    document.documentElement.dataset.titlebar = "";
    const sync = () => win.isMaximized().then(setMaximized).catch(() => {});
    sync();
    const off = win.onResized(sync);
    return () => {
      delete document.documentElement.dataset.titlebar;
      off.then((f) => f()).catch(() => {});
    };
  }, [tauri]);

  if (!tauri) return null;
  const win = getCurrentWindow();
  return (
    <div className="fixed inset-x-0 top-0 z-50 flex h-(--titlebar-h) justify-end select-none" data-tauri-drag-region>
      <div className="flex">
        <button type="button" className={WINBTN} aria-label="最小化" title="最小化" onClick={() => win.minimize()}>
          <Icon size={16} strokeWidth={1.25} name="winMin" />
        </button>
        <button
          type="button"
          className={WINBTN}
          aria-label={maximized ? "还原" : "最大化"}
          title={maximized ? "还原" : "最大化"}
          onClick={() => win.toggleMaximize()}
        >
          <Icon size={16} strokeWidth={1.25} name={maximized ? "winRestore" : "winMax"} />
        </button>
        <button type="button" className={`${WINBTN} hover:bg-[#c42b1c] hover:text-white active:bg-[#c42b1c] active:text-white`} aria-label="关闭" title="关闭" onClick={() => win.close()}>
          <Icon size={16} strokeWidth={1.25} name="winClose" />
        </button>
      </div>
    </div>
  );
}
