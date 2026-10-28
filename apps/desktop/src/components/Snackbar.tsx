// 提示条：sonner 的 Toaster，底部居中。store 里同时只有一条提示（snackbar），这里把它同步成一条固定 id 的 toast：
// 普通提示 6 秒后消失，常驻提示（例如 Core Service 已退出）不自动消失。

import { useEffect } from "react";
import { toast as sonner } from "sonner";
import { useApp } from "../app/store";
import { Toaster } from "./ui/sonner";

const ID = "app";

export function Snackbar() {
  const message = useApp((s) => s.snackbar);
  const sticky = useApp((s) => s.snackbarSticky);
  const toast = useApp((s) => s.toast);
  const themeMode = useApp((s) => s.settings?.appearance.theme_mode);

  useEffect(() => {
    if (!message) {
      sonner.dismiss(ID);
      return;
    }
    sonner(message, {
      id: ID,
      duration: sticky ? Infinity : 6000,
      cancel: { label: "关闭", onClick: () => toast(null) },
      onAutoClose: () => toast(null),
      onDismiss: () => toast(null),
    });
  }, [message, sticky, toast]);

  return <Toaster position="bottom-center" theme={themeMode ?? "system"} />;
}
