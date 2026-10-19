// 小组件：原生元素 + global.css 里的令牌（ADR-0007）。可访问性与键盘操作交给浏览器。

import { type ButtonHTMLAttributes, type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Icon, type IconName } from "./icons";
import { exitMs } from "./motion";

type ButtonVariant = "primary" | "default" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  icon?: IconName;
  /** 小号（34px）用于工具栏、面板、设置；默认 36px */
  small?: boolean;
  danger?: boolean;
  /** 开关型按钮（阅读器的 搜索 / 总结 / 问答）：按下时用强调色浅底 */
  pressed?: boolean;
}

export function Button({ variant = "default", icon, small, danger, pressed, className, children, ...rest }: ButtonProps) {
  const cls = ["btn", variant !== "default" && variant, small && "sm", danger && "danger", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button type="button" className={cls} aria-pressed={pressed} {...rest}>
      {icon && <Icon name={icon} />}
      {children}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  label: string;
  active?: boolean;
}

export function IconButton({ icon, label, active, className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      className={["ibtn", active && "on", className].filter(Boolean).join(" ")}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  );
}

interface SegmentedProps<T extends string> {
  value: T;
  options: { value: T; label: string }[];
  onValue: (v: T) => void;
  label: string;
}

/** 分段控件：一组 aria-pressed 按钮；选中底块是一个单独的元素，切换时滑过去。 */
export function Segmented<T extends string>(p: SegmentedProps<T>) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const place = () => {
      const on = el.querySelector<HTMLElement>('button[aria-pressed="true"]');
      if (!on || !on.offsetWidth) {
        el.removeAttribute("data-ready");
        return;
      }
      el.style.setProperty("--seg-x", `${on.offsetLeft}px`);
      el.style.setProperty("--seg-w", `${on.offsetWidth}px`);
      el.dataset.ready = "";
    };
    place();
    // 字体加载完、窗口缩放后按钮宽度会变
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [p.value, p.options.length]);
  return (
    <div className="seg" role="group" aria-label={p.label} ref={ref}>
      <span className="seg-thumb" aria-hidden="true" />
      {p.options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === p.value} onClick={() => p.onValue(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Switch(p: { checked: boolean; onValue: (v: boolean) => void; label: string; id?: string }) {
  return (
    <input
      id={p.id}
      className="switch"
      type="checkbox"
      role="switch"
      aria-label={p.label}
      checked={p.checked}
      onChange={(e) => p.onValue(e.target.checked)}
    />
  );
}

interface SelectProps<T extends string> {
  /** 显示在上方的标签；hideLabel 时只作为 aria-label */
  label: string;
  hideLabel?: boolean;
  value: T;
  options: { value: T; label: string; disabled?: boolean }[];
  onValue: (v: T) => void;
  className?: string;
}

export function Select<T extends string>(p: SelectProps<T>) {
  const select = (
    <select
      className={p.hideLabel ? p.className : undefined}
      aria-label={p.hideLabel ? p.label : undefined}
      value={p.value}
      onChange={(e) => p.onValue(e.target.value as T)}
    >
      {p.options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
  if (p.hideLabel) return select;
  return (
    <label className={["fld", p.className].filter(Boolean).join(" ")}>
      {p.label}
      {select}
    </label>
  );
}

interface TextFieldProps {
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

export function TextField(p: TextFieldProps) {
  const [draft, setDraft] = useState(p.value);
  useEffect(() => setDraft(p.value), [p.value]);
  const commit = () => {
    if (draft !== p.value) p.onValue(draft);
  };
  const input = (
    <input
      className={["inp", p.mono && "mono", p.hideLabel && p.className].filter(Boolean).join(" ")}
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
    <label className={["fld", p.className].filter(Boolean).join(" ")}>
      {!p.hideLabel && p.label}
      {input}
      {p.hint && <span className="fld-hint">{p.hint}</span>}
    </label>
  );
}

/** 线性进度条；value 为 0–1，省略时为不确定进度。 */
export function Progress({ value, className }: { value?: number; className?: string }) {
  const indeterminate = value == null;
  return (
    <span
      className={["bar", indeterminate && "indeterminate", className].filter(Boolean).join(" ")}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(value * 100)}
    >
      <i style={indeterminate ? undefined : { width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </span>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} role="progressbar" aria-label="加载中" />;
}

interface DialogAction {
  value: string;
  label: string;
  primary?: boolean;
}

interface DialogProps {
  open: boolean;
  headline: string;
  /** 按 Esc / 点遮罩关闭时 returnValue 为空 */
  onClose: (returnValue: string) => void;
  children: ReactNode;
  actions: DialogAction[];
}

/** 模态对话框：原生 <dialog>，showModal 提供焦点陷阱与 Esc 关闭。 */
export function Dialog(p: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const onClose = useRef(p.onClose);
  onClose.current = p.onClose;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (p.open && !el.open) el.showModal?.();
    if (!p.open && el.open) el.close();
  }, [p.open]);

  const closing = useRef(false);
  // 先播放退出动画（data-state="closing"），再真正关闭
  const finish = (value: string) => {
    const el = ref.current;
    if (closing.current) return;
    const done = () => {
      closing.current = false;
      if (el) delete el.dataset.state;
      el?.close();
      onClose.current(value);
    };
    const ms = exitMs();
    if (!el || !ms) return done();
    closing.current = true;
    el.dataset.state = "closing";
    setTimeout(done, ms);
  };

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        finish("");
      }}
      onClick={(e) => {
        if (e.target === ref.current) finish("");
      }}
    >
      <h2 id={titleId} className="serif">
        {p.headline}
      </h2>
      <div className="dialog-body">{p.children}</div>
      <div className="dialog-actions">
        {p.actions.map((a) => (
          <Button key={a.value} variant={a.primary ? "primary" : "ghost"} onClick={() => finish(a.value)}>
            {a.label}
          </Button>
        ))}
      </div>
    </dialog>
  );
}
