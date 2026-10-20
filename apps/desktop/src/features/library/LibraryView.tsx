import { useCallback, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { isTauri } from "../../api/core";
import { useApp } from "../../app/store";
import { copyText, isMenuOpen, MOD, type MenuItem, openMenu } from "../../components/ContextMenu";
import { Icon } from "../../components/icons";
import { Button, Dialog, Progress } from "../../components/ui";
import { ReparseDialog } from "../reader/ReparseDialog";
import { defaultDoc, formatAuthors, ItemList } from "./ItemList";

type Item = Schemas["ItemOut"];
type Doc = Schemas["DocRef"];
const PAGE = 100;
const MAX_PAGE = 500; // 服务端单页上限

/** 文献库快捷键：菜单里显示的提示与 keydown 处理共用这一张表 */
const KEYS = {
  open: "Enter",
  copy: `${MOD}C`,
  remove: "Delete",
  search: `${MOD}F`,
  import: `${MOD}O`,
  sync: "F5",
};

const TEXT_FIELD = 'input, textarea, select, [contenteditable="true"]';

function citation(item: Item): string {
  const head = [formatAuthors(item.authors), item.year && `(${item.year})`].filter(Boolean).join(" ");
  return `${[head, item.title, item.venue].filter(Boolean).join(". ")}.`;
}

/** 在 Zotero 中选中条目（zotero:// 协议，经 shell 插件交给系统打开） */
async function revealInZotero(key: string): Promise<void> {
  const url = `zotero://select/library/items/${key}`;
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("plugin:shell|open", { path: url });
  } else {
    window.open(url);
  }
}

function focusItem(id: string): void {
  const el = document.querySelector<HTMLElement>(`.item-row[data-item-id="${CSS.escape(id)}"]`);
  el?.focus({ preventScroll: true });
  el?.scrollIntoView({ block: "nearest" });
}

