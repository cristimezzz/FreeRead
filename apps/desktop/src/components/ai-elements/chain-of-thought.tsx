// AI Elements 的 ChainOfThought（可折叠的分步进度）。去掉了图片和搜索结果徽章，
// 展开状态改用 useState 受控（原版靠 @radix-ui/react-use-controllable-state）。

import type { LucideIcon } from "lucide-react";
import { BrainIcon, ChevronDownIcon, DotIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { createContext, memo, useContext, useMemo, useState } from "react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

interface Ctx {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
}
const ChainOfThoughtContext = createContext<Ctx | null>(null);
const useChainOfThought = () => {
  const ctx = useContext(ChainOfThoughtContext);
  if (!ctx) throw new Error("ChainOfThought components must be used within ChainOfThought");
  return ctx;
};

export type ChainOfThoughtProps = ComponentProps<"div"> & {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

export const ChainOfThought = memo(
  ({ className, open, defaultOpen = false, onOpenChange, ...props }: ChainOfThoughtProps) => {
    const [inner, setInner] = useState(defaultOpen);
    const isOpen = open ?? inner;
    const value = useMemo<Ctx>(
      () => ({
        isOpen,
        setIsOpen: (v) => {
          setInner(v);
          onOpenChange?.(v);
        },
      }),
      [isOpen, onOpenChange],
    );
    return (
      <ChainOfThoughtContext.Provider value={value}>
        <div className={cn("w-full space-y-3", className)} {...props} />
      </ChainOfThoughtContext.Provider>
    );
  },
);

export const ChainOfThoughtHeader = memo(
  ({ className, children, ...props }: ComponentProps<typeof CollapsibleTrigger>) => {
    const { isOpen, setIsOpen } = useChainOfThought();
    return (
      <Collapsible onOpenChange={setIsOpen} open={isOpen}>
        <CollapsibleTrigger
          className={cn(
            "flex w-full cursor-pointer items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground",
            className,
          )}
          {...props}
        >
          <BrainIcon className="size-4" />
          <span className="flex-1 text-left">{children}</span>
          <ChevronDownIcon className={cn("size-4 transition-transform", isOpen ? "rotate-180" : "rotate-0")} />
        </CollapsibleTrigger>
      </Collapsible>
    );
  },
);

export type ChainOfThoughtStepProps = ComponentProps<"div"> & {
  icon?: LucideIcon;
  label: ReactNode;
  description?: ReactNode;
  status?: "complete" | "active" | "pending";
};

const stepStatusStyles = {
  active: "text-foreground",
  complete: "text-muted-foreground",
  pending: "text-muted-foreground/50",
};

export const ChainOfThoughtStep = memo(
  ({ className, icon: Icon = DotIcon, label, description, status = "complete", children, ...props }: ChainOfThoughtStepProps) => (
    <div
      className={cn("flex gap-2 text-sm", stepStatusStyles[status], "fade-in-0 slide-in-from-top-2 animate-in", className)}
      {...props}
    >
      <div className="relative mt-0.5">
        <Icon className="size-4" />
        <div className="absolute top-7 bottom-0 left-1/2 -mx-px w-px bg-border" />
      </div>
      <div className="flex-1 space-y-1 overflow-hidden">
        <div>{label}</div>
        {description && <div className="text-xs text-muted-foreground">{description}</div>}
        {children}
      </div>
    </div>
  ),
);

export const ChainOfThoughtContent = memo(({ className, ...props }: ComponentProps<typeof CollapsibleContent>) => {
  const { isOpen } = useChainOfThought();
  return (
    <Collapsible open={isOpen}>
      <CollapsibleContent
        className={cn(
          "mt-2 space-y-3 text-popover-foreground outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:slide-in-from-top-2",
          className,
        )}
        {...props}
      />
    </Collapsible>
  );
});

ChainOfThought.displayName = "ChainOfThought";
ChainOfThoughtHeader.displayName = "ChainOfThoughtHeader";
ChainOfThoughtStep.displayName = "ChainOfThoughtStep";
ChainOfThoughtContent.displayName = "ChainOfThoughtContent";
