import { describe, expect, it } from "vitest";
import type { Settings } from "../app/store";
import { applyWelcomeProvider, draftFromSettings, providerPreset } from "../features/welcome/model";

const base = { providers: [], routes: {} } as unknown as Settings;
const deepseek = { id: "provider1", kind: "openai_compatible" as const, name: "DeepSeek", base_url: "https://api.deepseek.com/v1", max_concurrency: 4 };

describe("服务类型预设", () => {
  it("每种类型有默认地址和模型", () => {
    expect(providerPreset("openai_compatible")).toEqual({
      kind: "openai_compatible",
      name: "OpenAI 兼容服务",
      base_url: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
    });
    expect(providerPreset("ollama").base_url).toBe("http://127.0.0.1:11434/v1");
    expect(providerPreset("anthropic").kind).toBe("anthropic");
  });
});

describe("向导写入大模型服务", () => {
  it("没有服务时新建 provider1，并把翻译路由指向它", () => {
    const { settings, id } = applyWelcomeProvider(base, { ...providerPreset("openai_compatible"), name: "  " }, null);
    expect(id).toBe("provider1");
    expect(settings.providers).toEqual([
      { id: "provider1", kind: "openai_compatible", name: "OpenAI 兼容服务", base_url: "https://api.openai.com/v1", max_concurrency: 4 },
    ]);
    expect(settings.routes).toEqual({ translate: { provider_id: "provider1", model: "gpt-4o-mini" } });
  });

  it("再次保存时更新同一个服务，不新增", () => {
    const first = applyWelcomeProvider(base, providerPreset("openai_compatible"), null);
    const again = applyWelcomeProvider(first.settings, { ...providerPreset("ollama"), model: "llama3" }, first.id);
    expect(again.id).toBe("provider1");
    expect(again.settings.providers).toHaveLength(1);
    expect(again.settings.providers[0]).toMatchObject({ kind: "ollama", base_url: "http://127.0.0.1:11434/v1", max_concurrency: 4 });
    expect(again.settings.routes.translate).toEqual({ provider_id: "provider1", model: "llama3" });
  });

  it("翻译已用别的服务时，不改路由；新 id 避开已有的", () => {
    const s = { ...base, providers: [deepseek], routes: { translate: { provider_id: "provider1", model: "deepseek-chat" } } } as Settings;
    const { settings, id } = applyWelcomeProvider(s, providerPreset("anthropic"), null);
    expect(id).toBe("provider2");
    expect(settings.routes).toBe(s.routes);
  });
});

describe("已有服务时的初始表单", () => {
  it("取翻译用的服务和模型", () => {
    const s = { ...base, providers: [deepseek], routes: { translate: { provider_id: "provider1", model: "deepseek-chat" } } } as Settings;
    expect(draftFromSettings(s)).toEqual({
      id: "provider1",
      draft: { kind: "openai_compatible", name: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
    });
  });

  it("没有服务时用 OpenAI 兼容预设", () => {
    expect(draftFromSettings(base)).toEqual({ id: null, draft: providerPreset("openai_compatible") });
  });
});
