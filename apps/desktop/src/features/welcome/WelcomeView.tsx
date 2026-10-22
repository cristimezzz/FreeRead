// 首次启动的欢迎向导：大模型服务 → 解析服务 → 从 Zotero 导入。每一步都能跳过，
// 走完或跳过后写入 settings.onboarding_done，之后直接进入文献库（设置页可以重新打开）。

import { type ReactNode, useEffect, useState } from "react";
import { api, unwrap } from "../../api/client";
import { isTauri } from "../../api/core";
import { type Settings, useApp } from "../../app/store";
import { BrandMark } from "../../components/icons";
import { Button, Segmented, TextField } from "../../components/ui";
import {
  REMOTE_ENGINES,
  type RemoteEngine,
  installEngine,
  saveParserKey,
  saveProviderKey,
  testParser,
  testProvider,
  useEngines,
} from "../settings/actions";
import { RemoteParserCard } from "../settings/parsers";
import { Row } from "../settings/Row";
import { applyWelcomeProvider, draftFromSettings, PROVIDER_PRESETS, type ProviderKind, providerPreset } from "./model";

const STEPS = ["大模型服务", "解析服务", "导入文献"] as const;

export function WelcomeView() {
  const settings = useApp((s) => s.settings);
  const [step, setStep] = useState(0);
  const [finishing, setFinishing] = useState(false);
  if (!settings) return null;

  const finish = async (syncZotero: boolean) => {
    const { saveSettings, toast, navigate } = useApp.getState();
    setFinishing(true);
    try {
      if (syncZotero) {
        unwrap(await api().POST("/library/sync", { body: { full: true } }));
        toast("已开始从 Zotero 同步，进度见底部任务条");
      }
      navigate({ name: "library" });
      await saveSettings({ ...useApp.getState().settings!, onboarding_done: true });
    } catch (e) {
      toast(syncZotero ? `同步失败：${e}` : `保存失败：${e}`);
      setFinishing(false);
    }
  };

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = step > 0 ? () => setStep((s) => s - 1) : undefined;

  return (
    <div className="welcome">
      <div className="welcome-col">
        <header className="welcome-head">
          <BrandMark size={40} />
          <div>
            <h1 className="display serif">欢迎使用 FreeRead</h1>
            <p className="page-sub">静下心来，开启你的阅读之旅。</p>
          </div>
          <Button variant="ghost" small className="welcome-skip" disabled={finishing} onClick={() => void finish(false)}>
            跳过向导
          </Button>
        </header>

        <ol className="welcome-steps" aria-label="步骤">
          {STEPS.map((label, i) => (
            <li key={label} aria-current={i === step ? "step" : undefined} data-done={i < step || undefined}>
              <i>{i + 1}</i>
              {label}
            </li>
          ))}
        </ol>

        <section className="welcome-step" key={step} aria-labelledby="welcome-step-h">
          {step === 0 && <ProviderStep settings={settings} onNext={next} />}
          {step === 1 && <ParseStep settings={settings} onBack={back} onNext={next} />}
          {step === 2 && <ImportStep settings={settings} busy={finishing} onBack={back} onFinish={finish} />}
        </section>
      </div>
    </div>
  );
}

function StepHead({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <h2 id="welcome-step-h" className="serif">
        {title}
      </h2>
      <p className="set-hint">{children}</p>
    </>
  );
}

function StepActions({ onBack, children }: { onBack?: () => void; children: ReactNode }) {
  return (
    <div className="welcome-actions">
      {onBack && (
        <Button variant="ghost" onClick={onBack}>
          上一步
        </Button>
      )}
      <span className="welcome-actions-end">{children}</span>
    </div>
  );
}

/* ------------------------------------------------------------ 1. 大模型服务 */

const save = async (s: Settings) => {
  try {
    await useApp.getState().saveSettings(s);
    return true;
  } catch (e) {
    useApp.getState().toast(`保存失败：${e}`);
    return false;
  }
};

