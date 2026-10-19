// 应用侧栏（ADR-0007）：248px，品牌 + 主导航；文献库页下方是分类树，设置页下方是本页锚点。
// 阅读器里收成 60px 图标栏，把宽度让给正文。

import { useApp, type View } from "../app/store";
import { CollectionTree } from "../features/library/CollectionTree";
import { SETTINGS_SECTIONS } from "../features/settings/sections";
import { BrandMark, Icon, type IconName } from "./icons";

type ReaderView = Extract<View, { name: "reader" }>;

let last: ReaderView | null = null;

/** 记住最近打开的文档，导航上的"阅读"回到它。 */
function useLastReader() {
  const view = useApp((s) => s.view);
  if (view.name === "reader") last = view;
  return last;
}

export function Sidebar() {
  const view = useApp((s) => s.view);
  const navigate = useApp((s) => s.navigate);
  const lastReader = useLastReader();

  const items: { key: View["name"]; label: string; icon: IconName; onClick: () => void }[] = [
    { key: "library", label: "文献库", icon: "library", onClick: () => navigate({ name: "library" }) },
  ];
  if (lastReader) {
    const target = lastReader;
    items.push({ key: "reader", label: "阅读", icon: "book", onClick: () => navigate(target) });
  }
  items.push({ key: "settings", label: "设置", icon: "settings", onClick: () => navigate({ name: "settings" }) });

  if (view.name === "reader") {
    return (
      <nav className="rail" aria-label="主导航">
        <BrandMark size={30} />
        {items.map((it) => (
          <button
            key={it.key}
            type="button"
            className={`ibtn${view.name === it.key ? " on" : ""}`}
            aria-label={it.label}
            title={it.label}
            aria-current={view.name === it.key ? "page" : undefined}
            onClick={it.onClick}
          >
            <Icon name={it.icon} />
          </button>
        ))}
      </nav>
    );
  }

  return (
    <aside className="side" aria-label="主导航">
      <div className="brand serif">
        <BrandMark />
        FreeRead
      </div>
      <nav className="side-nav">
        {items.map((it) => (
          <button
            key={it.key}
            type="button"
            className={`nav${view.name === it.key ? " on" : ""}`}
            aria-current={view.name === it.key ? "page" : undefined}
            onClick={it.onClick}
          >
            <Icon name={it.icon} />
            {it.label}
          </button>
        ))}
      </nav>
      {view.name === "library" && <LibrarySection />}
      {view.name === "settings" && <SettingsAnchors />}
    </aside>
  );
}

function LibrarySection() {
  const collections = useApp((s) => s.collections);
  const selected = useApp((s) => s.collectionId);
  const total = useApp((s) => s.libraryTotal);
  const setCollectionId = useApp((s) => s.setCollectionId);
  return (
    <>
      <div className="sec">分类</div>
      <CollectionTree collections={collections} selected={selected} total={total} onSelect={setCollectionId} />
    </>
  );
}

function SettingsAnchors() {
  const active = useApp((s) => s.settingsSection) ?? SETTINGS_SECTIONS[0].id;
  return (
    <>
      <div className="sec">本页</div>
      {SETTINGS_SECTIONS.map((s) => (
        <a
          key={s.id}
          className={`anchor${s.id === active ? " on" : ""}`}
          href={`#${s.id}`}
          aria-current={s.id === active ? "location" : undefined}
          onClick={(e) => {
            e.preventDefault();
            document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
            useApp.setState({ settingsSection: s.id, settingsPinned: s.id });
          }}
        >
          {s.label}
        </a>
      ))}
    </>
  );
}
