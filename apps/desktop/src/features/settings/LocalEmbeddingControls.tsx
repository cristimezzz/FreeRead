import { type ReactNode, useEffect, useState } from "react";
import { api, type Schemas, unwrap } from "../../api/client";
import { type Settings, useApp } from "../../app/store";
import { OptionSelect, ProgressBar, TextInput } from "../../components/controls";
import { Button } from "../../components/ui/button";
import { Hint, More, Row } from "./Row";

const DEFAULT_MIRROR = "https://huggingface.co";
type EmbeddingModel = Schemas["EmbeddingModel"];

export function LocalEmbeddingControls({
  embedding,
  onSavingChange,
  footer,
}: {
  embedding: Settings["embedding"];
  onSavingChange?: (saving: boolean) => void;
  footer?: (canContinue: boolean, saving: boolean) => ReactNode;
}) {
  const [modelId, setModelId] = useState(embedding.local_model);
  const [mirror, setMirror] = useState(embedding.mirror === DEFAULT_MIRROR ? "" : embedding.mirror);
  const [models, setModels] = useState<EmbeddingModel[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const jobs = useApp((s) => s.jobs);
  const downloads = Object.values(jobs).filter((job) => job.kind === "model_download");
  const completed = downloads.filter((job) => job.status === "done").map((job) => job.id).join(",");
  const selected = models.find((model) => model.id === modelId) ?? models.find((model) => model.recommended);
  const job = downloads
    .filter((job) => job.payload.model === selected?.id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))[0];
  const active = job?.status === "running" || job?.status === "queued";
  const installed = selected?.downloaded;
  const current = embedding.source === "local" && selected?.id === embedding.local_model;
  const downloadSource = mirror.trim() || DEFAULT_MIRROR;

  useEffect(() => {
    let ignore = false;
    void api().GET("/embedding/models").then((response) => {
      const list = unwrap(response);
      if (ignore) return;
      setModels(list);
      setLoadError(false);
    }).catch(() => {
      if (!ignore) setLoadError(true);
    });
    return () => { ignore = true; };
  }, [completed, retry]);

  const apply = async () => {
    if (!selected || saving) return;
    setError("");
    setSaving(true);
    onSavingChange?.(true);
    let saved = false;
    try {
      const { settings, saveSettings } = useApp.getState();
      if (!settings) return;
      await saveSettings({
        ...settings,
        embedding: { ...settings.embedding, source: "local", local_model: selected.id, mirror: downloadSource },
      });
      saved = true;
      if (!installed && !active) {
        const enqueued = unwrap(await api().POST("/embedding/download", { params: { query: { model_id: selected.id } } }));
        useApp.setState((state) => ({
          jobs: { ...state.jobs, [enqueued.id]: state.jobs[enqueued.id] ?? enqueued },
        }));
      }
    } catch (e) {
      setError(`${saved ? "无法开始下载" : "保存索引设置失败"}：${e}`);
    } finally {
      setSaving(false);
      onSavingChange?.(false);
    }
  };

  return (
    <>
      {loadError && (
        <Row title="无法加载本地模型列表">
          <Button variant="outline" size="sm" onClick={() => { setLoadError(false); setRetry((n) => n + 1); }}>
            重试
          </Button>
        </Row>
      )}
      {!selected && !loadError && <Hint role="status">正在加载本地模型…</Hint>}
      {selected && (
        <>
          <Row title="本地索引模型" desc={selected.description}>
            <OptionSelect
              label="本地索引模型"
              hideLabel
              value={selected.id}
              options={models.map((model) => ({
                value: model.id,
                label: model.recommended ? `${model.label} · 推荐` : model.label,
              }))}
              disabled={saving}
              onValue={(id) => { setError(""); setModelId(id); }}
            />
          </Row>
          <Row
            title={`下载大小约 ${Math.round(selected.size_bytes / (1 << 20))} MiB`}
            desc={
              <span className="block break-words" role="status">
                {installed ? "已下载" : job?.status === "failed" ? `下载失败：${job.error ?? "请重试"}` :
                  job?.status === "queued" ? "等待下载" : job?.status === "running" ?
                    `下载中 ${Math.round(job.progress * 100)}%` : "未下载"}
                {active && <ProgressBar value={job.progress} className="mt-2 block w-40 max-w-full" />}
              </span>
            }
          >
            {(!current || !(active || installed) || downloadSource !== embedding.mirror) && (
              <Button variant="outline" size="sm" disabled={saving} onClick={() => void apply()}>
                {active || installed
                  ? current ? "保存下载源" : "使用此模型"
                  : job?.status === "failed" ? "重试下载" : "下载模型"}
              </Button>
            )}
          </Row>
          {error && <Hint className="text-destructive break-words" role="alert">{error}</Hint>}
          <More label="下载源" defaultOpen={Boolean(mirror)}>
            <Row title="Hugging Face 镜像" desc="留空使用 Hugging Face 官方源。">
              <TextInput
                label="Hugging Face 镜像"
                hideLabel
                mono
                value={mirror}
                placeholder="https://huggingface.co"
                disabled={saving}
                onValue={(value) => { setError(""); setMirror(value); }}
              />
            </Row>
          </More>
        </>
      )}
      {footer?.(embedding.source === "provider" || Boolean(current && (active || installed)), saving)}
    </>
  );
}