export function LibraryView() {
  const collections = useApp((s) => s.collections);
  const selected = useApp((s) => s.collectionId);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const libraryVersion = useApp((s) => s.libraryVersion);
  const seq = useRef(0); // 只采用最后一次请求的结果：搜索输入、切换分类时旧响应可能后到
  const loaded = useRef(0);
  const seenVersion = useRef(libraryVersion);
  loaded.current = items.length;
  const { navigate, toast, bumpLibrary } = useApp.getState();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Item | null>(null);
  const [reparseDoc, setReparseDoc] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    useApp
      .getState()
      .loadCollections()
      .catch((e) => toast(`加载分类失败：${e}`));
  }, [libraryVersion, toast]);

  const load = useCallback(
    async (offset: number, limit = PAGE) => {
      const id = ++seq.current;
      setLoading(true);
      try {
        const page = unwrap(
          await api().GET("/library/items", {
            params: {
              query: {
                collection_id: selected,
                q: debounced || null,
                offset,
                limit,
                sort: "added",
              },
            },
          }),
        );
        if (id !== seq.current) return;
        setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
        if (!selected && !debounced) useApp.setState({ libraryTotal: page.total });
      } catch (e) {
        if (id === seq.current) toast(`加载文献失败：${e}`);
      } finally {
        if (id === seq.current) setLoading(false);
      }
    },
    [selected, debounced, toast],
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  // 同步 / 解析进度推送触发的刷新：保留已经点开的"加载更多"，不要退回第一页
  const reload = useCallback(() => load(0, Math.min(MAX_PAGE, Math.max(PAGE, loaded.current))), [load]);
  useEffect(() => {
    if (seenVersion.current === libraryVersion) return;
    seenVersion.current = libraryVersion;
    void reload();
  }, [libraryVersion, reload]);

  const zoteroKey = collections.find((c) => c.id === selected)?.zotero_key ?? null;

  const sync = async () => {
    try {
      unwrap(await api().POST("/library/sync", { body: { collection_key: zoteroKey, full: false } }));
      toast(zoteroKey ? "已开始同步该分类" : "已开始从 Zotero 同步");
    } catch (e) {
      toast(`同步失败：${e}`);
    }
  };

  const importPdf = async () => {
    let paths: string[] = [];
    if (isTauri()) {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const picked = await open({ multiple: true, filters: [{ name: "PDF", extensions: ["pdf"] }] });
      paths = picked ? (Array.isArray(picked) ? picked : [picked]) : [];
    } else {
      const p = window.prompt("PDF 文件的本地绝对路径（浏览器开发模式）");
      paths = p ? [p] : [];
    }
    for (const path of paths) {
      try {
        const r = unwrap(await api().POST("/library/import-file", { body: { path } }));
        toast(r.created ? `已导入：${r.item.title}` : `已在文献库中：${r.item.title}`);
      } catch (e) {
        toast(`导入失败：${e}`);
      }
    }
    if (paths.length) bumpLibrary();
  };

  const open = (item: Item, picked?: Doc) => {
    const doc = picked ?? defaultDoc(item);
    if (!doc?.doc_id) {
      toast(item.documents.length ? "这个条目的 PDF 文件已不存在，请重新从 Zotero 同步" : "这个条目没有可用的 PDF 附件");
      return;
    }
    // 一个条目有多个 PDF 时标题后附文件名，区分正在读的是哪一个
    const title = item.documents.length > 1 ? `${item.title} · ${doc.filename}` : item.title;
    const byline = [formatAuthors(item.authors), item.year, item.venue].filter(Boolean).join(" · ");
    navigate({ name: "reader", docId: doc.doc_id, itemId: item.id, title, byline });
  };

  const copy = async (text: string, what: string) => {
    toast((await copyText(text)) ? `已复制${what}` : "复制失败");
  };

  const remove = async (item: Item) => {
    try {
      const r = await api().POST("/library/items/{item_id}/archive", { params: { path: { item_id: item.id } } });
      if (!r.response.ok) unwrap(r); // 204 没有响应体，unwrap 只用来抛出错误
      toast(`已移除：${item.title}`);
      // 选中项挪到相邻条目，方便连续操作
      const i = items.findIndex((x) => x.id === item.id);
      setSelectedId((items[i + 1] ?? items[i - 1])?.id ?? null);
      bumpLibrary();
    } catch (e) {
      toast(`移除失败：${e}`);
    }
  };

  const itemMenu = (item: Item): MenuItem[] => {
    const doc = defaultDoc(item);
    const menu: MenuItem[] = [
      { label: "打开", icon: "book", shortcut: KEYS.open, disabled: !doc?.doc_id, onSelect: () => open(item) },
    ];
    if (item.documents.length > 1) {
      for (const d of item.documents) {
        menu.push({ label: `打开 ${d.filename}`, disabled: !d.file_exists || !d.doc_id, onSelect: () => open(item, d) });
      }
    }
    menu.push(
      {
        label: "重新解析…",
        icon: "sync",
        disabled: !doc?.doc_id,
        onSelect: () => setReparseDoc(doc?.doc_id ?? null),
      },
      "separator",
      { label: "复制标题", icon: "copy", shortcut: KEYS.copy, onSelect: () => void copy(item.title, "标题") },
      { label: "复制引用", onSelect: () => void copy(citation(item), "引用") },
      { label: "复制 DOI", disabled: !item.doi, onSelect: () => void copy(item.doi ?? "", " DOI") },
    );
    const key = item.zotero_key;
    if (key) {
      menu.push({
        label: "在 Zotero 中显示",
        icon: "external",
        onSelect: () => void revealInZotero(key).catch((e) => toast(`无法打开 Zotero：${e}`)),
      });
    }
    menu.push("separator", {
      label: "移除文献…",
      icon: "delete",
      shortcut: KEYS.remove,
      danger: true,
      onSelect: () => setRemoving(item),
    });
    return menu;
  };

  const listMenu = (): MenuItem[] => [
    { label: "导入 PDF…", icon: "upload", shortcut: KEYS.import, onSelect: () => void importPdf() },
    {
      label: zoteroKey ? "同步此分类" : "从 Zotero 同步",
      icon: "sync",
      shortcut: KEYS.sync,
      onSelect: () => void sync(),
    },
    "separator",
    { label: "搜索", icon: "search", shortcut: KEYS.search, onSelect: () => searchRef.current?.focus() },
    { label: "刷新列表", onSelect: () => void reload() },
  ];

  // 快捷键：只在文献库挂载时生效；对话框或菜单打开时让给它们。
  // 处理函数每次渲染都换成最新的，监听只注册一次。
  const onKey = useRef<(e: KeyboardEvent) => void>(() => {});
  onKey.current = (e) => {
    if (e.defaultPrevented || isMenuOpen() || document.querySelector("dialog[open]")) return;
    const mod = e.ctrlKey || e.metaKey;
    const target = e.target instanceof Element ? e.target : null;
    const inSearch = target === searchRef.current;
    const inField = !!target?.closest(TEXT_FIELD);
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const handled = () => e.preventDefault();

    if (mod && key === "f") {
      handled();
      searchRef.current?.focus();
      searchRef.current?.select();
      return;
    }
    if (mod && key === "o") {
      handled();
      void importPdf();
      return;
    }
    if (key === "F5") {
      handled(); // 同时挡住 WebView 的刷新页面
      void sync();
      return;
    }
    if (key === "Escape") {
      if (inSearch && query) {
        handled();
        setQuery("");
      } else if (inSearch) {
        searchRef.current?.blur();
      } else if (selectedId) {
        (document.activeElement as HTMLElement | null)?.blur();
        setSelectedId(null);
      }
      return;
    }
    if (inField) {
      // 搜索框里按 ↓ 进入列表
      if (inSearch && key === "ArrowDown" && items.length) {
        handled();
        focusItem(items[0].id);
      }
      return;
    }
    if (key === "/" && !mod) {
      handled();
      searchRef.current?.focus();
      return;
    }
    if (!items.length) return;
    const i = items.findIndex((x) => x.id === selectedId);
    const current = i >= 0 ? items[i] : undefined;
    const moveTo = (to: number) => {
      handled();
      focusItem(items[Math.max(0, Math.min(items.length - 1, to))].id);
    };
    switch (key) {
      case "ArrowDown":
        return moveTo(i < 0 ? 0 : i + 1);
      case "ArrowUp":
        return moveTo(i < 0 ? 0 : i - 1);
      case "Home":
        return moveTo(0);
      case "End":
        return moveTo(items.length - 1);
      case "PageDown":
        return moveTo(i + 10);
      case "PageUp":
        return moveTo(i - 10);
      case "Enter":
        // 焦点在按钮上时由按钮自己的点击处理，避免打开两次
        if (current && !(target instanceof HTMLButtonElement)) {
          handled();
          open(current);
        }
        return;
      case "Delete":
        if (current) {
          handled();
          setRemoving(current);
        }
        return;
      case "c":
        if (mod && current && !window.getSelection()?.toString()) {
          handled();
          void copy(current.title, "标题");
        }
        return;
    }
  };
  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKey.current(e);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  const collection = collections.find((c) => c.id === selected);
  const scope = collection ? collection.name : "全部文献";

  return (
    <div
      className="page library"
      onContextMenu={(e) => {
        // 条目已经弹了自己的菜单；文本框、选中的文字交给全局的编辑 / 复制菜单
        if (e.defaultPrevented || (e.target as Element).closest(TEXT_FIELD)) return;
        if (window.getSelection()?.toString().trim()) return;
        e.preventDefault();
        openMenu(e.clientX, e.clientY, listMenu());
      }}
    >
      <header className="page-head">
        <div>
          <h1 className="display serif">文献库</h1>
          <p className="page-sub">
            {scope} · {total} 篇
          </p>
        </div>
        <div className="page-actions">
          <Button icon="upload" onClick={importPdf} title={`导入 PDF（${KEYS.import}）`}>
            导入 PDF
          </Button>
          <Button variant="primary" icon="sync" onClick={sync} title={KEYS.sync}>
            {zoteroKey ? "同步此分类" : "从 Zotero 同步"}
          </Button>
        </div>
      </header>
      <div className="library-tools">
        <label className="field search">
          <Icon name="search" />
          <input
            ref={searchRef}
            type="search"
            value={query}
            placeholder={`搜索标题或作者（${KEYS.search}）`}
            aria-label="搜索文献"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <span className="library-sort">按添加时间排序</span>
      </div>
      <section className="items" aria-label="文献列表" aria-busy={loading}>
        {loading && <Progress className="items-loading" />}
        {items.length > 0 && (
          <ItemList
            items={items}
            onOpen={open}
            selectedId={selectedId}
            onSelect={(it) => setSelectedId(it.id)}
            onMenu={(it, x, y) => openMenu(x, y, itemMenu(it))}
          />
        )}
        {!items.length && !loading && (
          <div className="empty">
            {debounced ? "没有匹配的文献" : "还没有文献。从 Zotero 同步，或导入本地 PDF。"}
          </div>
        )}
        {items.length < total && (
          <div className="load-more">
            <Button variant="ghost" onClick={() => load(items.length)}>
              加载更多
            </Button>
          </div>
        )}
      </section>
      <Dialog
        open={removing !== null}
        headline="移除文献"
        onClose={(v) => {
          const item = removing;
          setRemoving(null);
          if (v === "ok" && item) void remove(item);
        }}
        actions={[
          { value: "cancel", label: "取消" },
          { value: "ok", label: "移除", primary: true },
        ]}
      >
        <p>从文献库移除「{removing?.title}」？PDF 文件、译文和批注都会保留，重新导入同一 PDF 即可恢复。</p>
        {removing?.zotero_key && <p>这是 Zotero 条目，下次从 Zotero 同步时会重新出现；要彻底删除请在 Zotero 中删除。</p>}
      </Dialog>
      <ReparseDialog open={reparseDoc !== null} docId={reparseDoc ?? ""} onClose={() => setReparseDoc(null)} />
    </div>
  );
}
