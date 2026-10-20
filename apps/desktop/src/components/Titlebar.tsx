// 自绘标题栏：窗口去掉了系统边框（tauri.conf.json decorations: false），
// 这里提供顶部的拖动区（双击最大化）与 最小化 / 最大化 / 关闭 按钮。只在 Tauri 里渲染。

import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useState } from "react";
import { isTauri } from "../api/core";
import { Icon } from "./icons";

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
    <div className="titlebar" data-tauri-drag-region>
      <div className="titlebar-controls">
        <button type="button" className="winbtn" aria-label="最小化" title="最小化" onClick={() => win.minimize()}>
          <Icon size={16} strokeWidth={1.25} name="winMin" />
        </button>
        <button
          type="button"
          className="winbtn"
          aria-label={maximized ? "还原" : "最大化"}
          title={maximized ? "还原" : "最大化"}
          onClick={() => win.toggleMaximize()}
        >
          <Icon size={16} strokeWidth={1.25} name={maximized ? "winRestore" : "winMax"} />
        </button>
        <button type="button" className="winbtn close" aria-label="关闭" title="关闭" onClick={() => win.close()}>
          <Icon size={16} strokeWidth={1.25} name="winClose" />
        </button>
      </div>
    </div>
  );
}
