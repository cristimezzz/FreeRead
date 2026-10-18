import { useEffect, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { isTauri } from "../../api/core";
import { type Settings, useApp } from "../../app/store";
import { PRESET_SEEDS } from "../../app/theme";
import { Icon } from "../../components/icons";
import { Segmented, Select, TextField } from "../../components/md";

type Provider = Schemas["ProviderConfig"];

const LANGS = [
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁体中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
];

export function SettingsView() {
  const settings = useApp((s) => s.settings);
  const save = useApp((s) => s.saveSettings);
  const toast = useApp((s) => s.toast);
  const [engines, setEngines] = useState<Schemas["EngineOut"][]>([]);
  const [keys, setKeys] = useState<Record<string, boolean>>({});

  const refreshKeys = async () => {
    const list = unwrap(await api().GET("/llm/providers"));
    setKeys(Object.fromEntries(list.map((p) => [p.id, p.has_key])));
  };

  useEffect(() => {
    void api()
      .GET("/parsers")
      .then((r) => setEngines(unwrap(r)));
    void refreshKeys();
  }, []);

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

  const test = async (id: string) => {
    const model = settings.routes.translate?.provider_id === id ? settings.routes.translate.model : null;
    try {
      const r = unwrap(
        await api().POST("/llm/providers/{provider_id}/test", {
          params: { path: { provider_id: id } },
          body: { model },
        }),
      );
      toast(r.ok ? `连接正常（${r.model}，${r.latency_ms} ms）` : `连接失败：${r.error}`);
    } catch (e) {
      toast(`测试失败：${e}`);
    }
  };

  const route = settings.routes.translate;

  return (
    <>
      <header className="top-bar">
        <h1>设置</h1>
      </header>
      <div className="settings">
        <section aria-labelledby="s-appearance">
          <h2 id="s-appearance">外观</h2>
          <div className="row">
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
          </div>
          <div className="row">
            <div className="swatches" role="group" aria-label="主题色">
              {PRESET_SEEDS.map((s) => (
                <button
                  key={s.color}
                  className="swatch"
                  title={s.name}
                  aria-label={s.name}
                  aria-pressed={settings.appearance.seed_color.toUpperCase() === s.color.toUpperCase()}
                  style={{ background: s.color }}
                  onClick={() => appearance({ seed_color: s.color })}
                />
              ))}
            </div>
            <label className="switch-row">
              自定义
              <input
                type="color"
                value={settings.appearance.seed_color}
                onChange={(e) => appearance({ seed_color: e.target.value.toUpperCase() })}
              />
            </label>
          </div>
          <div className="row">
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
          </div>
        </section>

        <section aria-labelledby="s-translate">
          <h2 id="s-translate">翻译</h2>
          <div className="row">
            <Select
              label="目标语言"
              value={settings.target_lang}
              options={LANGS}
              onValue={(target_lang) => update({ target_lang })}
            />
            <Select
              label="翻译使用的服务"
              value={route?.provider_id ?? ""}
              options={[
                { value: "", label: "未配置" },
                ...settings.providers.map((p) => ({ value: p.id, label: p.name })),
              ]}
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
                label="模型"
                value={route.model}
                commitOnChange
                onValue={(model) => update({ routes: { ...settings.routes, translate: { ...route, model } } })}
              />
            )}
          </div>
        </section>

        <section aria-labelledby="s-llm">
          <h2 id="s-llm">大模型服务</h2>
          <p className="hint">支持 OpenAI 兼容接口（OpenAI、DeepSeek、通义、Moonshot、vLLM 等）。API Key 保存在系统钥匙串，不写入设置文件。</p>
          {settings.providers.map((p, i) => (
            <ProviderCard
              key={p.id}
              provider={p}
              hasKey={Boolean(keys[p.id])}
              onChange={(patch) => updateProvider(i, patch)}
              onKey={(k) => setKey(p.id, k)}
              onTest={() => test(p.id)}
              onRemove={() => removeProvider(p.id)}
            />
          ))}
          <md-outlined-button onClick={addProvider}>
            <span slot="icon">
              <Icon name="add" size={18} />
            </span>
            添加服务
          </md-outlined-button>
        </section>

        <section aria-labelledby="s-parse">
          <h2 id="s-parse">解析</h2>
          <div className="row">
            <Select
              label="高质量解析引擎"
              value={settings.parse_engine}
              options={[
                { value: "auto", label: "自动（MinerU 可用时升级）" },
                { value: "pymupdf", label: "只用快速模式" },
                ...engines
                  .filter((e) => e.heavy)
                  .map((e) => ({
                    value: e.name as Settings["parse_engine"],
                    label: e.available ? e.label : `${e.label}（未安装）`,
                    disabled: !e.available,
                  })),
              ]}
              onValue={(parse_engine) => update({ parse_engine })}
            />
          </div>
          <p className="hint">导入后先用快速模式秒级出可读版本，再在后台用高质量引擎升级。</p>
        </section>

        <section aria-labelledby="s-privacy">
          <h2 id="s-privacy">隐私</h2>
          {settings.consented_providers.length ? (
            settings.consented_providers.map((id) => (
              <div className="row" key={id}>
                <span>已允许向 {settings.providers.find((p) => p.id === id)?.name ?? id} 发送文档内容</span>
                <md-text-button
                  onClick={() =>
                    update({ consented_providers: settings.consented_providers.filter((c) => c !== id) })
                  }
                >
                  撤销
                </md-text-button>
              </div>
            ))
          ) : (
            <p className="hint">还没有向任何服务发送过文档内容。第一次翻译前会先询问你。</p>
          )}
        </section>
      </div>
    </>
  );
}

interface ProviderCardProps {
  provider: Provider;
  hasKey: boolean;
  onChange: (patch: Partial<Provider>) => void;
  onKey: (key: string | null) => void;
  onTest: () => void;
  onRemove: () => void;
}

function ProviderCard({ provider, hasKey, onChange, onKey, onTest, onRemove }: ProviderCardProps) {
  const [key, setKey] = useState("");
  return (
    <div className="provider">
      <TextField label="名称" value={provider.name} commitOnChange onValue={(name) => onChange({ name })} />
      <Select
        label="类型"
        value={provider.kind ?? "openai_compatible"}
        options={[
          { value: "openai_compatible", label: "OpenAI 兼容" },
          { value: "anthropic", label: "Anthropic（兼容端点）" },
          { value: "ollama", label: "Ollama（本地）" },
        ]}
        onValue={(kind) => onChange({ kind })}
      />
      <TextField
        label="Base URL"
        value={provider.base_url}
        commitOnChange
        onValue={(base_url) => onChange({ base_url })}
      />
      <TextField
        label={hasKey ? "API Key（已保存，输入新值可替换）" : "API Key"}
        type="password"
        value={key}
        onValue={setKey}
      />
      <div className="actions">
        <md-filled-tonal-button
          disabled={!key || undefined}
          onClick={() => {
            onKey(key);
            setKey("");
          }}
        >
          保存 Key
        </md-filled-tonal-button>
        {hasKey && <md-text-button onClick={() => onKey(null)}>删除 Key</md-text-button>}
        <md-text-button onClick={onTest}>测试连接</md-text-button>
        <span style={{ flex: 1 }} />
        <md-icon-button aria-label="删除服务" onClick={onRemove}>
          <Icon name="delete" />
        </md-icon-button>
      </div>
    </div>
  );
}
