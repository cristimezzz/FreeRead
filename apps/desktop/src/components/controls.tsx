// 常用控件：在 shadcn/ui（components/ui/*）上包一层"选项列表 + 回调"的接口，调用处不用每次拼 Radix 的子组件。见 ADR-0009。

import { type ComponentProps, type ReactNode, useEffect, useId, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { Icon, type IconName } from "./icons";

interface IconButtonProps extends Omit<ComponentProps<typeof Button>, "children" | "size"> {
  icon: IconName;
  label: string;
  /** 选中态（例如当前打开的面板）：强调色浅底 */
  active?: boolean;
  size?: "icon" | "icon-sm" | "icon-xs";
}

/** 只有图标的按钮：label 同时用作 aria-label 和悬停提示。 */
export function IconButton({ icon, label, active, size = "icon-sm", variant = "ghost", className, ...rest }: IconButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant={variant}
          size={size}
          aria-label={label}
          aria-pressed={active}
          className={cn(active && "bg-brand-soft text-brand-ink hover:bg-brand-soft", className)}
          {...rest}
        >
          <Icon name={icon} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

interface OptionToggleProps<T extends string> {
  value: T;
  options: { value: T; label: string }[];
  onValue: (v: T) => void;
  label: string;
  className?: string;
}

/** 分段控件：单选的 ToggleGroup，不允许取消选中。 */
export function OptionToggle<T extends string>(p: OptionToggleProps<T>) {
  return (
    // 外观同 shadcn Tabs 的标签条：浅底槽 + 选中项浮起
    <ToggleGroup
      type="single"
      size="sm"
      aria-label={p.label}
      value={p.value}
      onValueChange={(v) => v && p.onValue(v as T)}
      className={cn("bg-muted text-muted-foreground h-8 rounded-lg p-[3px]", p.className)}
    >
      {p.options.map((o) => (
        <ToggleGroupItem
          key={o.value}
          value={o.value}
          className="hover:text-foreground data-[state=on]:bg-background data-[state=on]:text-foreground dark:data-[state=on]:border-input dark:data-[state=on]:bg-input/30 h-full rounded-md! border border-transparent px-3 text-[13px] hover:bg-transparent data-[state=on]:shadow-sm"
        >
          {o.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

// Radix Select 不接受空字符串作为选项值，内部换成占位值
const EMPTY = "__empty__";

interface OptionSelectProps<T extends string> {
  /** 显示在上方的标签；hideLabel 时只作为 aria-label */
  label: string;
  hideLabel?: boolean;
  value: T;
  options: { value: T; label: string; disabled?: boolean }[];
  onValue: (v: T) => void;
  className?: string;
  disabled?: boolean;
}

export function OptionSelect<T extends string>(p: OptionSelectProps<T>) {
  const id = useId();
  const select = (
    <Select
      value={p.value === "" ? EMPTY : p.value}
      onValueChange={(v) => p.onValue((v === EMPTY ? "" : v) as T)}
      disabled={p.disabled}
    >
      <SelectTrigger
        id={id}
        size="sm"
        aria-label={p.hideLabel ? p.label : undefined}
        className={cn("w-full", p.hideLabel && p.className)}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {p.options.map((o) => (
          <SelectItem key={o.value || EMPTY} value={o.value || EMPTY} disabled={o.disabled}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
  if (p.hideLabel) return select;
  return (
    <Field label={p.label} htmlFor={id} className={p.className}>
      {select}
    </Field>
  );
}

/** 标签 + 控件 + 说明，竖排。 */
export function Field({
  label,
  htmlFor,
  hint,
  className,
  children,
}: {
  label?: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      {label && (
        <Label htmlFor={htmlFor} className="text-muted-foreground text-xs font-medium">
          {label}
        </Label>
      )}
      {children}
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}

interface TextInputProps {
  label: string;
  hideLabel?: boolean;
  value: string;
  onValue: (v: string) => void;
  type?: string;
  placeholder?: string;
  /** 输入框下方的说明 */
  hint?: string;
  className?: string;
  mono?: boolean;
  disabled?: boolean;
  /** 只在失焦 / 回车时提交，而不是每次按键 */
  commitOnChange?: boolean;
}

export function TextInput(p: TextInputProps) {
  const id = useId();
  const [draft, setDraft] = useState(p.value);
  useEffect(() => setDraft(p.value), [p.value]);
  const commit = () => {
    if (draft !== p.value) p.onValue(draft);
  };
  const input = (
    <Input
      id={id}
      className={cn("h-8", p.mono && "font-mono text-[13px]", p.hideLabel && !p.hint && p.className)}
      aria-label={p.hideLabel ? p.label : undefined}
      type={p.type ?? "text"}
      value={p.commitOnChange ? draft : p.value}
      placeholder={p.placeholder}
      disabled={p.disabled}
      spellCheck={false}
      onChange={(e) => (p.commitOnChange ? setDraft(e.target.value) : p.onValue(e.target.value))}
      onBlur={p.commitOnChange ? commit : undefined}
      onKeyDown={p.commitOnChange ? (e) => e.key === "Enter" && commit() : undefined}
    />
  );
  if (p.hideLabel && !p.hint) return input;
  return (
    <Field label={p.hideLabel ? undefined : p.label} htmlFor={id} hint={p.hint} className={p.className}>
      {input}
    </Field>
  );
}

export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <Loader2
      className={cn("text-muted-foreground animate-spin motion-reduce:animate-none", className)}
      size={size}
      role="progressbar"
      aria-label="加载中"
    />
  );
}

interface DialogAction {
  value: string;
  label: string;
  primary?: boolean;
  danger?: boolean;
}

interface ActionDialogProps {
  open: boolean;
  headline: string;
  description?: string;
  /** 按 Esc / 点遮罩关闭时 returnValue 为空 */
  onClose: (returnValue: string) => void;
  children?: ReactNode;
  actions: DialogAction[];
  className?: string;
}

/** 模态对话框：底部一排按钮，点哪个就以它的 value 关闭。 */
export function ActionDialog(p: ActionDialogProps) {
  return (
    <Dialog open={p.open} onOpenChange={(open) => !open && p.onClose("")}>
      <DialogContent className={cn("sm:max-w-lg", p.className)} showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{p.headline}</DialogTitle>
          {p.description && <DialogDescription>{p.description}</DialogDescription>}
        </DialogHeader>
        {p.children && <div className="grid gap-4 text-sm">{p.children}</div>}
        <DialogFooter>
          {p.actions.map((a) => (
            <Button
              key={a.value}
              variant={a.danger ? "destructive" : a.primary ? "default" : "outline"}
              onClick={() => p.onClose(a.value)}
            >
              {a.label}
            </Button>
          ))}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 开关：label 用作 aria-label（旁边的文字说明由调用方给）。 */
export function LabeledSwitch(p: { checked: boolean; onValue: (v: boolean) => void; label: string; id?: string; disabled?: boolean }) {
  return (
    <Switch
      id={p.id}
      aria-label={p.label}
      checked={p.checked}
      disabled={p.disabled}
      onCheckedChange={p.onValue}
      className="data-[state=checked]:bg-brand"
    />
  );
}

/** 线性进度条；value 为 0–1，省略时为不确定进度。 */
export function ProgressBar({ value, className }: { value?: number | null; className?: string }) {
  return <Progress className={className} value={value == null ? null : Math.max(0, Math.min(1, value)) * 100} />;
}
