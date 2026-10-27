// 阅读器右侧面板的外壳：标题行（衬线标题 + 操作按钮）、说明文字、底栏。搜索 / 总结 / 术语 / 图谱 / 批注共用。

import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function SidePanel({
  title,
  actions,
  className,
  children,
  ...rest
}: Omit<ComponentProps<"aside">, "title"> & { title: ReactNode; actions?: ReactNode }) {
  return (
    <aside className={cn("bg-background flex min-h-0 min-w-0 flex-1 flex-col", className)} {...rest}>
      <div className="flex items-center gap-1 pt-3.5 pr-3 pb-2.5 pl-6">
        <h2 className="flex-1 font-serif text-xl font-medium">{title}</h2>
        {actions}
      </div>
      {children}
    </aside>
  );
}

/** 面板里的提示 / 错误文字。 */
export function PanelNote({ error, className, ...rest }: ComponentProps<"p"> & { error?: boolean }) {
  return (
    <p
      className={cn(
        "mx-6 mt-1 mb-2 text-[12.5px] leading-relaxed",
        error ? "text-destructive" : "text-muted-foreground",
        className,
      )}
      {...rest}
    />
  );
}

/** 面板底栏：统计、次要操作。 */
export function PanelFoot({ className, ...rest }: ComponentProps<"div">) {
  return <div className={cn("text-muted-foreground flex flex-wrap gap-2 border-t px-6 py-3 text-xs", className)} {...rest} />;
}
