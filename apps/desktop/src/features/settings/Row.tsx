// 设置项的布局：分组（带锚点 id 的 section）与一行（标题、说明、控件）。欢迎向导也用。

import { type ReactNode, useState } from "react";
import { Icon } from "../../components/icons";

/** 设置项一行：左边标题与说明，右边控件。 */
export function Row({ title, desc, htmlFor, children }: { title: ReactNode; desc?: ReactNode; htmlFor?: string; children?: ReactNode }) {
  const k = (
    <>
      <b>{title}</b>
      {desc && <span>{desc}</span>}
    </>
  );
  return (
    <div className="set-row">
      {htmlFor ? (
        <label className="k" htmlFor={htmlFor}>
          {k}
        </label>
      ) : (
        <div className="k">{k}</div>
      )}
      {children && <div className="v">{children}</div>}
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
    <details className="set-more" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <Icon name="chevronRight" size={16} />
        {label}
      </summary>
      {open && children}
    </details>
  );
}

export function Group({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="set-group" id={id} aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="serif">
        {title}
      </h2>
      {children}
    </section>
  );
}
