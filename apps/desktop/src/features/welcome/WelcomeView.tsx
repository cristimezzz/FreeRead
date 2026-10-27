// 首次启动的欢迎向导：大模型服务 → 解析服务 → 从 Zotero 导入。每一步都能跳过，
// 走完或跳过后写入 settings.onboarding_done，之后直接进入文献库（设置页可以重新打开）。

import { type ReactNode, useEffect, useState } from "react";
import { api, unwrap } from "../../api/client";
import { isTauri } from "../../api/core";
import { type Settings, useApp } from "../../app/store";
import { BrandMark } from "../../components/icons";
import { exitMs } from "../../components/motion";
import { OptionToggle, TextInput } from "../../components/controls";
import { Icon } from "../../components/icons";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";
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
import { ConnState, FieldGrid, Hint, Panel, Row } from "../settings/Row";
import { applyWelcomeProvider, draftFromSettings, PROVIDER_PRESETS, type ProviderKind, providerPreset } from "./model";

const STEPS = ["大模型服务", "解析服务", "导入文献"] as const;

export function WelcomeView() {
  const settings = useApp((s) => s.settings);
  const [step, setStep] = useState(0);
  const [finishing, setFinishing] = useState(false);
  // 用户要求减少动效时不播片头
  const [intro, setIntro] = useState(() => exitMs() > 0);
  if (!settings) return null;
  if (intro) return <WelcomeIntro onDone={() => setIntro(false)} />;

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
    <div className="animate-in fade-in-0 h-full overflow-auto px-6 pt-[calc(var(--titlebar-h)+28px)] pb-16 duration-300">
      <div className="mx-auto max-w-3xl">
        <header className="flex items-start gap-4.5 max-[560px]:flex-wrap">
          <BrandMark size={40} />
          <div className="min-w-0 flex-1">
            <h1 className="font-serif text-4xl leading-tight font-medium tracking-tight">欢迎使用 FreeRead</h1>
            <p className="text-muted-foreground mt-1.5">静下心来，开启你的阅读之旅。</p>
          </div>
          <Button variant="ghost" size="sm" className="flex-none" disabled={finishing} onClick={() => void finish(false)}>
            跳过向导
          </Button>
        </header>

        <ol className="mt-8 flex gap-6 border-b" aria-label="步骤">
          {STEPS.map((label, i) => (
            <li
              key={label}
              aria-current={i === step ? "step" : undefined}
              className={cn(
                "text-muted-foreground -mb-px flex items-center gap-2 border-b-2 border-transparent px-1 pb-3 text-[13px] transition-colors",
                i < step && "text-foreground/80",
                i === step && "border-brand text-foreground font-medium",
              )}
            >
              <i
                className={cn(
                  "grid size-5.5 place-items-center rounded-full border text-xs not-italic tabular-nums",
                  i === step && "border-brand text-brand",
                )}
              >
                {i + 1}
              </i>
              {label}
            </li>
          ))}
        </ol>

        <section
          className="animate-in fade-in-0 slide-in-from-bottom-1 pt-7 duration-300"
          key={step}
          aria-labelledby="welcome-step-h"
        >
          {step === 0 && <ProviderStep settings={settings} onNext={next} />}
          {step === 1 && <ParseStep settings={settings} onBack={back} onNext={next} />}
          {step === 2 && <ImportStep settings={settings} busy={finishing} onBack={back} onFinish={finish} />}
        </section>
      </div>
    </div>
  );
}

/** 片头停留多久后开始退场（毫秒），之后淡出 INTRO_EXIT_MS 进入向导；点击或按键可跳过。 */
const INTRO_HOLD_MS = 1800;
const INTRO_EXIT_MS = 280;

/**
 * 进入向导前的片头：Logo 的两页从书脊处展开，启动页进度条的位置上画出一道强调色细线，然后淡出。
 * 版式与启动页（.boot）相同，从启动页过来时 Logo 和名称原地不动。
 */
