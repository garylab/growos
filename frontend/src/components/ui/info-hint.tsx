import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A small info (ⓘ) icon that reveals an explanation when clicked. Closes on outside click or Escape.
 * `hover` additionally opens it on pointer-over (click still toggles, so touch devices keep working);
 * `icon` and `tone` let a caller swap in a status glyph, e.g. a pass/fail marker on a test result.
 *
 * The panel is rendered into document.body with fixed positioning: hints live inside tables, and `Table`
 * wraps its rows in `overflow-auto`, which would clip a panel opened from one of the last rows.
 */
export function InfoHint({ children, label = "More information", className, width = "w-64", icon, tone, hover = false }:
  { children: ReactNode; label?: string; className?: string; width?: string; icon?: ReactNode; tone?: string; hover?: boolean }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLSpanElement>(null);
  // A hint near any edge — a left-aligned page title, a right-hand number, a row at the bottom of a long table —
  // would otherwise overflow the window. Measured once per open, before paint, in viewport coordinates: we clamp
  // horizontally and flip above the anchor when there is no room below. The panel's size does not depend on the
  // position we compute, so the measurement is stable and cannot loop.
  useLayoutEffect(() => {
    if (!open) { setPos(null); return; }
    const wrap = ref.current?.getBoundingClientRect();
    const box = panel.current?.getBoundingClientRect();
    if (!wrap || !box) return;
    const margin = 8;
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const left = Math.min(Math.max(wrap.left, margin), Math.max(margin, vw - margin - box.width));
    const below = wrap.bottom + 6;
    const top = below + box.height > vh - margin ? Math.max(margin, wrap.top - 6 - box.height) : below;
    setPos({ top, left });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    // The panel is portaled, so it is not a descendant of `ref`: check it separately or clicking the text closes it.
    const onDoc = (e: MouseEvent | PointerEvent | FocusEvent) => {
      const t = e.target as Node;
      if (!ref.current?.contains(t) && !panel.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    // Fixed positioning is measured once, so scrolling would leave the panel behind: close it instead.
    const onScroll = () => setOpen(false);
    document.addEventListener("pointerdown", onDoc);
    document.addEventListener("focusin", onDoc);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("focusin", onDoc);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);
  return (
    <span ref={ref} className={cn("relative inline-flex align-middle", className)}
      onMouseEnter={hover ? () => setOpen(true) : undefined} onMouseLeave={hover ? () => setOpen(false) : undefined}>
      <button type="button" aria-label={label} aria-expanded={open} onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}
        className={cn(tone ?? "text-muted-foreground hover:text-foreground focus-visible:text-foreground", "focus-visible:outline-none", open && !tone && "text-foreground")}>
        {icon ?? <Info className="h-3.5 w-3.5" />}
      </button>
      {open && createPortal(
        // Hidden until measured so it never paints at the wrong place; hovering the panel itself keeps it open so
        // long error text stays selectable.
        <span ref={panel} role="tooltip" style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden" }}
          onMouseEnter={hover ? () => setOpen(true) : undefined} onMouseLeave={hover ? () => setOpen(false) : undefined}
          className={cn("fixed z-50 max-w-[calc(100vw-1rem)] rounded-md border bg-white dark:bg-slate-900 p-2.5 text-xs font-normal normal-case tracking-normal text-muted-foreground shadow-lg", width)}>
          {children}
        </span>, document.body)}
    </span>
  );
}
