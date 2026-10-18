// @material/web 组件的注册、JSX 类型声明与少量受控封装（ADR-0006）。
// React 19 会把 props 设为自定义元素的属性；事件统一用 addEventListener 绑定，
// 不依赖 React 对自定义元素事件名的推断。

import "@material/web/button/filled-button.js";
import "@material/web/button/filled-tonal-button.js";
import "@material/web/button/outlined-button.js";
import "@material/web/button/text-button.js";
import "@material/web/chips/chip-set.js";
import "@material/web/chips/filter-chip.js";
import "@material/web/dialog/dialog.js";
import "@material/web/divider/divider.js";
import "@material/web/iconbutton/icon-button.js";
import "@material/web/labs/segmentedbutton/outlined-segmented-button.js";
import "@material/web/labs/segmentedbuttonset/outlined-segmented-button-set.js";
import "@material/web/list/list-item.js";
import "@material/web/list/list.js";
import "@material/web/progress/circular-progress.js";
import "@material/web/progress/linear-progress.js";
import "@material/web/select/outlined-select.js";
import "@material/web/select/select-option.js";
import "@material/web/slider/slider.js";
import "@material/web/switch/switch.js";
import "@material/web/textfield/outlined-text-field.js";

import { type ReactNode, type RefObject, useEffect, useRef } from "react";

type MdElementProps = React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
  [prop: string]: unknown;
};

declare module "react" {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "md-filled-button": MdElementProps;
      "md-filled-tonal-button": MdElementProps;
      "md-outlined-button": MdElementProps;
      "md-text-button": MdElementProps;
      "md-icon-button": MdElementProps;
      "md-chip-set": MdElementProps;
      "md-filter-chip": MdElementProps;
      "md-dialog": MdElementProps;
      "md-divider": MdElementProps;
      "md-list": MdElementProps;
      "md-list-item": MdElementProps;
      "md-circular-progress": MdElementProps;
      "md-linear-progress": MdElementProps;
      "md-outlined-select": MdElementProps;
      "md-select-option": MdElementProps;
      "md-slider": MdElementProps;
      "md-switch": MdElementProps;
      "md-outlined-text-field": MdElementProps;
      "md-outlined-segmented-button": MdElementProps;
      "md-outlined-segmented-button-set": MdElementProps;
    }
  }
}

export function useDomEvent<E extends Event>(
  ref: RefObject<HTMLElement | null>,
  name: string,
  handler: (e: E) => void,
) {
  const saved = useRef(handler);
  saved.current = handler;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const listener = (e: Event) => saved.current(e as E);
    el.addEventListener(name, listener);
    return () => el.removeEventListener(name, listener);
  }, [ref, name]);
}

interface TextFieldProps {
  label: string;
  value: string;
  onValue: (v: string) => void;
  type?: string;
  placeholder?: string;
  supportingText?: string;
  className?: string;
  disabled?: boolean;
  /** 只在失焦 / 回车时提交（change 事件），而不是每次按键 */
  commitOnChange?: boolean;
  children?: ReactNode;
}

export function TextField(p: TextFieldProps) {
  const ref = useRef<HTMLElement & { value: string }>(null);
  useDomEvent(ref, p.commitOnChange ? "change" : "input", () => p.onValue(ref.current?.value ?? ""));
  return (
    <md-outlined-text-field
      ref={ref}
      label={p.label}
      value={p.value}
      type={p.type ?? "text"}
      placeholder={p.placeholder ?? ""}
      supporting-text={p.supportingText ?? ""}
      class={p.className}
      disabled={p.disabled || undefined}
    >
      {p.children}
    </md-outlined-text-field>
  );
}

interface SelectProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string; disabled?: boolean }[];
  onValue: (v: T) => void;
  className?: string;
}

export function Select<T extends string>(p: SelectProps<T>) {
  const ref = useRef<HTMLElement & { value: string }>(null);
  useDomEvent(ref, "change", () => p.onValue((ref.current?.value ?? "") as T));
  return (
    <md-outlined-select ref={ref} label={p.label} value={p.value} class={p.className}>
      {p.options.map((o) => (
        <md-select-option
          key={o.value}
          value={o.value}
          selected={o.value === p.value || undefined}
          disabled={o.disabled || undefined}
        >
          <div slot="headline">{o.label}</div>
        </md-select-option>
      ))}
    </md-outlined-select>
  );
}

export function Switch(p: { selected: boolean; onValue: (v: boolean) => void; label: string }) {
  const ref = useRef<HTMLElement & { selected: boolean }>(null);
  useDomEvent(ref, "change", () => p.onValue(Boolean(ref.current?.selected)));
  return (
    <label className="switch-row">
      <span>{p.label}</span>
      <md-switch ref={ref} selected={p.selected || undefined} aria-label={p.label} />
    </label>
  );
}

interface SegmentedProps<T extends string> {
  value: T;
  options: { value: T; label: string }[];
  onValue: (v: T) => void;
  label: string;
}

export function Segmented<T extends string>(p: SegmentedProps<T>) {
  const ref = useRef<HTMLElement>(null);
  useDomEvent<CustomEvent<{ button: HTMLElement }>>(ref, "segmented-button-set-selection", (e) => {
    const v = e.detail?.button?.dataset.value as T | undefined;
    if (v) p.onValue(v);
  });
  return (
    <md-outlined-segmented-button-set ref={ref} aria-label={p.label}>
      {p.options.map((o) => (
        <md-outlined-segmented-button
          key={o.value}
          data-value={o.value}
          label={o.label}
          selected={o.value === p.value || undefined}
          no-checkmark
        />
      ))}
    </md-outlined-segmented-button-set>
  );
}

interface DialogAction {
  value: string;
  label: string;
  primary?: boolean;
}

interface DialogProps {
  open: boolean;
  headline: string;
  onClose: (returnValue: string) => void;
  children: ReactNode;
  actions: DialogAction[];
}

/**
 * 按钮不用 form 属性提交（React 会去设置自定义元素只读的 form 属性而报错），
 * 而是直接调用 md-dialog 的 close(returnValue)。按 Esc / 点遮罩关闭时 returnValue 为空。
 */
export function Dialog(p: DialogProps) {
  const ref = useRef<HTMLElement & { returnValue: string; close: (v?: string) => void }>(null);
  useDomEvent(ref, "closed", () => p.onClose(ref.current?.returnValue ?? ""));
  return (
    <md-dialog ref={ref} open={p.open || undefined}>
      <div slot="headline">{p.headline}</div>
      <div slot="content">{p.children}</div>
      <div slot="actions">
        {p.actions.map((a) =>
          a.primary ? (
            <md-filled-button key={a.value} onClick={() => ref.current?.close(a.value)}>
              {a.label}
            </md-filled-button>
          ) : (
            <md-text-button key={a.value} onClick={() => ref.current?.close(a.value)}>
              {a.label}
            </md-text-button>
          ),
        )}
      </div>
    </md-dialog>
  );
}
