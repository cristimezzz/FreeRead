// 提示条：底部居中的墨色小卡片，几秒后自动消失（常驻提示除外）。

import { useEffect, useRef } from "react";
import { useApp } from "../app/store";
import { usePresence } from "./motion";

export function Snackbar() {
  const message = useApp((s) => s.snackbar);
  const sticky = useApp((s) => s.snackbarSticky);
  const toast = useApp((s) => s.toast);
  // 消失时保留最后一条文字播放退出动画
  const last = useRef(message);
  if (message) last.current = message;
  const { mounted, closing } = usePresence(Boolean(message));
  useEffect(() => {
    if (!message || sticky) return;
    const t = setTimeout(() => toast(null), 6000);
    return () => clearTimeout(t);
  }, [message, sticky, toast]);
  if (!mounted) return null;
  return (
    <div className="snackbar" role="status" data-state={closing ? "closing" : "open"}>
      <span key={last.current}>{last.current}</span>
      <button type="button" onClick={() => toast(null)}>
        关闭
      </button>
    </div>
  );
}