function WelcomeIntro({ onDone }: { onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setLeaving(true), INTRO_HOLD_MS);
    const skip = () => setLeaving(true);
    window.addEventListener("keydown", skip);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", skip);
    };
  }, []);

  useEffect(() => {
    if (!leaving) return;
    const t = setTimeout(onDone, INTRO_EXIT_MS);
    return () => clearTimeout(t);
  }, [leaving]);

  return (
    <div
      className="welcome-intro text-muted-foreground flex h-full cursor-default flex-col items-center justify-center gap-5 p-6 text-center text-[13px] select-none"
      data-state={leaving ? "leaving" : undefined}
      role="presentation"
      onClick={() => setLeaving(true)}
    >
      <BrandMark size={56} />
      <div className="text-foreground font-serif text-3xl font-medium tracking-tight">FreeRead</div>
      {/* 占住启动页进度条和状态文字的位置，Logo 与名称才不会移动 */}
      <span className="welcome-intro-rule" />
      <p aria-hidden="true" className="invisible">
        FreeRead
      </p>
    </div>
  );
}

function StepHead({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <h2 id="welcome-step-h" className="mb-1 font-serif text-xl font-medium">
        {title}
      </h2>
      <Hint>{children}</Hint>
    </>
  );
}

function StepActions({ onBack, children }: { onBack?: () => void; children: ReactNode }) {
  return (
    <div className="mt-7 flex items-center gap-2">
      {onBack && (
        <Button variant="ghost" onClick={onBack}>
          上一步
        </Button>
      )}
      <span className="ml-auto flex gap-2">{children}</span>
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
      <Panel>
        <div className="flex flex-wrap items-center gap-2.5">
          <OptionToggle
            label="服务类型"
            value={draft.kind}
            options={(Object.keys(PROVIDER_PRESETS) as ProviderKind[]).map((k) => ({ value: k, label: PROVIDER_PRESETS[k].label }))}
            onValue={(kind) => {
              setDraft(providerPreset(kind));
              setTested(null);
            }}
          />
          <span className="ml-auto flex items-center gap-1">
            {tested === true && <ConnState ok>连接正常</ConnState>}
            {tested === false && <ConnState ok={false}>连接失败</ConnState>}
            <Button
              variant="ghost"
              size="sm"
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
        <FieldGrid>
          <TextInput label="名称" value={draft.name} onValue={(name) => edit({ name })} />
          <TextInput label="模型" mono value={draft.model} onValue={(model) => edit({ model })} />
          <TextInput label="Base URL" mono value={draft.base_url} onValue={(base_url) => edit({ base_url })} />
          {needsKey && (
            <TextInput
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
        </FieldGrid>
      </Panel>
      <StepActions>
        <Button variant="outline" onClick={onNext}>
          跳过
        </Button>
        <Button
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
        <OptionToggle
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
          pypiMirror={settings.pypi_mirror}
          onPypiMirror={(pypi_mirror) => update({ pypi_mirror })}
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
        <Hint>
          {info.available
            ? `${info.label} 已可用，导入的 PDF 会在后台升级成高质量版本。`
            : "可以先继续：安装或配置完成之前，先用快速模式解析。"}
        </Hint>
      )}
      <StepActions onBack={onBack}>
        <Button onClick={onNext}>继续</Button>
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
        <TextInput
          label="Zotero 数据目录"
          hideLabel
          mono
          className="min-w-45"
          placeholder="~/Zotero"
          value={zotero.data_dir}
          commitOnChange
          onValue={(d) => setDir(d.trim())}
        />
        {isTauri() && (
          <Button variant="outline" size="sm" onClick={() => void browse()}>
            选择…
          </Button>
        )}
      </Row>
      <StepActions onBack={onBack}>
        <Button variant="outline" disabled={busy} onClick={() => onFinish(false)}>
          暂不导入
        </Button>
        <Button disabled={busy} onClick={() => onFinish(true)}>
          <Icon name="sync" />
          从 Zotero 同步
        </Button>
      </StepActions>
    </>
  );
}
