// AI Elements 的 Queue（分组的任务列表）。去掉了附件、待办消息类型和 ScrollArea（滚动由调用方的容器负责）。

import { ChevronDownIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export const Queue = ({ className, ...props }: ComponentProps<"div">) => (
  <div className={cn("flex flex-col gap-1", className)} {...props} />
);

export const QueueSection = ({ className, defaultOpen = true, ...props }: ComponentProps<typeof Collapsible>) => (
  <Collapsible className={cn(className)} defaultOpen={defaultOpen} {...props} />
);

export const QueueSectionTrigger = ({ children, className, ...props }: ComponentProps<"button">) => (
  <CollapsibleTrigger asChild>
    <button
      className={cn(
        "group flex w-full cursor-pointer items-center justify-between rounded-md bg-muted/40 px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted",
        className,
      )}
      type="button"
      {...props}
    >
      {children}
    </button>
  </CollapsibleTrigger>
);

export const QueueSectionLabel = ({
  count,
  label,
  icon,
  className,
  ...props
}: ComponentProps<"span"> & { count?: number; label: string; icon?: ReactNode }) => (
  <span className={cn("flex items-center gap-2", className)} {...props}>
    <ChevronDownIcon className="size-4 transition-transform group-data-[state=closed]:-rotate-90" />
    {icon}
    <span>
      {label}
      {count !== undefined && ` ${count}`}
    </span>
  </span>
);

export const QueueSectionContent = ({ className, ...props }: ComponentProps<typeof CollapsibleContent>) => (
  <CollapsibleContent className={cn(className)} {...props} />
);

export const QueueList = ({ className, ...props }: ComponentProps<"ul">) => (
  <ul className={cn("mt-1", className)} {...props} />
);

export const QueueItem = ({ className, ...props }: ComponentProps<"li">) => (
  <li
    className={cn("group flex flex-col gap-1 rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-muted", className)}
    {...props}
  />
);

export const QueueItemIndicator = ({
  completed = false,
  className,
  ...props
}: ComponentProps<"span"> & { completed?: boolean }) => (
  <span
    className={cn(
      "mt-1 inline-block size-2.5 flex-none rounded-full border",
      completed ? "border-muted-foreground/20 bg-muted-foreground/10" : "border-muted-foreground/50",
      className,
    )}
    {...props}
  />
);

export const QueueItemContent = ({
  completed = false,
  className,
  ...props
}: ComponentProps<"span"> & { completed?: boolean }) => (
  <span
    className={cn(
      "line-clamp-1 grow break-words",
      completed ? "text-muted-foreground/50 line-through" : "text-foreground/80",
      className,
    )}
    {...props}
  />
);

export const QueueItemDescription = ({
  completed = false,
  className,
  ...props
}: ComponentProps<"div"> & { completed?: boolean }) => (
  <div
    className={cn("ml-[1.125rem] text-xs", completed ? "text-muted-foreground/40 line-through" : "text-muted-foreground", className)}
    {...props}
  />
);
