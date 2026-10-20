import { type ReactNode, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { isTauri } from "../../api/core";
import { type Settings, useApp } from "../../app/store";
import { ACCENT_PRESETS } from "../../app/theme";
import { Button, IconButton, Progress, Segmented, Select, Switch, TextField } from "../../components/ui";
import { GlossaryPanel } from "../translate/GlossaryPanel";
import { useGlossary } from "../translate/useGlossary";
import { SETTINGS_SECTIONS } from "./sections";
import { ZoteroSection } from "./ZoteroSection";

type Provider = Schemas["ProviderConfig"];
type Engine = Schemas["EngineOut"];
type RemoteEngine = "mineru" | "docling";
type RemoteParser = Schemas["RemoteParser"];
type Job = Schemas["JobOut"];

const REMOTE_ENGINES: RemoteEngine[] = ["mineru", "docling"];

const UNAVAILABLE_LABEL: Record<string, string> = {
  not_installed: "未安装",
  not_configured: "未填写服务地址",
  consent_required: "待确认上传",
};

/** 引擎下拉里的名称：API 模式加注，不可用时写明原因。 */
export function engineOptionLabel(e: Engine): string {
  const name = e.location === "api" ? `${e.label}（API）` : e.label;
  if (e.available) return name;
  return `${name}（${UNAVAILABLE_LABEL[e.unavailable_reason ?? ""] ?? "不可用"}）`;
}

/** 地址的主机名，用于隐私确认文案；解析失败时原样返回。 */
export function urlHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

const LANGS = [
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁体中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
];

/** 设置项一行：左边标题与说明，右边控件。 */
function Row({ title, desc, htmlFor, children }: { title: ReactNode; desc?: ReactNode; htmlFor?: string; children?: ReactNode }) {
  const k = (
    <>
      <b>{title}</b>
      {desc && <span>{desc}</span>}
    </>
  );
  return (
    <div className="set-row">
      {htmlFor ? (
        <label className="k" htmlFor={htmlFor}>
          {k}
        </label>
      ) : (
        <div className="k">{k}</div>
      )}
      {children && <div className="v">{children}</div>}
    </div>
  );
}

function Group({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="set-group" id={id} aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="serif">
        {title}
      </h2>
      {children}
    </section>
  );
}

const sectionTitle = (id: (typeof SETTINGS_SECTIONS)[number]["id"]) => SETTINGS_SECTIONS.find((s) => s.id === id)!.label;

export function SettingsView() {
  const settings = useApp((s) => s.settings);
  const save = useApp((s) => s.saveSettings);
  const toast = useApp((s) => s.toast);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [keys, setKeys] = useState<Record<string, boolean>>({});
  const jobs = useApp((s) => s.jobs);
  const page = useRef<HTMLDivElement>(null);

  // 每个引擎最近一次本机安装任务（进行中或已结束）
  const installJobs: Partial<Record<RemoteEngine, Job>> = {};
  for (const j of Object.values(jobs)) {
    const name = j.payload.engine as RemoteEngine;
    if (j.kind !== "engine_install") continue;
    const prev = installJobs[name];
    if (!prev || j.created_at > prev.created_at) installJobs[name] = j;
  }
  const installKey = REMOTE_ENGINES.map((n) => installJobs[n]?.status).join(":");

  const refreshKeys = async () => {
    const list = unwrap(await api().GET("/llm/providers"));
    setKeys(Object.fromEntries(list.map((p) => [p.id, p.has_key])));
  };

  const refreshEngines = () =>
    api()
      .GET("/parsers")
      .then((r) => setEngines(unwrap(r)))
      .catch(() => {});

  useEffect(() => {
    void refreshKeys();
  }, []);

  // 引擎可用性取决于设置（运行位置、地址、上传确认），设置变化后重新获取
  // 安装任务结束后可用性也会变
  useEffect(() => {
    void refreshEngines();
  }, [settings, installKey]);

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
    try {
      if (isTauri()) {
        const { invoke } = await import("@tauri-apps/api/core");
        if (key) await invoke("set_api_key", { providerId: id, key });
        else await invoke("delete_api_key", { providerId: id });
      }
      const path = { params: { path: { provider_id: id } } } as const;
      if (key) await api().PUT("/llm/providers/{provider_id}/key", { ...path, body: { key } });
      else await api().DELETE("/llm/providers/{provider_id}/key", path);
      await refreshKeys();
      if (key) toast(isTauri() ? "API Key 已保存到系统钥匙串" : "API Key 已设置（浏览器开发模式下只在本次运行有效）");
    } catch (e) {
      toast(`保存 API Key 失败：${e}`);
    }
  };

  const test = async (id: string): Promise<boolean | null> => {
    const model = settings.routes.translate?.provider_id === id ? settings.routes.translate.model : null;
    try {
      const r = unwrap(
        await api().POST("/llm/providers/{provider_id}/test", {
          params: { path: { provider_id: id } },
          body: { model },
        }),
      );
      toast(r.ok ? `连接正常（${r.model}，${r.latency_ms} ms）` : `连接失败：${r.error}`);
      return r.ok;
    } catch (e) {
      toast(`测试失败：${e}`);
      return null;
    }
  };

  const updateParser = (engine: RemoteEngine, patch: Partial<RemoteParser>) =>
    update({ parsers: { ...settings.parsers, [engine]: { ...settings.parsers[engine], ...patch } } });

  const setParserKey = async (engine: RemoteEngine, key: string | null) => {
    try {
      if (isTauri()) {
        const { invoke } = await import("@tauri-apps/api/core");
        if (key) await invoke("set_api_key", { providerId: `parser-${engine}`, key });
        else await invoke("delete_api_key", { providerId: `parser-${engine}` });
      }
      const path = { params: { path: { engine } } } as const;
      if (key) await api().PUT("/parsers/{engine}/key", { ...path, body: { key } });
      else await api().DELETE("/parsers/{engine}/key", path);
      await refreshEngines();
      if (key) toast(isTauri() ? "API Key 已保存到系统钥匙串" : "API Key 已设置（浏览器开发模式下只在本次运行有效）");
    } catch (e) {
      toast(`保存 API Key 失败：${e}`);
    }
  };

  const installEngine = async (engine: RemoteEngine) => {
    try {
      unwrap(await api().POST("/parsers/{engine}/install", { params: { path: { engine } } }));
    } catch (e) {
      toast(`无法开始安装：${e}`);
    }
  };

  const testParser = async (engine: RemoteEngine): Promise<boolean | null> => {
    try {
      const r = unwrap(await api().POST("/parsers/{engine}/test", { params: { path: { engine } } }));
      toast(r.ok ? `连接正常（${r.version ?? "版本未知"}，${r.latency_ms} ms）` : `连接失败：${r.error}`);
      return r.ok;
    } catch (e) {
      toast(`测试失败：${e}`);
      return null;
    }
  };

  const route = settings.routes.translate;
  const summaryRoute = settings.routes.summarize;
  const qaRoute = settings.routes.qa;
  const accent = settings.appearance.seed_color.toUpperCase();
  const isPreset = ACCENT_PRESETS.some((s) => s.color.toUpperCase() === accent);
  const providerOptions = settings.providers.map((p) => ({ value: p.id, label: p.name }));

  return (
    <div className="page settings" ref={page}>
      <div className="settings-col">
        <h1 className="display serif">设置</h1>
        <p className="page-sub">所有设置只保存在这台电脑上。</p>

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
        </Group>

        <GlossarySection settings={settings} update={update} />

        <EmbeddingSection settings={settings} update={update} />

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

        <ZoteroSection settings={settings} update={update} Group={Group} Row={Row} title={sectionTitle("zotero")} />

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
                onChange={(patch) => updateParser(name, patch)}
                onKey={(k) => setParserKey(name, k)}
                onTest={() => testParser(name)}
              />
            );
          })}
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

