// 高质量解析引擎（MinerU / Docling）的运行位置卡片：本机安装或 API 服务（ADR-0008）。设置页与欢迎向导共用。

import { useState } from "react";
import type { Schemas } from "../../api/client";
import { OptionSelect, OptionToggle, ProgressBar, TextInput } from "../../components/controls";
import { Button } from "../../components/ui/button";
import type { RemoteEngine } from "./actions";
import { ConnState, FieldGrid, Panel, Row } from "./Row";

type Engine = Schemas["EngineOut"];
type RemoteParser = Schemas["RemoteParser"];
type Job = Schemas["JobOut"];

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

const TIERS: { value: RemoteParser["tier"]; label: string }[] = [
  { value: "standard", label: "standard（VLM，推荐）" },
  { value: "advanced", label: "advanced（最准，最慢）" },
];

const CUSTOM_MIRROR = "custom";
const PYPI_MIRRORS: { value: string; label: string }[] = [
  { value: "", label: "官方 PyPI" },
  { value: "https://pypi.tuna.tsinghua.edu.cn/simple", label: "清华大学" },
  { value: "https://mirrors.aliyun.com/pypi/simple", label: "阿里云" },
  { value: "https://mirrors.ustc.edu.cn/pypi/simple", label: "中国科学技术大学" },
  { value: "https://mirrors.cloud.tencent.com/pypi/simple", label: "腾讯云" },
  { value: CUSTOM_MIRROR, label: "自定义…" },
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
  /** 本机安装用的 PyPI 镜像（设置 pypi_mirror，两个引擎共用） */
  pypiMirror: string;
  onPypiMirror: (url: string) => void;
  onChange: (patch: Partial<RemoteParser>) => void;
  onKey: (key: string | null) => void;
  onTest: () => Promise<boolean | null>;
}

export function RemoteParserCard({
  engine,
  label,
  cfg,
  info,
  installJob,
  onInstall,
  pypiMirror,
  onPypiMirror,
  onChange,
  onKey,
  onTest,
}: RemoteParserCardProps) {
  const [key, setKey] = useState("");
  const [tested, setTested] = useState<boolean | null>(null);
  const isApi = cfg.mode === "api";
  return (
    <Panel>
      <div className="flex flex-wrap items-center gap-2.5">
        <b className="text-[15px] font-medium">{label}</b>
        {isApi && tested === true && <ConnState ok>连接正常</ConnState>}
        {isApi && tested === false && <ConnState ok={false}>连接失败</ConnState>}
        <span className="ml-auto flex items-center gap-1">
          {isApi && (
            <Button variant="ghost" size="sm" disabled={!cfg.base_url} onClick={async () => setTested(await onTest())}>
              测试连接
            </Button>
          )}
          <OptionToggle
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
          <FieldGrid>
            <TextInput
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
              <OptionSelect label="质量档位（tier）" value={cfg.tier} options={TIERS} onValue={(tier) => onChange({ tier })} />
            )}
            <TextInput
              label={info?.has_key ? "API Key（已保存，输入新值可替换）" : "API Key（本机服务通常不需要）"}
              type="password"
              mono
              value={key}
              onValue={setKey}
            />
          </FieldGrid>
          <div className="mt-3.5 flex gap-2">
            <Button
              size="sm"
              disabled={!key}
              onClick={() => {
                onKey(key);
                setKey("");
              }}
            >
              保存 Key
            </Button>
            {info?.has_key && (
              <Button variant="outline" size="sm" onClick={() => onKey(null)}>
                删除 Key
              </Button>
            )}
          </div>
          {info?.unavailable_reason === "consent_required" && (
            <Row
              title="需要你的允许"
              desc={`使用这个服务时，PDF 原文会上传到 ${urlHost(cfg.base_url)}。允许后才会用它解析。`}
            >
              <Button variant="outline" size="sm" onClick={() => onChange({ consented_url: cfg.base_url })}>
                允许上传
              </Button>
            </Row>
          )}
        </>
      )}
      {!isApi && (
        <LocalInstall
          label={label}
          info={info}
          job={installJob}
          onInstall={onInstall}
          mirror={pypiMirror}
          onMirror={onPypiMirror}
        />
      )}
    </Panel>
  );
}

/** 本机模式：未安装时提供安装（可选 PyPI 镜像），安装中显示进度，失败时显示原因并可重试。 */
function LocalInstall({
  label,
  info,
  job,
  onInstall,
  mirror,
  onMirror,
}: {
  label: string;
  info: Engine | undefined;
  job: Job | undefined;
  onInstall: () => void;
  mirror: string;
  onMirror: (url: string) => void;
}) {
  const active = job && (job.status === "queued" || job.status === "running");
  if (active) {
    return (
      <Row
        title={`正在安装 ${label}… ${Math.round(job.progress * 100)}%`}
        desc={
          <>
            <span className="block truncate font-mono">{job.message ?? "排队中"}</span>
            <ProgressBar value={job.progress} className="mt-2 block w-55" />
          </>
        }
      />
    );
  }
  if (info?.unavailable_reason !== "not_installed") return null;
  const failed = job?.status === "failed";
  return (
    <>
      <PypiMirrorRow mirror={mirror} onMirror={onMirror} />
      <Row
        title={failed ? "安装失败" : `本机未安装 ${label}`}
        desc={
          failed ? (
            <span className="text-destructive block max-h-[9em] overflow-auto font-mono break-all whitespace-pre-wrap">{job.error}</span>
          ) : (
            <>
              安装会下载 Python 3.12、PyTorch 与 {label}（共数 GB）到独立环境，首次解析时还会下载模型。也可以改用 API 服务。
            </>
          )
        }
      >
        <Button variant={failed ? "outline" : "default"} size="sm" onClick={onInstall}>
          {failed ? "重试安装" : "安装"}
        </Button>
      </Row>
    </>
  );
}

/** PyPI 镜像：常用国内源或自定义 simple 索引地址。 */
function PypiMirrorRow({ mirror, onMirror }: { mirror: string; onMirror: (url: string) => void }) {
  const known = PYPI_MIRRORS.some((m) => m.value === mirror && m.value !== CUSTOM_MIRROR);
  const [custom, setCustom] = useState(!known);
  return (
    <Row title="PyPI 镜像" desc="安装时下载 Python 包的源；PyTorch 仍从 PyTorch 官方源下载">
      <span className="flex flex-wrap justify-end gap-2 [&>*]:w-65 [&>*]:max-w-full">
        <OptionSelect
          label="PyPI 镜像"
          hideLabel
          value={custom ? CUSTOM_MIRROR : mirror}
          options={PYPI_MIRRORS}
          onValue={(v) => {
            setCustom(v === CUSTOM_MIRROR);
            if (v !== CUSTOM_MIRROR) onMirror(v);
          }}
        />
        {custom && (
          <TextInput
            label="自定义 PyPI 镜像"
            hideLabel
            mono
            placeholder="https://…/simple"
            value={mirror}
            commitOnChange
            onValue={(v) => onMirror(v.trim())}
          />
        )}
      </span>
    </Row>
  );
}
