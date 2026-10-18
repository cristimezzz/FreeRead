import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, rawFetch, unwrap } from "../../api/client";
import type { Anchor, Block, Document } from "../../api/ir";
import { type DocumentStatus, useApp } from "../../app/store";
import { Icon } from "../../components/icons";
import { Dialog, Segmented } from "../../components/md";
import { useTranslations } from "../translate/useTranslations";
import { blockAt, buildPageIndex, primaryAnchor } from "./locate";
import { PdfView } from "./PdfView";
import { ReflowView, type TranslationMode } from "./ReflowView";

type Layout = "pdf" | "split" | "reflow";

const PREFS_KEY = "freeread.reader";

interface Prefs {
  layout: Layout;
  mode: TranslationMode;
  fontSize: number;
}

function loadPrefs(): Prefs {
  try {
    return { layout: "split", mode: "alternate", fontSize: 17, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return { layout: "split", mode: "alternate", fontSize: 17 };
  }
}

const ENGINE_LABEL: Record<string, string> = { pymupdf: "快速模式", mineru: "MinerU", docling: "Docling" };

export function ReaderView({ docId, title }: { docId: string; itemId: string; title: string }) {
  const [status, setStatus] = useState<DocumentStatus | null>(null);
  const [doc, setDoc] = useState<Document | null>(null);
  const [irVersion, setIrVersion] = useState(0);
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [located, setLocated] = useState<string | null>(null);
  const [pdfHighlight, setPdfHighlight] = useState<Anchor | null>(null);
  const [pdfScroll, setPdfScroll] = useState(0);
  const [reflowScroll, setReflowScroll] = useState(0);
  const firstVisible = useRef<string | null>(null);
  const prevDoc = useRef<Document | null>(null);
  const version = useApp((s) => s.documentVersion[docId] ?? 0);
  const settings = useApp((s) => s.settings);
  const toast = useApp((s) => s.toast);
  const jobs = useApp((s) => s.jobs);
  const navigate = useApp((s) => s.navigate);

  const setPref = <K extends keyof Prefs>(k: K, v: Prefs[K]) =>
    setPrefs((p) => {
      const next = { ...p, [k]: v };
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(next));
      } catch {
        // 无痕模式等情况下 localStorage 不可用，偏好只在本次有效
      }
      return next;
    });

  // 文档状态与 IR；document 事件（解析完成 / 升级）时重新拉取
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let s: DocumentStatus;
      try {
        s = unwrap(await api().GET("/documents/{doc_id}", { params: { path: { doc_id: docId } } }));
      } catch (e) {
        if (!cancelled) toast(`加载文档失败：${e}`);
        return;
      }
      if (cancelled) return;
      setStatus(s);
      if (s.parse_status !== "ready") return;
      try {
        const ir = (await (await rawFetch(`/documents/${docId}/ir`)).json()) as Document;
        if (cancelled) return;
        prevDoc.current = doc;
        setDoc(ir);
        setIrVersion((v) => v + 1);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) toast(`加载 IR 失败：${e}`);
      }
    })();
    return () => {
      cancelled = true;
    };
    // doc 只用于记录升级前的版本，不作为依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId, version, toast]);

  const index = useMemo(() => (doc ? buildPageIndex(doc.blocks) : new Map()), [doc]);
  const byId = useMemo(() => new Map(doc?.blocks.map((b) => [b.id, b]) ?? []), [doc]);

  // IR 升级（快速模式 → MinerU）后保持阅读位置：按旧块的坐标在新 IR 里找对应块
  useEffect(() => {
    const old = prevDoc.current;
    if (!doc || !old || !firstVisible.current) return;
    const anchor = primaryAnchor(old.blocks.find((b) => b.id === firstVisible.current));
    if (!anchor) return;
    const [x0, y0, x1, y1] = anchor.bbox;
    const id = blockAt(index, anchor.page, (x0 + x1) / 2, (y0 + y1) / 2, 40);
    if (id) {
      setLocated(id);
      setReflowScroll((k) => k + 1);
    }
    if (old.parser.engine !== doc.parser.engine) {
      toast(`已升级为 ${ENGINE_LABEL[doc.parser.engine] ?? doc.parser.engine} 解析结果`);
    }
  }, [irVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  const lang = settings?.target_lang ?? "zh-CN";
  const translationOn = prefs.mode !== "off" && prefs.layout !== "pdf";
  const { states, requestVisible, consent, acceptConsent, declineConsent } = useTranslations(
    doc,
    translationOn,
    lang,
    irVersion,
  );

  const onVisible = useCallback(
    (ids: string[]) => {
      firstVisible.current = ids[0] ?? null;
      requestVisible(ids);
    },
    [requestVisible],
  );

  const onLocateBlock = useCallback((b: Block) => {
    setLocated(b.id);
    setPdfHighlight(primaryAnchor(b));
    setPdfScroll((k) => k + 1);
  }, []);

  const onPoint = useCallback(
    (page: number, x: number, y: number) => {
      const id = blockAt(index, page, x, y);
      if (!id) return;
      setLocated(id);
      setPdfHighlight(primaryAnchor(byId.get(id)));
      setReflowScroll((k) => k + 1);
    },
    [index, byId],
  );

  const onPdfError = useCallback((m: string) => toast(m), [toast]);

  const parsing = Object.values(jobs).find(
    (j) => (j.kind === "parse" || j.kind === "parse_hq") && j.payload.doc_id === docId && (j.status === "running" || j.status === "queued"),
  );
  const ready = status?.parse_status === "ready" && doc;
  const layout: Layout = ready ? prefs.layout : "pdf";

  return (
    <>
      <header className="top-bar">
        <md-icon-button aria-label="返回文献库" onClick={() => navigate({ name: "library" })}>
          <Icon name="back" />
        </md-icon-button>
        <h1 title={title}>{doc?.meta.title || title}</h1>
      </header>
      <div className="reader-toolbar">
        <Segmented
          label="视图"
          value={layout}
          options={[
            { value: "pdf", label: "原版" },
            { value: "split", label: "并排" },
            { value: "reflow", label: "重排" },
          ]}
          onValue={(v) => (ready ? setPref("layout", v) : toast("解析完成后才能使用重排视图"))}
        />
        {layout !== "pdf" && (
          <Segmented
            label="翻译"
            value={prefs.mode}
            options={[
              { value: "off", label: "原文" },
              { value: "side", label: "对照" },
              { value: "alternate", label: "交替" },
              { value: "only", label: "仅译文" },
            ]}
            onValue={(v) => setPref("mode", v)}
          />
        )}
        {layout !== "pdf" && (
          <label className="reader-status">
            字号
            <md-slider
              min={14}
              max={24}
              step={1}
              value={prefs.fontSize}
              labeled
              ref={(el: (HTMLElement & { value: number }) | null) => {
                if (el && !el.dataset.bound) {
                  el.dataset.bound = "1";
                  el.addEventListener("change", () => setPref("fontSize", Number(el.value)));
                }
              }}
            />
          </label>
        )}
        <span style={{ flex: 1 }} />
        <span className="reader-status">
          {parsing && <md-circular-progress indeterminate style={{ "--md-circular-progress-size": "20px" } as React.CSSProperties} />}
          {parsing
            ? parsing.kind === "parse_hq"
              ? "正在用高质量引擎升级…"
              : "正在解析…"
            : status?.parse_status === "failed"
              ? "解析失败，只能阅读原版"
              : doc
                ? `${ENGINE_LABEL[doc.parser.engine] ?? doc.parser.engine} · ${doc.blocks.length} 块`
                : ""}
        </span>
      </div>
      <div className="reader">
        {layout !== "reflow" && (
          <PdfView docId={docId} highlight={pdfHighlight} scrollKey={pdfScroll} onPoint={onPoint} onError={onPdfError} />
        )}
        {layout !== "pdf" && doc && (
          <ReflowView
            doc={doc}
            mode={prefs.mode}
            translations={states}
            located={located}
            scrollKey={reflowScroll}
            fontSize={prefs.fontSize}
            onLocate={onLocateBlock}
            onVisible={onVisible}
          />
        )}
      </div>
      <Dialog
        open={Boolean(consent)}
        headline="发送文档内容进行翻译？"
        onClose={(v) => (v === "ok" ? void acceptConsent() : declineConsent())}
        actions={[
          { value: "cancel", label: "暂不" },
          { value: "ok", label: "允许", primary: true },
        ]}
      >
        <p>
          翻译需要把论文段落发送给
          {settings?.providers.find((p) => p.id === consent?.providerId)?.name ?? consent?.providerId}。
          文档的其余数据都保存在本机。之后可以在 设置 › 隐私 中撤销。
        </p>
      </Dialog>
    </>
  );
}
