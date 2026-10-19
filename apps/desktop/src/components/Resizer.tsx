// 竖向分隔条：拖动或用 ← / → 调整相邻面板宽度，双击恢复默认。
// 拖动期间给 <body> 加 .resizing：关掉过渡、统一光标、禁止选中文字。

import { useRef } from "react";

interface Props {
  label: string;
  /** 当前宽度（px），即被调整的那个面板的宽度 */
  value: number;
  min: number;
  max: number;
  /** 面板在分隔条右侧时，向左拖是变宽 */
  invert?: boolean;
  onValue: (px: number) => void;
  onReset: () => void;
  className?: string;
}

const STEP = 16;

export function Resizer({ label, value, min, max, invert, onValue, onReset, className }: Props) {
  const drag = useRef<{ x: number; v: number } | null>(null);
  const clamp = (v: number) => Math.round(Math.min(max, Math.max(min, v)));
  const sign = invert ? -1 : 1;

  return (
    <div
      className={["resizer", className].filter(Boolean).join(" ")}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={Math.round(min)}
      aria-valuemax={Math.round(max)}
      tabIndex={0}
      title={`${label}（拖动调整，双击恢复默认）`}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        drag.current = { x: e.clientX, v: value };
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch {
          // 指针已失效（极少见）：仍按普通拖动处理，只是移出分隔条后收不到事件
        }
        document.body.classList.add("resizing");
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d) return;
        onValue(clamp(d.v + sign * (e.clientX - d.x)));
      }}
      onPointerUp={(e) => {
        drag.current = null;
        if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
        document.body.classList.remove("resizing");
      }}
      onLostPointerCapture={() => {
        drag.current = null;
        document.body.classList.remove("resizing");
      }}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        const step = e.shiftKey ? STEP * 4 : STEP;
        if (e.key === "ArrowLeft") onValue(clamp(value - sign * step));
        else if (e.key === "ArrowRight") onValue(clamp(value + sign * step));
        else if (e.key === "Home") onValue(min);
        else if (e.key === "End") onValue(max);
        else if (e.key === "Enter") onReset();
        else return;
        e.preventDefault();
      }}
    />
  );
}
