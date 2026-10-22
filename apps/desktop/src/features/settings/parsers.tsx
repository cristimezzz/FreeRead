// 高质量解析引擎（MinerU / Docling）的运行位置卡片：本机安装或 API 服务（ADR-0008）。设置页与欢迎向导共用。

import { useState } from "react";
import type { Schemas } from "../../api/client";
import { Button, Progress, Segmented, Select, TextField } from "../../components/ui";
import type { RemoteEngine } from "./actions";
import { Row } from "./Row";

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

export function RemoteParserCard({
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
