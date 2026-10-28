// 解析状态标签：小圆点 + 文字。可阅读用成功色，解析中用强调色浅底，失败用危险色，没有 PDF 用虚线框。

import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export type TagStatus = "pending" | "parsing" | "ready" | "failed" | "none" | (string & {});

const TONE: Record<string, string> = {
  ready: "text-success",
  parsing: "border-transparent bg-brand-soft text-brand-ink",
  failed: "text-destructive",
  none: "border-dashed",
};

export function tagClass(status: TagStatus, className?: string) {
  return cn(
    "text-muted-foreground inline-flex h-6 items-center gap-1.5 rounded-md border px-2 text-xs font-medium whitespace-nowrap",
    TONE[status],
    className,
  );
}

export function TagDot() {
  return <span className="size-1.5 flex-none rounded-full bg-current" />;
}

export function StatusTag({ status, className, children, ...rest }: ComponentProps<"span"> & { status: TagStatus }) {
  return (
    <span className={tagClass(status, className)} data-status={status} {...rest}>
      <TagDot />
      {children}
    </span>
  );
}
