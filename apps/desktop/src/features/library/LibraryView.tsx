import { useCallback, useEffect, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { isTauri } from "../../api/core";
import { useApp } from "../../app/store";
import { Icon } from "../../components/icons";
import { TextField } from "../../components/md";
import { CollectionTree } from "./CollectionTree";
import { ItemList } from "./ItemList";

type Item = Schemas["ItemOut"];
const PAGE = 100;

export function LibraryView() {
  const [collections, setCollections] = useState<Schemas["CollectionOut"][]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const libraryVersion = useApp((s) => s.libraryVersion);
  const { navigate, toast, bumpLibrary } = useApp.getState();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    void api()
      .GET("/library/collections")
      .then((r) => setCollections(unwrap(r)));
  }, [libraryVersion]);

  const load = useCallback(
    async (offset: number) => {
      setLoading(true);
      try {
        const page = unwrap(
          await api().GET("/library/items", {
            params: {
              query: {
                collection_id: selected,
                q: debounced || null,
                offset,
                limit: PAGE,
                sort: "added",
              },
            },
          }),
        );
        setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
      } catch (e) {
        toast(`加载文献失败：${e}`);
      } finally {
        setLoading(false);
      }
    },
    [selected, debounced, toast],
  );

  useEffect(() => {
    void load(0);
  }, [load, libraryVersion]);

  const zoteroKey = collections.find((c) => c.id === selected)?.zotero_key ?? null;

  const sync = async () => {
    try {
      unwrap(await api().POST("/library/sync", { body: { collection_key: zoteroKey } }));
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

  const open = (item: Item) => {
    const doc = item.documents.find((d) => d.parse_status === "ready") ?? item.documents[0];
    if (!doc?.doc_id) {
      toast("这个条目没有可用的 PDF 附件");
      return;
    }
    navigate({ name: "reader", docId: doc.doc_id, itemId: item.id, title: item.title });
  };

  return (
    <>
      <header className="top-bar">
        <h1>文献库</h1>
        <md-outlined-button onClick={importPdf}>
          <span slot="icon">
            <Icon name="add" size={18} />
          </span>
          导入 PDF
        </md-outlined-button>
        <md-filled-button onClick={sync}>
          <span slot="icon">
            <Icon name="sync" size={18} />
          </span>
          {zoteroKey ? "同步此分类" : "从 Zotero 同步"}
        </md-filled-button>
      </header>
      <div className="library">
        <CollectionTree collections={collections} selected={selected} onSelect={setSelected} />
        <section className="items" aria-label="文献列表">
          <div className="items-toolbar">
            <TextField className="search" label="搜索标题或作者" value={query} onValue={setQuery} />
            <span className="count">{total} 篇</span>
          </div>
          {loading && <md-linear-progress indeterminate />}
          {items.length > 0 && <ItemList items={items} onOpen={open} />}
          {!items.length && !loading && (
            <div className="empty">
              {debounced ? "没有匹配的文献" : "还没有文献。从 Zotero 同步，或导入本地 PDF。"}
            </div>
          )}
          {items.length < total && (
            <div style={{ padding: 12, textAlign: "center" }}>
              <md-text-button onClick={() => load(items.length)}>加载更多</md-text-button>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