function ProviderStep({ settings, onNext }: { settings: Settings; onNext: () => void }) {
  const [initial] = useState(() => draftFromSettings(settings));
  const [id, setId] = useState(initial.id);
  const [draft, setDraft] = useState(initial.draft);
  const [key, setKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [tested, setTested] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const needsKey = PROVIDER_PRESETS[draft.kind].needsKey;

  useEffect(() => {
    if (!id) return;
    void api()
      .GET("/llm/providers")
      .then((r) => setHasKey(Boolean(unwrap(r).find((p) => p.id === id)?.has_key)))
      .catch(() => {});
  }, [id]);

  const edit = (patch: Partial<typeof draft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setTested(null);
  };

  const canSave = Boolean(draft.base_url.trim() && draft.model.trim() && (!needsKey || key || hasKey));

  /** 写入设置和密钥，返回服务 id；失败返回 null。 */
  const persist = async (): Promise<string | null> => {
    const applied = applyWelcomeProvider(useApp.getState().settings!, draft, id);
    if (!(await save(applied.settings))) return null;
    setId(applied.id);
    if (key) {
      if (!(await saveProviderKey(applied.id, key))) return null;
      setKey("");
      setHasKey(true);
    }
    return applied.id;
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <StepHead title="连接一个大模型服务">
        翻译、总结、问答和知识图谱都要用到大模型。支持 OpenAI 兼容接口（OpenAI、DeepSeek、通义、Moonshot、vLLM
        等）、Anthropic 和本机的 Ollama。API Key 保存在系统钥匙串，不写入设置文件。
      </StepHead>
      <div className="card provider">
        <div className="provider-head">
          <Segmented
            label="服务类型"
            value={draft.kind}
            options={(Object.keys(PROVIDER_PRESETS) as ProviderKind[]).map((k) => ({ value: k, label: PROVIDER_PRESETS[k].label }))}
            onValue={(kind) => {
              setDraft(providerPreset(kind));
              setTested(null);
            }}
          />
          <span className="provider-actions">
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
            <Button
              variant="ghost"
              small
              disabled={!canSave || busy}
              onClick={() =>
                run(async () => {
                  const saved = await persist();
                  if (saved) setTested(await testProvider(saved, draft.model.trim()));
                })
              }
            >
              测试连接
            </Button>
          </span>
        </div>
        <div className="grid">
          <TextField label="名称" value={draft.name} onValue={(name) => edit({ name })} />
          <TextField label="模型" mono value={draft.model} onValue={(model) => edit({ model })} />
          <TextField label="Base URL" mono value={draft.base_url} onValue={(base_url) => edit({ base_url })} />
          {needsKey && (
            <TextField
              label={hasKey ? "API Key（已保存，输入新值可替换）" : "API Key"}
              type="password"
              mono
              value={key}
              onValue={(k) => {
                setKey(k);
                setTested(null);
              }}
            />
          )}
        </div>
      </div>
      <StepActions>
        <Button onClick={onNext}>跳过</Button>
        <Button
          variant="primary"
          disabled={!canSave || busy}
          onClick={() =>
            run(async () => {
              if (await persist()) onNext();
            })
          }
        >
          保存并继续
        </Button>
      </StepActions>
    </>
  );
}

/* ------------------------------------------------------------ 2. 解析服务 */

type EngineChoice = Settings["parse_engine"];

const ENGINE_CHOICES: { value: EngineChoice; label: string; desc: string }[] = [
  { value: "auto", label: "自动（推荐）", desc: "导入后先用快速模式秒级出可读版本；装好 MinerU 或配置了 MinerU 服务后，自动在后台升级成高质量版本。" },
  { value: "pymupdf", label: "只用快速模式", desc: "只用内置的 PyMuPDF，不需要额外安装。公式、表格和复杂版面的效果一般。" },
  { value: "mineru", label: "MinerU", desc: "公式、表格和双栏版面效果最好。可以装在本机（需要数 GB 空间，有 NVIDIA 显卡更快），也可以调用 mineru.net 或自部署的 mineru-api。" },
  { value: "docling", label: "Docling", desc: "IBM 开源的文档解析器。可以装在本机，也可以调用自部署的 docling-serve。" },
];

function ParseStep({ settings, onBack, onNext }: { settings: Settings; onBack?: () => void; onNext: () => void }) {
  const { engines, installJobs, refresh } = useEngines();
  const choice = ENGINE_CHOICES.find((c) => c.value === settings.parse_engine) ?? ENGINE_CHOICES[0];
  const heavy = REMOTE_ENGINES.includes(choice.value as RemoteEngine) ? (choice.value as RemoteEngine) : null;
  const update = (patch: Partial<Settings>) => void save({ ...useApp.getState().settings!, ...patch });
  const info = heavy ? engines.find((e) => e.name === heavy) : undefined;

  return (
    <>
      <StepHead title="选择 PDF 解析方式">
        FreeRead 把 PDF 解析成段落、公式、表格和图片，再做翻译与问答。解析质量决定了阅读和翻译的效果。
      </StepHead>
      <Row title="解析引擎" desc={choice.desc}>
        <Segmented
          label="解析引擎"
          value={choice.value}
          options={ENGINE_CHOICES.map((c) => ({ value: c.value, label: c.label }))}
          onValue={(parse_engine) => update({ parse_engine })}
        />
      </Row>
      {heavy && (
        <RemoteParserCard
          engine={heavy}
          label={info?.label ?? choice.label}
          cfg={settings.parsers[heavy]}
          info={info}
          installJob={installJobs[heavy]}
          onInstall={() => void installEngine(heavy)}
          onChange={(patch) =>
            update({ parsers: { ...settings.parsers, [heavy]: { ...settings.parsers[heavy], ...patch } } })
          }
          onKey={async (k) => {
            if (await saveParserKey(heavy, k)) await refresh();
          }}
          onTest={() => testParser(heavy)}
        />
      )}
      {heavy && info && (
        <p className="set-hint">
          {info.available
            ? `${info.label} 已可用，导入的 PDF 会在后台升级成高质量版本。`
            : "可以先继续：安装或配置完成之前，先用快速模式解析。"}
        </p>
      )}
      <StepActions onBack={onBack}>
        <Button variant="primary" onClick={onNext}>
          继续
        </Button>
      </StepActions>
    </>
  );
}

/* ------------------------------------------------------------ 3. 导入 */

function ImportStep({
  settings,
  busy,
  onBack,
  onFinish,
}: {
  settings: Settings;
  busy: boolean;
  onBack?: () => void;
  onFinish: (syncZotero: boolean) => void;
}) {
  const zotero = settings.zotero;
  const setDir = (data_dir: string) => void save({ ...useApp.getState().settings!, zotero: { ...zotero, data_dir } });

  const browse = async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const dir = await open({ directory: true, title: "选择 Zotero 数据目录（含 zotero.sqlite）" });
    if (typeof dir === "string") setDir(dir);
  };

  return (
    <>
      <StepHead title="要从 Zotero 导入现有文献吗？">
        FreeRead 读取 Zotero 里的条目、分类和 PDF 附件，不会改动 Zotero 的数据。Zotero 运行时用本地 API，没运行时读取数据库快照。以后可以随时在文献库里点「同步」。
      </StepHead>
      <Row title="Zotero 数据目录" desc="包含 zotero.sqlite 和 storage 文件夹；留空为默认的 用户目录\Zotero">
        <TextField
          label="Zotero 数据目录"
          hideLabel
          mono
          className="model-inp"
          placeholder="~/Zotero"
          value={zotero.data_dir}
          commitOnChange
          onValue={(d) => setDir(d.trim())}
        />
        {isTauri() && (
          <Button small onClick={() => void browse()}>
            选择…
          </Button>
        )}
      </Row>
      <StepActions onBack={onBack}>
        <Button disabled={busy} onClick={() => onFinish(false)}>
          暂不导入
        </Button>
        <Button variant="primary" icon="sync" disabled={busy} onClick={() => onFinish(true)}>
          从 Zotero 同步
        </Button>
      </StepActions>
    </>
  );
}
