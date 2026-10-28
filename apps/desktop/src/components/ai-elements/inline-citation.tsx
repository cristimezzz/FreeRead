// AI Elements 的 InlineCitation 悬浮卡部分。原版的轮播（embla）和"来源 URL 徽章"用不上：
// 触发器由调用方自己画（components/Citation.tsx 的编号小标），这里只提供悬浮卡与引文样式。

import type { ComponentProps } from "react";
import { HoverCard, HoverCardContent } from "@/components/ui/hover-card";
import { cn } from "@/lib/utils";

export const InlineCitationCard = (props: ComponentProps<typeof HoverCard>) => (
  <HoverCard closeDelay={80} openDelay={120} {...props} />
);

export const InlineCitationCardBody = ({ className, ...props }: ComponentProps<typeof HoverCardContent>) => (
  <HoverCardContent className={cn("relative w-80 p-3", className)} {...props} />
);

export const InlineCitationQuote = ({ className, ...props }: ComponentProps<"blockquote">) => (
  <blockquote
    className={cn("border-brand border-l-2 pl-3 text-sm leading-relaxed text-muted-foreground", className)}
    {...props}
  />
);