const TIERS: { value: RemoteParser["tier"]; label: string }[] = [
  { value: "flash", label: "flash（最快）" },
  { value: "basic", label: "basic（与本机相同，推荐）" },
  { value: "standard", label: "standard（VLM，更准）" },
  { value: "advanced", label: "advanced（最准，最慢）" },
];

const URL_PLACEHOLDER: Record<RemoteEngine, string> = {
  mineru: "https://mineru.net/api 或 http://127.0.0.1:8000",
  docling: "http://127.0.0.1:5001",
};

interface RemoteParserCardProps {
  engine: RemoteEngine;
  label: string;
  cfg: RemoteParser;
  info: Engine | undefined;
  installJob: Job | undefined;
  onInstall: () => void;
  onChange: (patch: Partial<RemoteParser>) => void;
  onKey: (key: string | null) => void;
  onTest: () => Promise<boolean | null>;
}

function RemoteParserCard({
  engine,
  label,
  cfg,
  info,
  installJob,
  onInstall,
  onChange,
  onKey,
  onTest,
}: RemoteParserCardProps) {
  const [key, setKey] = useState("");
  const [tested, setTested] = useState<boolean | null>(null);
  const isApi = cfg.mode === "api";
  return (
    <div className="card provider">
      <div className="provider-head">
        <b>{label}</b>
        {isApi && tested === true && (
          <span className="state ok">
            <i />
            连接正常
          </span>
        )}
        {isApi && tested === false && (
          <span className="state err">
            <i />
            连接失败
          </span>
        )}
        <span className="provider-actions">
          {isApi && (
            <Button variant="ghost" small disabled={!cfg.base_url} onClick={async () => setTested(await onTest())}>
              测试连接
            </Button>
          )}
          <Segmented
            label={`${label} 运行位置`}
            value={cfg.mode}
            options={[
              { value: "local", label: "本机" },
              { value: "api", label: "API 服务" },
            ]}
            onValue={(mode) => onChange({ mode })}
          />
        </span>
      </div>
      {isApi && (
        <>
          <div className="grid">
            <TextField
              label="Base URL"
              mono
              placeholder={URL_PLACEHOLDER[engine]}
              value={cfg.base_url}
              commitOnChange
              onValue={(base_url) => {
                setTested(null);
                onChange({ base_url: base_url.trim() });
              }}
            />
            {engine === "mineru" && (
              <Select label="质量档位（tier）" value={cfg.tier} options={TIERS} onValue={(tier) => onChange({ tier })} />
            )}
            <TextField
              label={info?.has_key ? "API Key（已保存，输入新值可替换）" : "API Key（本机服务通常不需要）"}
              type="password"
              mono
              value={key}
              onValue={setKey}
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
            {info?.has_key && (
              <Button small onClick={() => onKey(null)}>
                删除 Key
              </Button>
            )}
          </div>
          {info?.unavailable_reason === "consent_required" && (
            <Row
              title="需要你的允许"
              desc={`使用这个服务时，PDF 原文会上传到 ${urlHost(cfg.base_url)}。允许后才会用它解析。`}
            >
              <Button small onClick={() => onChange({ consented_url: cfg.base_url })}>
                允许上传
              </Button>
            </Row>
          )}
        </>
      )}
      {!isApi && <LocalInstall label={label} info={info} job={installJob} onInstall={onInstall} />}
    </div>
  );
}

