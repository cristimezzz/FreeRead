// M3 navigation rail（@material/web 没有提供，只用 M3 令牌自己实现）。

import { useApp } from "../../app/store";
import { Icon, type IconName } from "../icons";

export function NavigationRail() {
  const view = useApp((s) => s.view);
  const navigate = useApp((s) => s.navigate);
  const lastReader = useLastReader();

  const items: { key: string; label: string; icon: IconName; onClick: () => void; active: boolean }[] = [
    {
      key: "library",
      label: "文献库",
      icon: "library",
      onClick: () => navigate({ name: "library" }),
      active: view.name === "library",
    },
  ];
  if (lastReader) {
    items.push({
      key: "reader",
      label: "阅读",
      icon: "book",
      onClick: () => navigate(lastReader),
      active: view.name === "reader",
    });
  }
  items.push({
    key: "settings",
    label: "设置",
    icon: "settings",
    onClick: () => navigate({ name: "settings" }),
    active: view.name === "settings",
  });

  return (
    <nav className="rail" aria-label="主导航">
      {items.map((it) => (
        <button
          key={it.key}
          className="rail-item"
          aria-current={it.active ? "page" : undefined}
          onClick={it.onClick}
        >
          <span className="indicator">
            <Icon name={it.icon} />
          </span>
          {it.label}
        </button>
      ))}
    </nav>
  );
}

let last: Extract<ReturnType<typeof useApp.getState>["view"], { name: "reader" }> | null = null;

/** 记住最近打开的文档，导航栏上的"阅读"回到它。 */
function useLastReader() {
  const view = useApp((s) => s.view);
  if (view.name === "reader") last = view;
  return last;
}
