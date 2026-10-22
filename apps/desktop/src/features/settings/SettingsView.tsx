import { useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { type Settings, useApp } from "../../app/store";
import { ACCENT_PRESETS } from "../../app/theme";
import { Button, IconButton, Progress, Segmented, Select, Switch, TextField } from "../../components/ui";
import { GlossaryPanel } from "../translate/GlossaryPanel";
import { useGlossary } from "../translate/useGlossary";
import {
  installEngine,
  REMOTE_ENGINES,
  type RemoteEngine,
  saveParserKey,
  saveProviderKey,
  testParser,
  testProvider,
  useEngines,
} from "./actions";
import { engineOptionLabel, RemoteParserCard, urlHost } from "./parsers";
import { Group, More, Row } from "./Row";
import { SETTINGS_SECTIONS } from "./sections";
import { ZoteroSection } from "./ZoteroSection";

export { engineOptionLabel, urlHost } from "./parsers";

type Provider = Schemas["ProviderConfig"];
type RemoteParser = Schemas["RemoteParser"];

const LANGS = [
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁体中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
];

const sectionTitle = (id: (typeof SETTINGS_SECTIONS)[number]["id"]) => SETTINGS_SECTIONS.find((s) => s.id === id)!.label;

export function SettingsView() {
  const settings = useApp((s) => s.settings);
  const save = useApp((s) => s.saveSettings);
  const toast = useApp((s) => s.toast);
  const { engines, installJobs, refresh: refreshEngines } = useEngines();
  const [keys, setKeys] = useState<Record<string, boolean>>({});
  const page = useRef<HTMLDivElement>(null);

  const refreshKeys = async () => {
    const list = unwrap(await api().GET("/llm/providers"));
    setKeys(Object.fromEntries(list.map((p) => [p.id, p.has_key])));
  };

  useEffect(() => {
    void refreshKeys();
  }, []);

  // 侧栏锚点高亮：取标题已滚到页面顶部附近的最后一节。滚到底时最后几节到不了顶部，
  // 这时保留侧栏点过的那一节（只要它在可见范围内）；用户自己滚动后取消
  const hasSettings = Boolean(settings);
  useEffect(() => {
    const root = page.current;
    if (!root) return;
    const onScroll = () => {
      const box = root.getBoundingClientRect();
      const tops = SETTINGS_SECTIONS.map((s) => ({
        id: s.id,
        y: (document.getElementById(s.id)?.getBoundingClientRect().top ?? Infinity) - box.top,
      }));
      const { settingsSection, settingsPinned } = useApp.getState();
      const atBottom = root.scrollTop + root.clientHeight >= root.scrollHeight - 2;
      const pin = tops.find((t) => t.id === settingsPinned);
      let current: string = SETTINGS_SECTIONS[0].id;
      for (const t of tops) if (t.y <= 120) current = t.id;
      if (atBottom && pin && pin.y >= 0 && pin.y < box.height) current = pin.id;
      if (current !== settingsSection) useApp.setState({ settingsSection: current });
    };
    const unpin = () => useApp.setState({ settingsPinned: null });
    root.addEventListener("scroll", onScroll, { passive: true });
    root.addEventListener("wheel", unpin, { passive: true });
    root.addEventListener("keydown", unpin);
    return () => {
      root.removeEventListener("scroll", onScroll);
      root.removeEventListener("wheel", unpin);
      root.removeEventListener("keydown", unpin);
      useApp.setState({ settingsSection: null, settingsPinned: null });
    };
  }, [hasSettings]);

  if (!settings) return null;

  const update = async (patch: Partial<Settings>) => {
    try {
      await save({ ...settings, ...patch });
    } catch (e) {
      toast(`保存失败：${e}`);
    }
  };
  const appearance = (patch: Partial<Settings["appearance"]>) =>
    update({ appearance: { ...settings.appearance, ...patch } });

  const updateProvider = (i: number, patch: Partial<Provider>) => {
    const providers = settings.providers.map((p, j) => (j === i ? { ...p, ...patch } : p));
    return update({ providers });
  };

  const addProvider = () => {
    let n = settings.providers.length + 1;
    while (settings.providers.some((p) => p.id === `provider${n}`)) n++;
    const p: Provider = {
      id: `provider${n}`,
      kind: "openai_compatible",
      name: "OpenAI 兼容服务",
      base_url: "https://api.openai.com/v1",
      max_concurrency: 4,
    };
    const routes = settings.routes.translate
      ? settings.routes
      : { ...settings.routes, translate: { provider_id: p.id, model: "gpt-4o-mini" } };
    return update({ providers: [...settings.providers, p], routes });
  };

  const removeProvider = async (id: string) => {
    const routes = Object.fromEntries(
      Object.entries(settings.routes).filter(([, r]) => r.provider_id !== id),
    );
    await update({
      providers: settings.providers.filter((p) => p.id !== id),
      routes,
      consented_providers: settings.consented_providers.filter((c) => c !== id),
    });
    await setKey(id, null);
  };

  const setKey = async (id: string, key: string | null) => {
    if (await saveProviderKey(id, key)) await refreshKeys().catch(() => {});
  };

  const test = (id: string) =>
    testProvider(id, settings.routes.translate?.provider_id === id ? settings.routes.translate.model : null);

  const updateParser = (engine: RemoteEngine, patch: Partial<RemoteParser>) =>
    update({ parsers: { ...settings.parsers, [engine]: { ...settings.parsers[engine], ...patch } } });

  const setParserKey = async (engine: RemoteEngine, key: string | null) => {
    if (await saveParserKey(engine, key)) await refreshEngines();
  };

  const route = settings.routes.translate;
  const summaryRoute = settings.routes.summarize;
  const qaRoute = settings.routes.qa;
  const kgRoute = settings.routes.kg_extract;
  const accent = settings.appearance.seed_color.toUpperCase();
  const isPreset = ACCENT_PRESETS.some((s) => s.color.toUpperCase() === accent);
  const providerOptions = settings.providers.map((p) => ({ value: p.id, label: p.name }));

  return (
    <div className="page settings" ref={page}>
      <div className="settings-col">
        <h1 className="display serif">设置</h1>
        <p className="page-sub">
          所有设置只保存在这台电脑上。
          <Button variant="ghost" small className="settings-welcome" onClick={() => void update({ onboarding_done: false })}>
            重新打开欢迎向导
          </Button>
        </p>

        <Group id="providers" title={sectionTitle("providers")}>
          <p className="set-hint">
            支持 OpenAI 兼容接口（OpenAI、DeepSeek、通义、Moonshot、vLLM 等）。API Key 保存在系统钥匙串，不写入设置文件。
          </p>
          {settings.providers.map((p, i) => (
            <ProviderCard
              key={p.id}
              provider={p}
              defaultOpen={i === 0}
              hasKey={Boolean(keys[p.id])}
              onChange={(patch) => updateProvider(i, patch)}
              onKey={(k) => setKey(p.id, k)}
              onTest={() => test(p.id)}
              onRemove={() => removeProvider(p.id)}
            />
          ))}
          <Button small icon="add" className="add-provider" onClick={addProvider}>
            添加服务
          </Button>
        </Group>

        <Group id="ai" title={sectionTitle("ai")}>
          <Row title="目标语言">
            <Select
              label="目标语言"
              hideLabel
              value={settings.target_lang}
              options={LANGS}
              onValue={(target_lang) => update({ target_lang })}
            />
          </Row>
          <Row title="翻译使用的服务">
            <Select
              label="翻译使用的服务"
              hideLabel
              value={route?.provider_id ?? ""}
              options={[{ value: "", label: "未配置" }, ...providerOptions]}
              onValue={(provider_id) =>
                update({
                  routes: provider_id
                    ? { ...settings.routes, translate: { provider_id, model: route?.model ?? "" } }
                    : Object.fromEntries(Object.entries(settings.routes).filter(([k]) => k !== "translate")),
                })
              }
            />
            {route && (
              <TextField
                label="翻译模型"
                hideLabel
                mono
                className="model-inp"
                placeholder="模型"
                value={route.model}
                commitOnChange
                onValue={(model) => update({ routes: { ...settings.routes, translate: { ...route, model } } })}
              />
            )}
          </Row>
          <More
            label="按任务指定服务、自动抽取图谱"
            defaultOpen={Boolean(summaryRoute || qaRoute || kgRoute || settings.kg.auto)}
          >
            <Row title="总结使用的服务" desc="总结要读全文并归纳，推荐用推理能力更强的模型">
              <Select
                label="总结使用的服务"
                hideLabel
                value={summaryRoute?.provider_id ?? ""}
                options={[{ value: "", label: "与翻译相同" }, ...providerOptions]}
                onValue={(provider_id) =>
                  update({
                    routes: provider_id
                      ? {
                          ...settings.routes,
                          summarize: { provider_id, model: summaryRoute?.model || route?.model || "" },
                        }
                      : Object.fromEntries(Object.entries(settings.routes).filter(([k]) => k !== "summarize")),
                  })
                }
              />
              {summaryRoute && (
                <TextField
                  label="总结模型"
                  hideLabel
                  mono
                  className="model-inp"
                  placeholder="模型"
                  value={summaryRoute.model}
                  commitOnChange
                  onValue={(model) => update({ routes: { ...settings.routes, summarize: { ...summaryRoute, model } } })}
                />
              )}
            </Row>
            <Row title="问答使用的服务" desc="回答只依据检索到的原文，并标出出处">
              <Select
                label="问答使用的服务"
                hideLabel
                value={qaRoute?.provider_id ?? ""}
                options={[{ value: "", label: "与总结相同" }, ...providerOptions]}
                onValue={(provider_id) =>
                  update({
                    routes: provider_id
                      ? {
                          ...settings.routes,
                          qa: { provider_id, model: qaRoute?.model || summaryRoute?.model || route?.model || "" },
                        }
                      : Object.fromEntries(Object.entries(settings.routes).filter(([k]) => k !== "qa")),
                  })
                }
              />
              {qaRoute && (
                <TextField
                  label="问答模型"
                  hideLabel
                  mono
                  className="model-inp"
                  placeholder="模型"
                  value={qaRoute.model}
                  commitOnChange
                  onValue={(model) => update({ routes: { ...settings.routes, qa: { ...qaRoute, model } } })}
                />
              )}
            </Row>
            <Row title="图谱抽取使用的服务" desc="按章节找出方法、数据集、指标等实体和关系，每篇调用次数与章节数相当">
              <Select
                label="图谱抽取使用的服务"
                hideLabel
                value={kgRoute?.provider_id ?? ""}
                options={[{ value: "", label: "与总结相同" }, ...providerOptions]}
                onValue={(provider_id) =>
                  update({
                    routes: provider_id
                      ? {
                          ...settings.routes,
                          kg_extract: { provider_id, model: kgRoute?.model || summaryRoute?.model || route?.model || "" },
                        }
                      : Object.fromEntries(Object.entries(settings.routes).filter(([k]) => k !== "kg_extract")),
                  })
                }
              />
              {kgRoute && (
                <TextField
                  label="图谱抽取模型"
                  hideLabel
                  mono
                  className="model-inp"
                  placeholder="模型"
                  value={kgRoute.model}
                  commitOnChange
                  onValue={(model) => update({ routes: { ...settings.routes, kg_extract: { ...kgRoute, model } } })}
                />
              )}
            </Row>
            <Row
              title="建立语义索引后自动抽取图谱"
              desc="新导入的文献嵌入完成后自动排队抽取（会调用大模型）；关闭时在阅读器的图谱面板里手动抽取"
              htmlFor="kg-auto"
            >
              <Switch
                id="kg-auto"
                label="建立语义索引后自动抽取图谱"
                checked={settings.kg.auto}
                onValue={(auto) => update({ kg: { ...settings.kg, auto } })}
              />
            </Row>
          </More>
        </Group>

        <Group id="parse" title={sectionTitle("parse")}>
          <Row title="高质量解析引擎" desc="导入后先用快速模式秒级出可读版本，再在后台用高质量引擎升级">
            <Select
              label="高质量解析引擎"
              hideLabel
              value={settings.parse_engine}
              options={[
                { value: "auto", label: "自动（MinerU 可用时升级）" },
                { value: "pymupdf", label: "只用快速模式" },
                ...engines
                  .filter((e) => e.heavy)
                  .map((e) => ({
                    value: e.name as Settings["parse_engine"],
                    label: engineOptionLabel(e),
                    disabled: !e.available,
                  })),
              ]}
              onValue={(parse_engine) => update({ parse_engine })}
            />
          </Row>
          <p className="set-hint">
            MinerU 和 Docling 可以在本机运行，也可以调用自部署或云端服务：MinerU 支持 mineru-api 与
            mineru.net，Docling 支持 docling-serve。局域网地址无需确认；公网地址要先允许上传 PDF。
          </p>
          {REMOTE_ENGINES.map((name) => {
            const info = engines.find((e) => e.name === name);
            return (
              <RemoteParserCard
                key={name}
                engine={name}
                label={info?.label ?? name}
                cfg={settings.parsers[name]}
                info={info}
                installJob={installJobs[name]}
                onInstall={() => installEngine(name)}
                pypiMirror={settings.pypi_mirror}
                onPypiMirror={(pypi_mirror) => update({ pypi_mirror })}
                onChange={(patch) => updateParser(name, patch)}
                onKey={(k) => setParserKey(name, k)}
                onTest={() => testParser(name)}
              />
            );
          })}
          <More defaultOpen={settings.parse_device !== "auto"}>
            <Row title="解析设备" desc="只影响在本机运行的 MinerU 和 Docling。GPU 需要 NVIDIA 显卡；改动从下一次解析开始生效">
              <Segmented
                label="解析设备"
                value={settings.parse_device}
                options={[
                  { value: "auto", label: "自动" },
                  { value: "gpu", label: "GPU" },
                  { value: "cpu", label: "CPU" },
                ]}
                onValue={(parse_device) => update({ parse_device })}
              />
            </Row>
          </More>
        </Group>

        <ZoteroSection settings={settings} update={update} Group={Group} Row={Row} title={sectionTitle("zotero")} />

        <EmbeddingSection settings={settings} update={update} />

        <GlossarySection settings={settings} update={update} />

        <Group id="appearance" title={sectionTitle("appearance")}>
          <Row title="深浅色">
            <Segmented
              label="深浅色"
              value={settings.appearance.theme_mode}
              options={[
                { value: "system", label: "跟随系统" },
                { value: "light", label: "浅色" },
                { value: "dark", label: "深色" },
              ]}
              onValue={(theme_mode) => appearance({ theme_mode })}
            />
          </Row>
          <Row title="强调色" desc="只用在选中项、引用标记和定位高亮上">
            <div className="swatches" role="group" aria-label="强调色">
              {ACCENT_PRESETS.map((s) => (
                <button
                  key={s.color}
                  type="button"
                  className="sw"
                  aria-pressed={accent === s.color.toUpperCase()}
                  onClick={() => appearance({ seed_color: s.color })}
                >
                  <i style={{ background: s.color }} />
                  {s.name}
                </button>
              ))}
              <label className="sw" data-on={!isPreset || undefined} title="自定义强调色">
                <i className={isPreset ? "sw-custom" : undefined} style={isPreset ? undefined : { background: accent }} />
                自定义
                <input
                  type="color"
                  className="sr-only"
                  aria-label="自定义强调色"
                  value={accent.toLowerCase()}
                  onChange={(e) => appearance({ seed_color: e.target.value.toUpperCase() })}
                />
              </label>
            </div>
          </Row>
          <Row title="对比度">
            <Segmented
              label="对比度"
              value={settings.appearance.contrast}
              options={[
                { value: "standard", label: "标准" },
                { value: "medium", label: "中" },
                { value: "high", label: "高" },
              ]}
              onValue={(contrast) => appearance({ contrast })}
            />
          </Row>
        </Group>

        <Group id="privacy" title={sectionTitle("privacy")}>
          {REMOTE_ENGINES.filter((n) => settings.parsers[n].consented_url).map((n) => (
            <Row
              key={n}
              title={`已允许把 PDF 上传到 ${urlHost(settings.parsers[n].consented_url!)}`}
              desc={`用于 ${engines.find((e) => e.name === n)?.label ?? n} 解析`}
            >
              <Button small onClick={() => updateParser(n, { consented_url: null })}>
                撤销
              </Button>
            </Row>
          ))}
          {settings.consented_providers.length ? (
            settings.consented_providers.map((id) => (
              <Row
                key={id}
                title={`已允许向 ${settings.providers.find((p) => p.id === id)?.name ?? id} 发送文档内容`}
                desc="用于翻译、总结和问答"
              >
                <Button
                  small
                  onClick={() => update({ consented_providers: settings.consented_providers.filter((c) => c !== id) })}
                >
                  撤销
                </Button>
              </Row>
            ))
          ) : (
            <Row title="还没有向任何服务发送过文档内容" desc="第一次翻译、总结或问答前会先询问你" />
          )}
        </Group>
      </div>
    </div>
  );
}

const KIND_LABEL: Record<NonNullable<Provider["kind"]>, string> = {
  openai_compatible: "OpenAI 兼容",
  anthropic: "Anthropic（兼容端点）",
  ollama: "Ollama（本地）",
};

interface ProviderCardProps {
  provider: Provider;
  defaultOpen: boolean;
  hasKey: boolean;
  onChange: (patch: Partial<Provider>) => void;
  onKey: (key: string | null) => void;
  onTest: () => Promise<boolean | null>;
  onRemove: () => void;
}

function ProviderCard({ provider, defaultOpen, hasKey, onChange, onKey, onTest, onRemove }: ProviderCardProps) {
  const [key, setKey] = useState("");
  const [open, setOpen] = useState(defaultOpen);
  const [tested, setTested] = useState<boolean | null>(null);
  const kind = provider.kind ?? "openai_compatible";
  return (
    <div className="card provider">
      <div className="provider-head">
        <b>{provider.name}</b>
        {tested === true && (
          <span className="state ok">
            <i />
            连接正常
          </span>
        )}
        {tested === false && (
          <span className="state err">
            <i />
            连接失败
          </span>
        )}
        {!open && (
          <span className="provider-sum">
            {KIND_LABEL[kind]} · <span className="mono">{provider.base_url}</span>
          </span>
        )}
        <span className="provider-actions">
          {open && (
            <Button variant="ghost" small onClick={async () => setTested(await onTest())}>
              测试连接
            </Button>
          )}
          {open && <IconButton icon="delete" label="删除服务" className="danger" onClick={onRemove} />}
          <Button variant="ghost" small aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? "收起" : "展开"}
          </Button>
        </span>
      </div>
      {open && (
        <>
          <div className="grid">
            <TextField label="名称" value={provider.name} commitOnChange onValue={(name) => onChange({ name })} />
            <Select
              label="类型"
              value={kind}
              options={(Object.keys(KIND_LABEL) as (keyof typeof KIND_LABEL)[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))}
              onValue={(kind) => onChange({ kind })}
            />
            <TextField
              label="Base URL"
              mono
              value={provider.base_url}
              commitOnChange
              onValue={(base_url) => onChange({ base_url })}
            />
            <TextField
              label={hasKey ? "API Key（已保存，输入新值可替换）" : "API Key"}
              type="password"
              mono
              value={key}
              onValue={setKey}
            />
            <TextField
              label="最大并发"
              type="number"
              value={String(provider.max_concurrency)}
              hint="同时进行的请求数（1–32），所有任务共享；遇到限流（429）时调小"
              commitOnChange
              onValue={(v) => {
                const n = Math.round(Number(v));
                if (Number.isFinite(n) && n > 0) onChange({ max_concurrency: Math.min(32, n) });
              }}
            />
          </div>
          <div className="provider-keys">
            <Button
              variant="primary"
              small
              disabled={!key}
              onClick={() => {
                onKey(key);
                setKey("");
              }}
            >
              保存 Key
            </Button>
            {hasKey && (
              <Button small onClick={() => onKey(null)}>
                删除 Key
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

type Embedding = Settings["embedding"];

function EmbeddingSection({
  settings,
  update,
}: {
  settings: Settings;
  update: (patch: Partial<Settings>) => Promise<void>;
}) {
  const toast = useApp((s) => s.toast);
  const jobs = useApp((s) => s.jobs);
  const [status, setStatus] = useState<Schemas["EmbeddingStatus"] | null>(null);
  const embedding: Embedding = settings.embedding ?? {
    source: "local",
    local_model: "multilingual-e5-small",
    auto: true,
    mirror: "https://huggingface.co",
  };
  const route = settings.routes.embed;

  const download = Object.values(jobs).find(
    (j) => j.kind === "model_download" && (j.status === "queued" || j.status === "running"),
  );
  const embedJobs = Object.values(jobs).filter(
    (j) => j.kind === "embed" && (j.status === "queued" || j.status === "running"),
  ).length;
  // 下载 / 嵌入任务的进展会改变状态：任务数或下载进度变化时刷新
  const jobKey = `${download?.status}:${Math.round((download?.progress ?? 0) * 20)}:${embedJobs}`;

  useEffect(() => {
    void api()
      .GET("/embedding/status")
      .then((r) => setStatus(unwrap(r)))
      .catch(() => {});
  }, [settings, jobKey]);

  const set = (patch: Partial<Embedding>) => update({ embedding: { ...embedding, ...patch } });

  const startDownload = async () => {
    try {
      unwrap(await api().POST("/embedding/download"));
    } catch (e) {
      toast(`无法开始下载：${e}`);
    }
  };

  const rebuild = async () => {
    try {
      const ids = unwrap(await api().POST("/embedding/rebuild"));
      toast(`已重新排队 ${ids.length} 篇文档`);
    } catch (e) {
      toast(`重建失败：${e}`);
    }
  };

  const mb = (n: number) => `${Math.round(n / (1 << 20))} MB`;
  const providerName = settings.providers.find((p) => p.id === route?.provider_id)?.name;

  return (
    <Group id="search" title={sectionTitle("search")}>
      <p className="set-hint">
        为论文建立语义索引后，阅读器里的搜索（Ctrl+F）可以按意思找段落，总结和问答也会用到它。关键词搜索不需要索引。
      </p>
      <Row title="嵌入模型来源">
        <Select
          label="嵌入模型来源"
          hideLabel
          value={embedding.source}
          options={[
            { value: "local", label: "内置本地模型（推荐，不上传内容）" },
            { value: "provider", label: "大模型服务" },
          ]}
          onValue={(source) => set({ source })}
        />
      </Row>

      {embedding.source === "local" ? (
        <Row
          title={status?.local_label ?? embedding.local_model}
          desc={
            <>
              {status && `约 ${mb(status.size_bytes)}，`}
              {download
                ? `下载中 ${Math.round(download.progress * 100)}%`
                : status?.downloaded
                  ? "已就绪"
                  : "未下载"}
              {download && <Progress value={download.progress} className="row-bar" />}
            </>
          }
        >
          {!status?.downloaded && (
            <Button small disabled={Boolean(download)} onClick={startDownload}>
              下载模型
            </Button>
          )}
        </Row>
      ) : (
        <>
          <Row title="嵌入使用的服务">
            <Select
              label="嵌入使用的服务"
              hideLabel
              value={route?.provider_id ?? ""}
              options={[
                { value: "", label: "未配置" },
                ...settings.providers.map((p) => ({ value: p.id, label: p.name })),
              ]}
              onValue={(provider_id) =>
                update({
                  routes: provider_id
                    ? { ...settings.routes, embed: { provider_id, model: route?.model ?? "text-embedding-3-small" } }
                    : Object.fromEntries(Object.entries(settings.routes).filter(([k]) => k !== "embed")),
                })
              }
            />
            {route && (
              <TextField
                label="嵌入模型"
                hideLabel
                mono
                className="model-inp"
                placeholder="嵌入模型"
                value={route.model}
                commitOnChange
                onValue={(model) => update({ routes: { ...settings.routes, embed: { ...route, model } } })}
              />
            )}
          </Row>
          {status?.not_ready === "consent_required" && route && (
            <Row title="需要你的允许" desc={`建立索引需要把论文段落发送给 ${providerName ?? route.provider_id}。`}>
              <Button
                small
                onClick={() => update({ consented_providers: [...settings.consented_providers, route.provider_id] })}
              >
                允许
              </Button>
            </Row>
          )}
          {status?.not_ready === "missing_api_key" && <p className="set-hint">这个服务还没有保存 API Key。</p>}
        </>
      )}

      {status && (
        <Row
          title="索引"
          desc={`已建立索引 ${status.docs_embedded} / ${status.docs_total} 篇${embedJobs > 0 ? `，${embedJobs} 篇排队中` : ""}`}
        >
          <Button small disabled={!status.ready} onClick={rebuild}>
            重建索引
          </Button>
        </Row>
      )}

      <More defaultOpen={!embedding.auto || embedding.mirror !== "https://huggingface.co"}>
        <Row title="解析后自动建立索引" htmlFor="embed-auto">
          <Switch id="embed-auto" label="解析后自动建立索引" checked={embedding.auto} onValue={(auto) => set({ auto })} />
        </Row>
        {embedding.source === "local" && (
          <Row title="下载源" desc="Hugging Face 访问慢时可改为镜像，如 https://hf-mirror.com">
            <TextField
              label="下载源"
              hideLabel
              mono
              value={embedding.mirror}
              commitOnChange
              onValue={(mirror) => set({ mirror })}
            />
          </Row>
        )}
      </More>
    </Group>
  );
}

/** 术语表：翻译全文前自动抽取的开关 + 全局术语（对所有文档生效）。 */
function GlossarySection({ settings, update }: { settings: Settings; update: (p: Partial<Settings>) => Promise<void> }) {
  const glossary = useGlossary(null, settings.target_lang, true);
  return (
    <Group id="glossary" title={sectionTitle("glossary")}>
      <Row
        title="翻译全文前自动抽取术语"
        desc="文档还没有术语时，先让模型从论文中抽取一次（多一次模型调用），之后的译法更统一"
        htmlFor="glossary-auto"
      >
        <Switch
          id="glossary-auto"
          label="翻译全文前自动抽取术语"
          checked={settings.glossary.auto_extract}
          onValue={(auto_extract) => update({ glossary: { ...settings.glossary, auto_extract } })}
        />
      </Row>
      <p className="set-hint">全局术语对所有文档生效；文档里的同名术语优先。翻译时只会带上段落里出现的术语。</p>
      <GlossaryPanel state={glossary} globalOnly />
    </Group>
  );
}
