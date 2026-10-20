// 设置 › Zotero：数据源（本地 API / 数据库快照）、数据目录、上次同步。见 docs/m2/zotero-sync.md。

import { type ReactNode, useEffect, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { isTauri } from "../../api/core";
import { type Settings, useApp } from "../../app/store";
import { Button, Select, TextField } from "../../components/ui";

type SyncState = Schemas["SyncStateOut"];
type Zotero = Settings["zotero"];

const SOURCE_LABEL: Record<string, string> = { zotero_local: "本地 API", zotero_sqlite: "数据库快照" };

const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

export function ZoteroSection({
  settings,
  update,
  Group,
  Row,
  title,
}: {
  settings: Settings;
  update: (patch: Partial<Settings>) => Promise<void>;
  Group: (p: { id: string; title: string; children: ReactNode }) => ReactNode;
  Row: (p: { title: ReactNode; desc?: ReactNode; children?: ReactNode }) => ReactNode;
  title: string;
}) {
  const toast = useApp((s) => s.toast);
  const jobs = useApp((s) => s.jobs);
  const [states, setStates] = useState<SyncState[]>([]);
  const zotero: Zotero = settings.zotero ?? { source: "auto", data_dir: "" };
  const set = (patch: Partial<Zotero>) => update({ zotero: { ...zotero, ...patch } });

  const syncing = Object.values(jobs).find((j) => j.kind === "sync" && (j.status === "queued" || j.status === "running"));
  const syncKey = `${syncing?.id ?? ""}`;
  useEffect(() => {
    void api()
      .GET("/library/sync/state")
      .then((r) => setStates(unwrap(r)))
      .catch(() => undefined);
  }, [syncKey]);

  const browse = async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const dir = await open({ directory: true, title: "选择 Zotero 数据目录（含 zotero.sqlite）" });
    if (typeof dir === "string") await set({ data_dir: dir });
  };

  const fullSync = async () => {
    try {
      unwrap(await api().POST("/library/sync", { body: { full: true } }));
      toast("已开始完全同步");
    } catch (e) {
      toast(`同步失败：${e}`);
    }
  };

  return (
    <Group id="zotero" title={title}>
      <Row title="数据来源" desc="Zotero 运行时用本地 API；没运行时读取数据库快照（先复制一份再读，不会改动 Zotero 的数据库）">
        <Select
          label="数据来源"
          hideLabel
          value={zotero.source}
          options={[
            { value: "auto", label: "自动（推荐）" },
            { value: "local_api", label: "只用本地 API" },
            { value: "sqlite", label: "只用数据库快照" },
          ]}
          onValue={(source) => set({ source })}
        />
      </Row>
      <Row title="Zotero 数据目录" desc="包含 zotero.sqlite 和 storage 文件夹；留空为默认的 用户目录\Zotero">
        <TextField
          label="Zotero 数据目录"
          hideLabel
          mono
          className="model-inp"
          placeholder="~/Zotero"
          value={zotero.data_dir}
          commitOnChange
          onValue={(data_dir) => set({ data_dir: data_dir.trim() })}
        />
        {isTauri() && (
          <Button small onClick={() => void browse()}>
            选择…
          </Button>
        )}
      </Row>
      <Row
        title="上次同步"
        desc={
          states.length
            ? states
                .map(
                  (s) =>
                    `${SOURCE_LABEL[s.source] ?? s.source}：${fmt(s.last_synced_at)}（库版本 ${s.last_version ?? "—"}，上次全量 ${fmt(s.last_full_sync_at)}）`,
                )
                .join("；")
            : "还没有同步过"
        }
      >
        <Button
          small
          icon="sync"
          disabled={Boolean(syncing)}
          title="重新读取全部条目，补上增量同步看不到的变化"
          onClick={() => void fullSync()}
        >
          完全同步
        </Button>
      </Row>
      <p className="set-hint">
        平时同步只读取上次之后变化的条目（需要本地 API）；每 7 天或点"完全同步"时读取全部，并把 Zotero 里删除或移入回收站的条目归档。
      </p>
    </Group>
  );
}
