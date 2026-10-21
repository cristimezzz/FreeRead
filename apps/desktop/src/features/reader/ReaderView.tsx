import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, rawFetch, unwrap } from "../../api/client";
import { type Anchor, type Block, type Document, PLACEHOLDER_RE } from "../../api/ir";
import { type DocumentStatus, useApp } from "../../app/store";
import { usePresence } from "../../components/motion";
import { Resizer } from "../../components/Resizer";
import { Button, Dialog, IconButton, Segmented, Spinner } from "../../components/ui";
import { useTranslations } from "../translate/useTranslations";
import { GlossaryPanel } from "../translate/GlossaryPanel";
import { useGlossary } from "../translate/useGlossary";
import { KgPanel } from "../kg/KgPanel";
import { useKg } from "../kg/useKg";
import { blockAt, buildPageIndex, primaryAnchor } from "./locate";
import { type PdfMark, PdfView } from "./PdfView";
import { AnnotationsPanel } from "../annotations/AnnotationsPanel";
import { ExportDialog } from "../annotations/ExportDialog";
import { type Annotation, type AnnotationColor, useAnnotations } from "../annotations/useAnnotations";
import { ReflowView, type TranslationMode } from "./ReflowView";
import { SearchPanel } from "./SearchPanel";
import { SummaryPanel } from "../summary/SummaryPanel";
import { useSummary } from "../summary/useSummary";
import { QaPanel } from "../qa/QaPanel";
import { ReparseDialog } from "./ReparseDialog";
import { useQa } from "../qa/useQa";

type Layout = "pdf" | "split" | "reflow";

const PREFS_KEY = "freeread.reader";

interface Prefs {
  layout: Layout;
  mode: TranslationMode;
  fontSize: number;
  /** 右侧面板（搜索 / 总结 / 问答）宽度，px */
  panelWidth: number;
  /** 并排视图里原版所占比例 */
  split: number;
}

const DEFAULT_PREFS: Prefs = { layout: "split", mode: "alternate", fontSize: 17, panelWidth: 420, split: 0.5 };
const PANEL_MIN = 320;
const PANE_MIN = 240;

function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

/** 观察元素宽度（分隔条的上下限要按当前宽度算）。 */
function useWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

/** 引用悬停提示：正文取 text，表格取单元格文本，图取说明。 */
function blockPreview(b: Block | undefined): string | undefined {
  if (!b) return undefined;
  if (b.text.trim()) return b.text;
  if (b.html) return new DOMParser().parseFromString(b.html, "text/html").body.textContent ?? undefined;
  return b.latex ?? undefined;
}

const ENGINE_LABEL: Record<string, string> = { pymupdf: "快速模式", mineru: "MinerU", docling: "Docling" };

