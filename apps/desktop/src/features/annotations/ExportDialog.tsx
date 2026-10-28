// 导出 Markdown：桌面版用保存对话框选路径，由 Core 写文件；浏览器开发模式直接下载。

import { useState } from "react";
import { api, rawFetch, unwrap } from "../../api/client";
import { isTauri } from "../../api/core";
import { useApp } from "../../app/store";
import { ActionDialog, LabeledSwitch, OptionSelect } from "../../components/controls";

type Layout = "off" | "below" | "only";

interface Props {
  open: boolean;
  docId: string;
  title: string;
  lang: string;
  onClose: () => void;
}

/** 文件名里不能有的字符换成空格，太长截断。 */
export function safeFileName(title: string): string {
  const name = title.replace(/[\\/:*?"<>|\r\n\t]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80);
  return `${name || "FreeRead 导出"}.md`;
}

const ROW = "flex min-h-10 items-center justify-between gap-4";

export function ExportDialog({ open, docId, title, lang, onClose }: Props) {
  const toast = useApp((s) => s.toast);
  const [opts, setOpts] = useState({ summary: true, annotations: true, body: true, qa: false });
  const [translation, setTranslation] = useState<Layout>("below");

  const run = async () => {
    const options = { ...opts, translation, lang };
    try {
      if (isTauri()) {
        const { save } = await import("@tauri-apps/plugin-dialog");
        const path = await save({ defaultPath: safeFileName(title), filters: [{ name: "Markdown", extensions: ["md"] }] });
        if (!path) return;
        unwrap(
          await api().POST("/documents/{doc_id}/export/markdown", {
            params: { path: { doc_id: docId } },
            body: { ...options, path },
          }),
        );
        toast(`已导出到 ${path}`);
      } else {
        const query = new URLSearchParams(Object.entries(options).map(([k, v]) => [k, String(v)]));
        const text = await (await rawFetch(`/documents/${docId}/export/markdown?${query}`)).text();
        const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = safeFileName(title);
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        toast("已导出 Markdown");
      }
    } catch (e) {
      toast(`导出失败：${e instanceof Error ? e.message : e}`);
    }
  };

  const toggle = (key: keyof typeof opts, label: string) => (
    <label className={ROW}>
      <span>{label}</span>
      <LabeledSwitch label={label} checked={opts[key]} onValue={(v) => setOpts((o) => ({ ...o, [key]: v }))} />
    </label>
  );

  return (
    <ActionDialog
      open={open}
      headline="导出 Markdown"
      onClose={(v) => {
        onClose();
        if (v === "ok") void run();
      }}
      actions={[
        { value: "cancel", label: "取消" },
        { value: "ok", label: "导出", primary: true },
      ]}
    >
      <div className="flex min-w-80 flex-col gap-1">
        {toggle("summary", "总结")}
        {toggle("annotations", "高亮与批注")}
        {toggle("body", "正文")}
        <div className={ROW}>
          <span>译文</span>
          <OptionSelect
            className="w-40"
            label="译文"
            hideLabel
            value={translation}
            options={[
              { value: "below", label: "放在原文下面" },
              { value: "only", label: "只要译文" },
              { value: "off", label: "不要译文" },
            ]}
            onValue={setTranslation}
          />
        </div>
        {toggle("qa", "问答记录")}
        <p className="text-muted-foreground mt-2 text-[12.5px] leading-relaxed">
          引用会换成页码，公式保留为 LaTeX，高亮写成 ==文字==（Obsidian、Typora 可显示）。
        </p>
      </div>
    </ActionDialog>
  );
}