/** 本机模式：未安装时提供安装，安装中显示进度，失败时显示原因并可重试。 */
function LocalInstall({
  label,
  info,
  job,
  onInstall,
}: {
  label: string;
  info: Engine | undefined;
  job: Job | undefined;
  onInstall: () => void;
}) {
  const active = job && (job.status === "queued" || job.status === "running");
  if (active) {
    return (
      <Row
        title={`正在安装 ${label}… ${Math.round(job.progress * 100)}%`}
        desc={
          <>
            <span className="install-msg">{job.message ?? "排队中"}</span>
            <Progress value={job.progress} className="row-bar" />
          </>
        }
      />
    );
  }
  if (info?.unavailable_reason !== "not_installed") return null;
  const failed = job?.status === "failed";
  return (
    <Row
      title={failed ? "安装失败" : `本机未安装 ${label}`}
      desc={
        failed ? (
          <span className="install-err">{job.error}</span>
        ) : (
          <>
            安装会下载 Python 3.12、PyTorch 与 {label}（共数 GB）到独立环境，首次解析时还会下载模型。也可以改用 API 服务。
          </>
        )
      }
    >
      <Button small variant={failed ? undefined : "primary"} onClick={onInstall}>
        {failed ? "重试安装" : "安装"}
      </Button>
    </Row>
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
      <Row title="解析后自动建立索引" htmlFor="embed-auto">
        <Switch id="embed-auto" label="解析后自动建立索引" checked={embedding.auto} onValue={(auto) => set({ auto })} />
      </Row>

      {embedding.source === "local" ? (
        <>
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
        </>
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
