import { useState } from "react";
import { isTauri } from "../../api/core";
import { Spinner } from "../../components/controls";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { Label } from "../../components/ui/label";
import {
  appDataUsage,
  type DataUsage,
  DEFAULT_SCOPE,
  type DeleteScope,
  deleteAppData,
  deleteSummary,
  formatBytes,
  nothingSelected,
  restartApp,
  SCOPE_ITEMS,
} from "./data";
import { Group, Row } from "./Row";

type Step = { s: "idle" } | { s: "deleting" } | { s: "failed"; error: string };

export function DataSection({ title }: { title: string }) {
  const desktop = isTauri();
  const [open, setOpen] = useState(false);
  const [usage, setUsage] = useState<DataUsage | null>(null);
  const [usageErr, setUsageErr] = useState<string | null>(null);
  const [scope, setScope] = useState<DeleteScope>(DEFAULT_SCOPE);
  const [step, setStep] = useState<Step>({ s: "idle" });

  const show = () => {
    setScope(DEFAULT_SCOPE);
    setStep({ s: "idle" });
    setOpen(true);
    // 每次打开都重新统计：期间可能导入了文档或装了引擎
    setUsage(null);
    setUsageErr(null);
    appDataUsage()
      .then(setUsage)
      .catch((e) => setUsageErr(String(e)));
  };

  const run = async () => {
    setStep({ s: "deleting" });
    if (scope.library) {
      try {
        localStorage.clear();
      } catch {
        // localStorage 不可用时没有要清的
      }
    }
    try {
      await deleteAppData(scope); // 成功时应用直接重启
    } catch (e) {
      setStep({ s: "failed", error: String(e) });
    }
  };

  const restart = () => {
    restartApp().catch((e) => setStep({ s: "failed", error: String(e) }));
  };

  const size = (key: keyof DeleteScope) => {
    if (key === "keys") return null;
    if (usageErr) return null;
    return usage ? formatBytes(usage[key]) : "…";
  };

  const busy = step.s !== "idle";

  return (
    <Group id="data" title={title}>
      <Row
        title="删除应用数据"
        desc={
          desktop
            ? `清除本机保存的文献、设置、API Key 等，删除后无法恢复${usage ? `。数据目录：${usage.root}` : ""}`
            : "仅桌面版可用"
        }
      >
        <Button variant="destructive" size="sm" disabled={!desktop} onClick={show}>
          删除…
        </Button>
      </Row>

      <Dialog open={open} onOpenChange={(v) => !v && !busy && setOpen(false)}>
        <DialogContent className="sm:max-w-lg" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>删除应用数据</DialogTitle>
            <DialogDescription>
              {step.s === "failed" ? "部分数据没能删除。解析服务已停止，需要重启 FreeRead。" : deleteSummary(scope)}
            </DialogDescription>
          </DialogHeader>

          {step.s === "failed" ? (
            <pre className="text-destructive max-h-[12em] overflow-auto rounded-md border px-3 py-2 text-xs wrap-anywhere whitespace-pre-wrap">
              {step.error}
            </pre>
          ) : (
            <div className="grid gap-3.5 text-sm">
              {SCOPE_ITEMS.map((item) => {
                const id = `delete-${item.key}`;
                const sz = size(item.key);
                return (
                  <div key={item.key} className="flex items-start gap-2.5">
                    <Checkbox
                      id={id}
                      className="mt-0.5"
                      checked={scope[item.key]}
                      disabled={busy}
                      onCheckedChange={(v) => setScope((s) => ({ ...s, [item.key]: v === true }))}
                    />
                    <Label htmlFor={id} className="block min-w-0 font-normal">
                      <b className="font-medium">{item.label}</b>
                      {sz && <span className="text-muted-foreground ml-1.5 text-xs tabular-nums">{sz}</span>}
                      <span className="text-muted-foreground mt-0.5 block text-[12.5px]">{item.desc}</span>
                    </Label>
                  </div>
                );
              })}
              {usage && <p className="text-muted-foreground text-xs wrap-anywhere">数据目录：{usage.root}</p>}
            </div>
          )}

          <DialogFooter>
            {step.s === "failed" ? (
              <Button onClick={restart}>重启 FreeRead</Button>
            ) : (
              <>
                <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button variant="destructive" disabled={busy || nothingSelected(scope)} onClick={() => void run()}>
                  {step.s === "deleting" && <Spinner size={14} className="text-current" />}
                  删除并重启
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Group>
  );
}
