import { useEffect, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { useApp } from "../../app/store";
import { Dialog } from "../../components/ui";
import { engineOptionLabel } from "../settings/SettingsView";

type Engine = Schemas["EngineOut"];

/** 选一个引擎强制重新解析本文。不可用的引擎列出但禁用，并提示去设置里安装或配置。 */
export function ReparseDialog({
  open,
  docId,
  current,
  onClose,
}: {
  open: boolean;
  docId: string;
  /** 当前解析结果所用引擎 */
  current?: string;
  onClose: () => void;
}) {
  const toast = useApp((s) => s.toast);
  const preferred = useApp((s) => s.settings?.parse_engine);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [engine, setEngine] = useState<string>("");

  // 每次打开都重新取：引擎可能刚在设置里装好或改成 API 模式
  useEffect(() => {
    if (!open) return;
    void api()
      .GET("/parsers")
      .then((r) => {
        const list = unwrap(r);
        setEngines(list);
        const ok = list.filter((e) => e.available);
        // 默认：设置里选的高质量引擎 → 其他可用的高质量引擎（MinerU 优先）→ 快速模式
        const pick =
          ok.find((e) => e.name === preferred && e.heavy) ??
          [...ok].filter((e) => e.heavy).sort((a, b) => (a.name === "mineru" ? -1 : b.name === "mineru" ? 1 : 0))[0] ??
          ok[0];
        setEngine(pick?.name ?? "");
      })
      .catch((e) => toast(`获取解析引擎失败：${e}`));
  }, [open, preferred, toast]);

  const start = async () => {
    const label = engines.find((e) => e.name === engine)?.label ?? engine;
    try {
      unwrap(
        await api().POST("/documents/{doc_id}/parse", {
          params: { path: { doc_id: docId } },
          body: { engine },
        }),
      );
      toast(`已开始用 ${label} 重新解析`);
    } catch (e) {
      toast(`无法重新解析：${e}`);
    }
  };

  const missing = engines.some((e) => e.heavy && !e.available);

  return (
    <Dialog
      open={open}
      headline="重新解析"
      onClose={(v) => {
        if (v === "ok" && engine) void start();
        onClose();
      }}
      actions={[
        { value: "cancel", label: "取消" },
        { value: "ok", label: "开始解析", primary: true },
      ]}
    >
      <p>选择解析引擎。译文、总结和问答里的引用会迁移到新结果，对不上的会标记为失效。</p>
      <div className="reparse-options" role="radiogroup" aria-label="解析引擎">
        {engines.map((e) => (
          <label key={e.name} className="reparse-option" data-disabled={!e.available || undefined}>
            <input
              type="radio"
              name="reparse-engine"
              value={e.name}
              checked={engine === e.name}
              disabled={!e.available}
              onChange={() => setEngine(e.name)}
            />
            <span>{engineOptionLabel(e)}</span>
            {e.name === current && <span className="reparse-current">当前</span>}
          </label>
        ))}
      </div>
      {missing && <p className="reparse-hint">未安装或未配置的引擎可以在 设置 › 解析 中安装，或改用 API 服务。</p>}
    </Dialog>
  );
}
