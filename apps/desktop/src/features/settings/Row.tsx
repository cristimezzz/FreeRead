// 设置项的布局：分组（带锚点 id 的 section）、一行（标题、说明、控件）、卡片、说明文字。欢迎向导也用。

import { type ComponentProps, type ReactNode, useState } from "react";
import { Icon } from "../../components/icons";
import { Card } from "../../components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../components/ui/collapsible";
import { Label } from "../../components/ui/label";
import { cn } from "../../lib/utils";

/** 设置项一行：左边标题与说明，右边控件。 */
export function Row({ title, desc, htmlFor, children }: { title: ReactNode; desc?: ReactNode; htmlFor?: string; children?: ReactNode }) {
  const k = (
    <>
      <b className="block text-sm font-medium">{title}</b>
      {desc && <span className="text-muted-foreground mt-0.5 block text-[12.5px] font-normal">{desc}</span>}
    </>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b py-3.5">
      {htmlFor ? (
        <Label className="block min-w-0 flex-[1_1_220px]" htmlFor={htmlFor}>
          {k}
        </Label>
      ) : (
        <div className="min-w-0 flex-[1_1_220px]">{k}</div>
      )}
      {children && <div className="flex flex-[0_1_auto] flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/**
 * 分组里次要的设置项，默认折叠。defaultOpen 只决定初始状态（例如里面有改过的值时展开），
 * 之后由用户开合，不随设置变化自动收起。
 */
export function More({
  label = "更多选项",
  defaultOpen = false,
  children,
}: {
  label?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="group/more text-foreground/80 hover:text-foreground focus-visible:outline-ring mt-2.5 inline-flex items-center gap-1 rounded-md py-1 pr-2 pl-0.5 text-[13px] transition-colors select-none focus-visible:outline-2 focus-visible:outline-offset-2">
        <Icon name="chevronRight" className="transition-transform group-data-[state=open]/more:rotate-90" />
        {label}
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}

export function Group({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="mt-9 scroll-mt-6" id={id} aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="mb-1 font-serif text-xl font-medium">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** 分组或卡片里的说明文字。 */
export function Hint({ className, ...rest }: ComponentProps<"p">) {
  return <p className={cn("text-muted-foreground mt-2 mb-1 text-[12.5px] leading-relaxed", className)} {...rest} />;
}

/** 设置页里的卡片（服务商、解析服务等）。 */
export function Panel({ className, ...rest }: ComponentProps<"div">) {
  return <Card className={cn("mt-3.5 gap-0 px-5 py-4.5 shadow-none", className)} {...rest} />;
}

/** 卡片里两列的输入框网格；窄窗口一列。 */
export function FieldGrid({ className, ...rest }: ComponentProps<"div">) {
  return <div className={cn("mt-3.5 grid grid-cols-2 gap-x-4 gap-y-3 max-[560px]:grid-cols-1", className)} {...rest} />;
}

/** 连接状态：小圆点 + 文字。 */
export function ConnState({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", ok ? "text-success" : "text-destructive")}>
      <i className="block size-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}
