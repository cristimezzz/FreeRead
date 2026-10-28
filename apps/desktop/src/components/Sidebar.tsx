// 应用侧栏（shadcn Sidebar，ADR-0009）：品牌 + 主导航；文献库页下方是分类树，设置页下方是本页锚点。
// 阅读器里收成图标栏（collapsible="icon"），把宽度让给正文；收展由当前页面决定。

import { useRef } from "react";
import { useApp, type View } from "../app/store";
import { CollectionTree } from "../features/library/CollectionTree";
import { SETTINGS_SECTIONS } from "../features/settings/sections";
import { BrandMark, Icon, type IconName } from "./icons";
import {
  Sidebar as SidebarRoot,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "./ui/sidebar";

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
  const { state } = useSidebar();
  // 收起（进阅读器）时分类树 / 设置锚点淡出而不是瞬间消失：阅读器页自己没有内容，沿用上一个页面的
  const section = useRef<"library" | "settings">("library");
  if (view.name === "library" || view.name === "settings") section.current = view.name;

  const items: { key: View["name"]; label: string; icon: IconName; onClick: () => void }[] = [
    { key: "library", label: "文献库", icon: "library", onClick: () => navigate({ name: "library" }) },
  ];
  if (lastReader) {
    const target = lastReader;
    items.push({ key: "reader", label: "阅读", icon: "book", onClick: () => navigate(target) });
  }
  items.push({ key: "settings", label: "设置", icon: "settings", onClick: () => navigate({ name: "settings" }) });

  return (
    <SidebarRoot collapsible="icon" aria-label="主导航">
      <SidebarHeader className="pt-4">
        {/* 展开时标题居中；收成图标栏时容器比内容窄，w-fit + max-w-full 让它贴左，Logo 与下方图标对齐，中间过渡连续 */}
        <div className="mx-auto flex w-fit max-w-full items-center gap-2.5 overflow-hidden pb-2 font-serif text-xl font-semibold tracking-tight whitespace-nowrap">
          <BrandMark />
          <span className="transition-opacity group-data-[collapsible=icon]:opacity-0">FreeRead</span>
        </div>
        <SidebarMenu>
          {items.map((it) => (
            <SidebarMenuItem key={it.key}>
              <SidebarMenuButton
                isActive={view.name === it.key}
                aria-current={view.name === it.key ? "page" : undefined}
                tooltip={it.label}
                onClick={it.onClick}
                className="data-[active=true]:[&>svg]:text-brand-ink"
              >
                <Icon name={it.icon} />
                <span>{it.label}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent
        className="transition-opacity duration-(--dur) ease-(--ease) group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:opacity-0"
        inert={state === "collapsed" || undefined}
      >
        {/* 固定宽度：侧栏收窄的过程中内容不跟着重新折行 */}
        <div className="animate-in fade-in-0 min-w-(--sidebar-width)" key={section.current}>
          {section.current === "library" && <LibrarySection />}
          {section.current === "settings" && <SettingsAnchors />}
        </div>
      </SidebarContent>
    </SidebarRoot>
  );
}

function LibrarySection() {
  const collections = useApp((s) => s.collections);
  const selected = useApp((s) => s.collectionId);
  const total = useApp((s) => s.libraryTotal);
  const setCollectionId = useApp((s) => s.setCollectionId);
  return (
    <SidebarGroup>
      <SidebarGroupLabel>分类</SidebarGroupLabel>
      <SidebarGroupContent>
        <CollectionTree collections={collections} selected={selected} total={total} onSelect={setCollectionId} />
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

function SettingsAnchors() {
  const active = useApp((s) => s.settingsSection) ?? SETTINGS_SECTIONS[0].id;
  return (
    <SidebarGroup>
      <SidebarGroupLabel>本页</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {SETTINGS_SECTIONS.map((s) => (
            <SidebarMenuItem key={s.id}>
              <SidebarMenuButton
                asChild
                size="sm"
                isActive={s.id === active}
                className="data-[active=true]:text-brand-ink data-[active=true]:bg-transparent"
              >
                <a
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
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
