// 欢迎向导的纯逻辑：服务类型预设、把向导里填的服务写进设置。

import type { Schemas } from "../../api/client";
import type { Settings } from "../../app/store";

type Provider = Schemas["ProviderConfig"];
export type ProviderKind = NonNullable<Provider["kind"]>;

export interface ProviderDraft {
  kind: ProviderKind;
  name: string;
  base_url: string;
  model: string;
}

interface Preset extends ProviderDraft {
  label: string;
  /** 本机服务不需要 API Key */
  needsKey: boolean;
}

export const PROVIDER_PRESETS: Record<ProviderKind, Preset> = {
  openai_compatible: {
    kind: "openai_compatible",
    label: "OpenAI 兼容",
    name: "OpenAI 兼容服务",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    needsKey: true,
  },
  anthropic: {
    kind: "anthropic",
    label: "Anthropic",
    name: "Anthropic",
    base_url: "https://api.anthropic.com/v1",
    model: "claude-sonnet-5-5",
    needsKey: true,
  },
  ollama: {
    kind: "ollama",
    label: "Ollama（本地）",
    name: "Ollama",
    base_url: "http://127.0.0.1:11434/v1",
    model: "qwen3",
    needsKey: false,
  },
};

export function providerPreset(kind: ProviderKind): ProviderDraft {
  const { label: _l, needsKey: _k, ...draft } = PROVIDER_PRESETS[kind];
  return draft;
}

/** 已有服务时的初始表单：取翻译用的那个（没有就取第一个）。 */
export function draftFromSettings(settings: Settings): { id: string | null; draft: ProviderDraft } {
  const route = settings.routes.translate;
  const p = settings.providers.find((x) => x.id === route?.provider_id) ?? settings.providers[0];
  if (!p) return { id: null, draft: providerPreset("openai_compatible") };
  const kind = p.kind ?? "openai_compatible";
  const model = route?.provider_id === p.id ? route.model : providerPreset(kind).model;
  return { id: p.id, draft: { kind, name: p.name, base_url: p.base_url, model } };
}

/**
 * 把向导里的服务写进设置：id 已存在时就地更新，否则按 provider{n} 新建。
 * 翻译没配置或正用这个服务时，把翻译路由指向它（总结、问答、图谱默认跟随翻译）。
 */
export function applyWelcomeProvider(
  settings: Settings,
  draft: ProviderDraft,
  id: string | null,
): { settings: Settings; id: string } {
  const fields = { kind: draft.kind, name: draft.name.trim() || PROVIDER_PRESETS[draft.kind].name, base_url: draft.base_url.trim() };
  let providers: Provider[];
  if (id && settings.providers.some((p) => p.id === id)) {
    providers = settings.providers.map((p) => (p.id === id ? { ...p, ...fields } : p));
  } else {
    let n = settings.providers.length + 1;
    while (settings.providers.some((p) => p.id === `provider${n}`)) n++;
    id = `provider${n}`;
    providers = [...settings.providers, { id, max_concurrency: 4, ...fields }];
  }
  const route = settings.routes.translate;
  const routes =
    !route || route.provider_id === id
      ? { ...settings.routes, translate: { provider_id: id, model: draft.model.trim() } }
      : settings.routes;
  return { settings: { ...settings, providers, routes }, id };
}
