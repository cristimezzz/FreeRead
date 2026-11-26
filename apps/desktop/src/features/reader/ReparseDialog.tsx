import { useEffect, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { useApp } from "../../app/store";
import { ActionDialog } from "../../components/controls";
import { Label } from "../../components/ui/label";
import { RadioGroup, RadioGroupItem } from "../../components/ui/radio-group";
import { cn } from "../../lib/utils";
import { engineOptionLabel } from "../settings/parsers";

type Engine = Schemas["EngineOut"];

/** 选择引擎重新解析单篇文献或整个文献库。 */
export function ReparseDialog({
  open,
  docId,
  current,
  onClose,
}: {
  open: boolean;
  docId?: string;
  /** 当前解析结果所用引擎 */
  current?: string;
  onClose: () => void;
}) {
  const toast = useApp((s) => s.toast);
  const preferred = useApp((s) => s.settings?.parse_engine);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [engine, setEngine] = useState<string>("");
  const all = docId === undefined;

  // 每次打开都重新取：引擎可能刚在设置里装好或改成 API 模式
  useEffect(() => {
    if (!open) return;
    let active = true;
    void api()
      .GET("/parsers")
      .then((r) => {
        if (!active) return;
        const list = unwrap(r);
        setEngines(list);
        const ok = list.filter((e) => e.available);
        // 批量默认按设置选引擎；单篇仍优先选择可用的高质量引擎。
        const pick = all
          ? ok.find((e) => e.name === (preferred === "auto" ? "mineru" : preferred)) ?? ok.find((e) => e.name === "pymupdf")
          : ok.find((e) => e.name === preferred && e.heavy) ??
            [...ok].filter((e) => e.heavy).sort((a, b) => (a.name === "mineru" ? -1 : b.name === "mineru" ? 1 : 0))[0] ??
            ok[0];
        setEngine(pick?.name ?? "");
      })
      .catch((e) => { if (active) toast(`获取解析引擎失败：${e}`); });
    return () => { active = false; };
  }, [open, preferred, toast, all]);

  const start = async () => {
    const label = engines.find((e) => e.name === engine)?.label ?? engine;
    try {
      if (docId === undefined) {
        const result = unwrap(await api().POST("/documents/reparse-all", { body: { engine } }));
        const summary = [`已排队 ${result.queued} 篇`];
        if (result.already_active) summary.push(`${result.already_active} 篇已在排队或解析中`);
        if (result.missing_pdf) summary.push(`${result.missing_pdf} 篇缺少可用 PDF`);
        toast(summary.join("，"));
        return;
      }
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
    <ActionDialog
      open={open}
      headline={all ? "全部重新解析" : "重新解析"}
      onClose={(v) => {
        if (v === "ok" && engine) void start();
        setEngine("");
        setEngines([]);
        onClose();
      }}
      actions={[
        { value: "cancel", label: "取消" },
        { value: "ok", label: all ? "全部重新解析" : "开始解析", primary: true, disabled: !engine },
      ]}
    >
      {all && <p>文献库中有可用 PDF 的文献将使用所选引擎在后台重新解析。选用 API 服务时，PDF 可能上传到对应服务。</p>}
      <p>选择解析引擎。译文、总结和问答里的引用会迁移到新结果，对不上的会标记为失效。</p>
      <RadioGroup className="mt-3.5 mb-1 gap-1" aria-label="解析引擎" value={engine} onValueChange={setEngine}>
        {engines.map((e) => (
          <Label
            key={e.name}
            className={cn(
              "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 font-normal",
              e.available ? "hover:bg-accent" : "text-muted-foreground cursor-default",
            )}
          >
            <RadioGroupItem
              value={e.name}
              disabled={!e.available}
              className="data-[state=checked]:border-brand [&_svg]:fill-brand"
            />
            <span>{engineOptionLabel(e)}</span>
            {e.name === current && <span className="text-muted-foreground ml-auto text-xs">当前</span>}
          </Label>
        ))}
      </RadioGroup>
      {missing && (
        <p className="text-muted-foreground mt-2 text-[12.5px]">
          未安装或未配置的引擎可以在 设置 › 解析 中安装，或改用 API 服务。
        </p>
      )}
    </ActionDialog>
  );
}
