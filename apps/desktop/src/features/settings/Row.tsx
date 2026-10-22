// 设置项的布局：分组（带锚点 id 的 section）与一行（标题、说明、控件）。欢迎向导也用。

import type { ReactNode } from "react";

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
