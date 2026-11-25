import { useRef, type ReactNode } from "react";

export function TableScroll({ label, html, children }: { label: string; html?: string; children?: ReactNode }) {
  const drag = useRef<{ id: number; x: number; y: number; left: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);

  return (
    <div
      className="rf-table"
      role="region"
      aria-label={label}
      tabIndex={0}
      onPointerDown={(e) => {
        suppressClick.current = false;
        const el = e.currentTarget;
        if (e.pointerType !== "mouse" || e.button !== 0 || e.shiftKey || el.scrollWidth <= el.clientWidth) return;
        // Leave the native scrollbar's own drag behavior alone.
        if (e.clientY >= el.getBoundingClientRect().top + el.clientHeight) return;
        drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, left: el.scrollLeft, moved: false };
      }}
      onPointerMove={(e) => {
        const state = drag.current;
        if (!state || state.id !== e.pointerId) return;
        const el = e.currentTarget;
        const dx = e.clientX - state.x;
        if (!state.moved) {
          const dy = Math.abs(e.clientY - state.y);
          if (dy > 5 && dy > Math.abs(dx)) {
            drag.current = null;
            return;
          }
          if (Math.abs(dx) < 5) return;
          el.setPointerCapture(e.pointerId);
          el.dataset.dragging = "";
          state.moved = true;
          suppressClick.current = true;
          const selection = window.getSelection();
          if (el.contains(selection?.anchorNode ?? null)) selection?.removeAllRanges();
        }
        e.preventDefault();
        el.scrollLeft = state.left - dx;
      }}
      onPointerUp={() => { drag.current = null; }}
      onPointerLeave={() => { if (!drag.current?.moved) drag.current = null; }}
      onPointerCancel={(e) => {
        drag.current = null;
        delete e.currentTarget.dataset.dragging;
      }}
      onLostPointerCapture={(e) => {
        drag.current = null;
        delete e.currentTarget.dataset.dragging;
      }}
      onClickCapture={(e) => {
        if (!suppressClick.current) return;
        suppressClick.current = false;
        e.stopPropagation();
      }}
      onDragStart={(e) => e.preventDefault()}
      dangerouslySetInnerHTML={html === undefined ? undefined : { __html: html }}
    >
      {children}
    </div>
  );
}
