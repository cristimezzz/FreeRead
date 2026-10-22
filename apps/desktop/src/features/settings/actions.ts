// 大模型服务与解析引擎的密钥、连接测试、本机安装。设置页与欢迎向导共用，失败时用 toast 提示。

import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { isTauri } from "../../api/core";
import { useApp } from "../../app/store";

type Engine = Schemas["EngineOut"];
type Job = Schemas["JobOut"];

export type RemoteEngine = "mineru" | "docling";
export const REMOTE_ENGINES: RemoteEngine[] = ["mineru", "docling"];

const toast = (m: string) => useApp.getState().toast(m);

const keySavedMessage = () =>
  isTauri() ? "API Key 已保存到系统钥匙串" : "API Key 已设置（浏览器开发模式下只在本次运行有效）";

/** 保存（key 为 null 时删除）大模型服务的 API Key：系统钥匙串 + Core Service。成功返回 true。 */
export async function saveProviderKey(id: string, key: string | null): Promise<boolean> {
  try {
    if (isTauri()) {
      if (key) await invoke("set_api_key", { providerId: id, key });
      else await invoke("delete_api_key", { providerId: id });
    }
    const path = { params: { path: { provider_id: id } } } as const;
    if (key) await api().PUT("/llm/providers/{provider_id}/key", { ...path, body: { key } });
    else await api().DELETE("/llm/providers/{provider_id}/key", path);
    if (key) toast(keySavedMessage());
    return true;
  } catch (e) {
    toast(`保存 API Key 失败：${e}`);
    return false;
  }
}

/** 测试大模型服务：true 连接正常，false 连接失败，null 请求本身出错。 */
export async function testProvider(id: string, model: string | null): Promise<boolean | null> {
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
}

/** 保存（key 为 null 时删除）解析服务的 API Key，钥匙串里的 ID 是 parser-<engine>（ADR-0008）。 */
export async function saveParserKey(engine: RemoteEngine, key: string | null): Promise<boolean> {
  try {
    if (isTauri()) {
      if (key) await invoke("set_api_key", { providerId: `parser-${engine}`, key });
      else await invoke("delete_api_key", { providerId: `parser-${engine}` });
    }
    const path = { params: { path: { engine } } } as const;
    if (key) await api().PUT("/parsers/{engine}/key", { ...path, body: { key } });
    else await api().DELETE("/parsers/{engine}/key", path);
    if (key) toast(keySavedMessage());
    return true;
  } catch (e) {
    toast(`保存 API Key 失败：${e}`);
    return false;
  }
}

export async function installEngine(engine: RemoteEngine): Promise<void> {
  try {
    unwrap(await api().POST("/parsers/{engine}/install", { params: { path: { engine } } }));
  } catch (e) {
    toast(`无法开始安装：${e}`);
  }
}

export async function testParser(engine: RemoteEngine): Promise<boolean | null> {
  try {
    const r = unwrap(await api().POST("/parsers/{engine}/test", { params: { path: { engine } } }));
    toast(r.ok ? `连接正常（${r.version ?? "版本未知"}，${r.latency_ms} ms）` : `连接失败：${r.error}`);
    return r.ok;
  } catch (e) {
    toast(`测试失败：${e}`);
    return null;
  }
}

/** 每个引擎最近一次本机安装任务（进行中或已结束）。 */
export function latestInstallJobs(jobs: Record<string, Job>): Partial<Record<RemoteEngine, Job>> {
  const out: Partial<Record<RemoteEngine, Job>> = {};
  for (const j of Object.values(jobs)) {
    const name = j.payload.engine as RemoteEngine;
    if (j.kind !== "engine_install") continue;
    const prev = out[name];
    if (!prev || j.created_at > prev.created_at) out[name] = j;
  }
  return out;
}

/**
 * 解析引擎列表与本机安装任务。引擎可用性取决于设置（运行位置、地址、上传确认），
 * 设置变化或安装任务结束后重新获取；保存密钥后调用 refresh。
 */
export function useEngines() {
  const settings = useApp((s) => s.settings);
  const jobs = useApp((s) => s.jobs);
  const [engines, setEngines] = useState<Engine[]>([]);
  const installJobs = latestInstallJobs(jobs);
  const installKey = REMOTE_ENGINES.map((n) => installJobs[n]?.status).join(":");

  const refresh = () =>
    api()
      .GET("/parsers")
      .then((r) => setEngines(unwrap(r)))
      .catch(() => {});

  useEffect(() => {
    void refresh();
  }, [settings, installKey]);

  return { engines, installJobs, refresh };
}
