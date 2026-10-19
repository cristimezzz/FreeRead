import { useCallback, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { isTauri } from "../../api/core";
import { useApp } from "../../app/store";
import { Icon } from "../../components/icons";
import { Button, Progress } from "../../components/ui";
import { formatAuthors, ItemList } from "./ItemList";

type Item = Schemas["ItemOut"];
const PAGE = 100;
const MAX_PAGE = 500; // 服务端单页上限

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
  useEffect(() => {
    if (seenVersion.current === libraryVersion) return;
    seenVersion.current = libraryVersion;
    void load(0, Math.min(MAX_PAGE, Math.max(PAGE, loaded.current)));
  }, [libraryVersion, load]);

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
    const byline = [formatAuthors(item.authors), item.year, item.venue].filter(Boolean).join(" · ");
    navigate({ name: "reader", docId: doc.doc_id, itemId: item.id, title: item.title, byline });
  };

  const collection = collections.find((c) => c.id === selected);
  const scope = collection ? collection.name : "全部文献";

  return (
    <div className="page library">
      <header className="page-head">
        <div>
          <h1 className="display serif">文献库</h1>
          <p className="page-sub">
            {scope} · {total} 篇
          </p>
        </div>
        <div className="page-actions">
          <Button icon="upload" onClick={importPdf}>
            导入 PDF
          </Button>
          <Button variant="primary" icon="sync" onClick={sync}>
            {zoteroKey ? "同步此分类" : "从 Zotero 同步"}
          </Button>
        </div>
      </header>
      <div className="library-tools">
        <label className="field search">
          <Icon name="search" />
          <input
            type="search"
            value={query}
            placeholder="搜索标题或作者"
            aria-label="搜索文献"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <span className="library-sort">按添加时间排序</span>
      </div>
      <section className="items" aria-label="文献列表" aria-busy={loading}>
        {loading && <Progress className="items-loading" />}
        {items.length > 0 && <ItemList items={items} onOpen={open} />}
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
    </div>
  );
}
