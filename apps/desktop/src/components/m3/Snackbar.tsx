// M3 snackbar（官方组件库没有）：底部居中，几秒后自动消失。

import { useEffect } from "react";
import { useApp } from "../../app/store";

export function Snackbar() {
  const message = useApp((s) => s.snackbar);
  const toast = useApp((s) => s.toast);
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => toast(null), 6000);
    return () => clearTimeout(t);
  }, [message, toast]);
  if (!message) return null;
  return (
    <div className="snackbar" role="status">
      <span>{message}</span>
      <button onClick={() => toast(null)}>关闭</button>
    </div>
  );
}