export function ReaderView({ docId, title, byline }: { docId: string; itemId: string; title: string; byline?: string }) {
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
  const loadedParse = useRef<string | null>(null);
  // 右侧面板：文内搜索、总结、问答、术语表共用一个位置
  type Side = "search" | "summary" | "qa" | "glossary" | "kg" | "notes";
  const [side, setSide] = useState<Side | null>(null);
  const toggleSide = (panel: Side) => setSide((cur) => (cur === panel ? null : panel));
  // 关闭时保留最后一个面板播放退出动画
  const lastSide = useRef(side);
  if (side) lastSide.current = side;
  const readerEl = useRef<HTMLDivElement>(null);
  const panesEl = useRef<HTMLDivElement>(null);
  const readerW = useWidth(readerEl);
  const panesW = useWidth(panesEl);
  const version = useApp((s) => s.documentVersion[docId] ?? 0);
  const settings = useApp((s) => s.settings);
  const toast = useApp((s) => s.toast);
  const jobs = useApp((s) => s.jobs);
  const [reparseOpen, setReparseOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [focusAnn, setFocusAnn] = useState<string | null>(null);
  // 本文最近一次完成的解析任务：用同一引擎重新解析时引擎和版本号都不变，靠它触发重新拉 IR
  const parsedAt = Object.values(jobs).reduce(
    (m, j) =>
      (j.kind === "parse" || j.kind === "parse_hq") && j.payload.doc_id === docId && j.status === "done" && (j.finished_at ?? "") > m
        ? (j.finished_at ?? "")
        : m,
    "",
  );
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
      // 只有解析结果变了才重新拉 IR；嵌入状态之类的变化也会发 document 事件
      const parseKey = [s.parser_engine, s.parser_version, s.normalizer_version, parsedAt].join("|");
      if (parseKey === loadedParse.current) return;
      try {
        // 重新解析后 IR 原地替换：不用 HTTP 缓存（旧版本 Core 的响应没有 Cache-Control，会被启发式缓存）
        const ir = (await (await rawFetch(`/documents/${docId}/ir`, { cache: "no-cache" })).json()) as Document;
        if (cancelled) return;
        prevDoc.current = doc;
        loadedParse.current = parseKey;
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
  }, [docId, version, parsedAt, toast]);

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
  // 本文最近的整篇翻译任务：进度变化时把新译文合并进来
  const docJob = Object.values(jobs)
    .filter((j) => j.kind === "translate_doc" && j.payload.doc_id === docId && j.payload.lang === lang)
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const translatingAll = docJob?.status === "queued" || docJob?.status === "running";
  const translation = useTranslations(
    doc,
    translationOn,
    lang,
    irVersion,
    docJob && docJob.status !== "queued" ? `${docJob.id}:${docJob.progress}:${docJob.status}` : "",
  );

  const { states, requestVisible } = translation;
  const summary = useSummary(docId, lang, side === "summary");
  // 两个功能都可能先问隐私确认：同一时间只会有一个在等
  const qa = useQa(docId, lang, side === "qa");
  const glossary = useGlossary(docId, lang, side === "glossary");
  const kg = useKg(docId, side === "kg");
  // 图谱云图展开后铺满阅读区（覆盖原版 / 重排），离开图谱面板时收起
  const [kgExpanded, setKgExpanded] = useState(false);
  const [kgStage, setKgStage] = useState<HTMLDivElement | null>(null);
  const showKgStage = side === "kg" && kgExpanded;
  useEffect(() => {
    if (side !== "kg") setKgExpanded(false);
  }, [side]);
  // 问答树同样可以展开铺满阅读区
  const [qaExpanded, setQaExpanded] = useState(false);
  const [qaStage, setQaStage] = useState<HTMLDivElement | null>(null);
  const showQaStage = side === "qa" && qaExpanded;
  useEffect(() => {
    if (side !== "qa") setQaExpanded(false);
  }, [side]);
  const ann = useAnnotations(docId, irVersion);
  const wholeMarks = useMemo(
    () => Object.fromEntries(Object.entries(ann.wholeBlocks).map(([id, a]) => [id, a.color])),
    [ann.wholeBlocks],
  );
  const pdfMarks = useMemo<PdfMark[]>(
    () =>
      ann.items
        .filter((a) => a.status === "ok")
        .flatMap((a) => (byId.get(a.block_id)?.anchors ?? []).map((an) => ({ ...an, color: a.color }))),
    [ann.items, byId],
  );
  const onAnnotate = useCallback(
    async (sel: { blockId: string; start: number; end: number }, color: AnnotationColor, note: boolean) => {
      const a = await ann.create(sel.blockId, sel.start, sel.end, color);
      if (a && note) {
        setFocusAnn(a.id);
        setSide("notes");
      }
    },
    [ann],
  );
  const onMarkClick = useCallback((id: string) => {
    setFocusAnn(id);
    setSide("notes");
  }, []);
  const quoteText = useCallback(
    (a: Annotation) => {
      const inlines = byId.get(a.block_id)?.inlines ?? [];
      return a.quote.replace(PLACEHOLDER_RE, (_, key: string) => {
        const latex = inlines.find((i) => i.key === key)?.latex;
        return latex ? `$${latex}$` : "";
      });
    },
    [byId],
  );
  // 翻译、总结、问答、术语抽取、图谱抽取都可能先问隐私确认：取第一个在等的
  const asking = [
    { label: "翻译", ...translation },
    { label: "总结", ...summary },
    { label: "问答", ...qa },
    { label: "术语抽取", ...glossary },
    { label: "图谱抽取", ...kg },
  ].find((f) => f.consent);
  const consentFor = asking?.label ?? null;
  const consent = asking?.consent ?? null;
  const acceptConsent = () => asking?.acceptConsent();
  const declineConsent = () => asking?.declineConsent();

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

  const jumpTo = useCallback(
    (id: string) => {
      setLocated(id);
      setPdfHighlight(primaryAnchor(byId.get(id)));
      setPdfScroll((k) => k + 1);
      setReflowScroll((k) => k + 1);
    },
    [byId],
  );

  // Ctrl+F / ⌘F 打开文内搜索
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setSide("search");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const parsing = Object.values(jobs).find(
    (j) => (j.kind === "parse" || j.kind === "parse_hq") && j.payload.doc_id === docId && (j.status === "running" || j.status === "queued"),
  );
  const ready = status?.parse_status === "ready" && doc;
  const layout: Layout = ready ? prefs.layout : "pdf";

  const panel = usePresence(side !== null);
  const shownSide = side ?? lastSide.current;
  // 面板最宽占阅读区 60%；窗口变窄时自动收回到上限内
  const panelMax = Math.max(PANEL_MIN, Math.round(readerW * 0.6));
  const panelW = Math.min(panelMax, Math.max(PANEL_MIN, prefs.panelWidth));
  const splitW = panesW
    ? Math.round(Math.min(Math.max(PANE_MIN, panesW - PANE_MIN), Math.max(PANE_MIN, prefs.split * panesW)))
    : 0;

  const parsingEngine = parsing?.payload.engine as string | undefined;
  const statusText = parsing
    ? parsing.payload.force && parsingEngine
      ? `正在用 ${ENGINE_LABEL[parsingEngine] ?? parsingEngine} 重新解析…`
      : parsing.kind === "parse_hq"
        ? "正在用高质量引擎升级…"
        : "正在解析…"
    : status?.parse_status === "failed"
      ? "解析失败，只能阅读原版"
      : doc
        ? `${ENGINE_LABEL[doc.parser.engine] ?? doc.parser.engine} · ${doc.blocks.length} 块`
        : "";

  return (
    <div className="page reader-page">
      <header className="reader-top">
        <IconButton icon="back" label="返回文献库" onClick={() => navigate({ name: "library" })} />
        <div className="reader-title">
          <h1 className="serif" title={title}>
            {doc?.meta.title || title}
          </h1>
          {byline && <div className="reader-byline">{byline}</div>}
        </div>
        {statusText && (
          <span className="reader-status" role="status" data-state={parsing ? "busy" : status?.parse_status}>
            {parsing ? <Spinner size={12} /> : <span className="dot" />}
            {statusText}
          </span>
        )}
        {status && (
          <Button
            variant="ghost"
            small
            icon="upload"
            disabled={!ready}
            title="导出总结、批注、正文和译文为 Markdown"
            onClick={() => setExportOpen(true)}
          >
            导出
          </Button>
        )}
        {status && (
          <Button
            variant="ghost"
            small
            icon="sync"
            disabled={Boolean(parsing)}
            title={parsing ? "正在解析，完成后可以重新解析" : "换一个解析引擎重新解析本文"}
            onClick={() => setReparseOpen(true)}
          >
            重新解析
          </Button>
        )}
      </header>
      <ExportDialog
        open={exportOpen}
        docId={docId}
        title={doc?.meta.title || title}
        lang={lang}
        onClose={() => setExportOpen(false)}
      />
      <ReparseDialog
        open={reparseOpen}
        docId={docId}
        current={status?.parser_engine ?? undefined}
        onClose={() => setReparseOpen(false)}
      />
      <div className="reader-toolbar" role="toolbar" aria-label="阅读工具">
        <div className="tool-group">
          <span className="lbl">视图</span>
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
        </div>
        {layout !== "pdf" && (
          <div className="tool-group">
            <span className="lbl">翻译</span>
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
            {ready && (
              <Button
                variant="ghost"
                small
                icon="translate"
                disabled={translatingAll}
                title={
                  translatingAll
                    ? `正在翻译全文${docJob?.message ? `：${docJob.message}` : ""}`
                    : "在后台翻译全文，之后离线也能读"
                }
                onClick={() => void translation.translateAll()}
              >
                {translatingAll
                  ? `翻译中 ${Math.round((docJob?.progress ?? 0) * 100)}%`
                  : "翻译全文"}
              </Button>
            )}
          </div>
        )}
        {layout !== "pdf" && (
          <label className="tool-group">
            <span className="lbl">字号</span>
            <input
              type="range"
              min={14}
              max={24}
              step={1}
              value={prefs.fontSize}
              title={`${prefs.fontSize}px`}
              onChange={(e) => setPref("fontSize", Number(e.target.value))}
            />
          </label>
        )}
        {ready && (
          <div className="tool-actions">
            <Button
              variant="ghost"
              small
              icon="search"
              title="搜索本文（Ctrl+F）"
              pressed={side === "search"}
              onClick={() => toggleSide("search")}
            >
              搜索
            </Button>
            <Button variant="ghost" small icon="summary" pressed={side === "summary"} onClick={() => toggleSide("summary")}>
              总结
            </Button>
            <Button variant="ghost" small icon="qa" pressed={side === "qa"} onClick={() => toggleSide("qa")}>
              问答
            </Button>
            <Button
              variant="ghost"
              small
              icon="glossary"
              pressed={side === "glossary"}
              onClick={() => toggleSide("glossary")}
            >
              术语
            </Button>
            <Button variant="ghost" small icon="graph" pressed={side === "kg"} onClick={() => toggleSide("kg")}>
              图谱
            </Button>
            <Button variant="ghost" small icon="edit" pressed={side === "notes"} onClick={() => toggleSide("notes")}>
              批注{ann.items.length ? ` ${ann.items.length}` : ""}
            </Button>
          </div>
        )}
      </div>
      <div className="reader" ref={readerEl}>
        <div className="reader-panes" ref={panesEl}>
          {showKgStage && <div className="kg-stage" ref={setKgStage} />}
          {showQaStage && <div className="kg-stage" ref={setQaStage} />}
          {layout !== "reflow" && (
            <PdfView
              docId={docId}
              highlight={pdfHighlight}
              marks={pdfMarks}
              scrollKey={pdfScroll}
              onPoint={onPoint}
              onError={onPdfError}
              style={layout === "split" && splitW ? { flex: `0 0 ${splitW}px` } : undefined}
            />
          )}
          {layout === "split" && doc && panesW > 0 && (
            <Resizer
              label="调整原版与重排的宽度"
              value={splitW}
              min={PANE_MIN}
              max={Math.max(PANE_MIN, panesW - PANE_MIN)}
              onValue={(px) => setPref("split", px / panesW)}
              onReset={() => setPref("split", DEFAULT_PREFS.split)}
            />
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
              marks={ann.marks}
              wholeMarks={wholeMarks}
              onAnnotate={onAnnotate}
              onMarkClick={onMarkClick}
            />
          )}
        </div>
        {panel.mounted && ready && (
          <>
            <Resizer
              invert
              label="调整侧边面板宽度"
              value={panelW}
              min={PANEL_MIN}
              max={panelMax}
              onValue={(px) => setPref("panelWidth", px)}
              onReset={() => setPref("panelWidth", DEFAULT_PREFS.panelWidth)}
            />
            <div className="side-slot" data-state={panel.closing ? "closing" : "open"} style={{ width: panelW }}>
              {shownSide === "search" && (
                <SearchPanel
                  docId={docId}
                  embedStatus={status?.embed_status}
                  onPick={jumpTo}
                  onClose={() => setSide(null)}
                />
              )}
              {shownSide === "summary" && (
                <SummaryPanel
                  state={summary}
                  blockText={(id) => blockPreview(byId.get(id))}
                  onPick={jumpTo}
                  onClose={() => setSide(null)}
                />
              )}
              {shownSide === "glossary" && <GlossaryPanel state={glossary} onClose={() => setSide(null)} />}
              {shownSide === "kg" && (
                <KgPanel
                  state={kg}
                  expanded={showKgStage}
                  stage={showKgStage ? kgStage : null}
                  onExpand={setKgExpanded}
                  blockText={(id) => blockPreview(byId.get(id))}
                  onPick={jumpTo}
                  onClose={() => setSide(null)}
                />
              )}
              {shownSide === "notes" && (
                <AnnotationsPanel
                  state={ann}
                  quoteText={quoteText}
                  focusId={focusAnn}
                  onPick={jumpTo}
                  onExport={() => setExportOpen(true)}
                  onClose={() => setSide(null)}
                />
              )}
              {shownSide === "qa" && (
                <QaPanel
                  state={qa}
                  expanded={showQaStage}
                  stage={showQaStage ? qaStage : null}
                  onExpand={setQaExpanded}
                  blockText={(id) => blockPreview(byId.get(id))}
                  onPick={(id) => {
                    setQaExpanded(false);
                    jumpTo(id);
                  }}
                  onClose={() => setSide(null)}
                />
              )}
            </div>
          </>
        )}
      </div>
      <Dialog
        open={Boolean(consent)}
        headline={`发送文档内容进行${consentFor ?? "处理"}？`}
        onClose={(v) => (v === "ok" ? void acceptConsent() : declineConsent())}
        actions={[
          { value: "cancel", label: "暂不" },
          { value: "ok", label: "允许", primary: true },
        ]}
      >
        <p>
          {consentFor}需要把论文段落发送给
          {settings?.providers.find((p) => p.id === consent?.providerId)?.name ?? consent?.providerId}。
          文档的其余数据都保存在本机。之后可以在 设置 › 隐私 中撤销。
        </p>
      </Dialog>
    </div>
  );
}
