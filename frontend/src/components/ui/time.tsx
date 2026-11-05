import { useEffect, useReducer } from "react";
import { fmtAbsolute, fmtRelative, parseUtc } from "@/lib/time";

// One timer for every relative timestamp on the page, so "3 mins ago" stays true without a timer per row.
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(cb: () => void) {
  listeners.add(cb);
  timer ??= setInterval(() => listeners.forEach((l) => l()), 30_000);
  return () => {
    listeners.delete(cb);
    if (listeners.size === 0 && timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

/** A timestamp shown as "3 mins ago", with the full local date and time on hover. */
export function TimeAgo({ value, fallback = "—", className }: { value: string | null | undefined; fallback?: string; className?: string }) {
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => subscribe(tick), []);
  const d = parseUtc(value);
  if (!d) return <>{fallback}</>;
  return <time dateTime={d.toISOString()} title={fmtAbsolute(value)} className={className}>{fmtRelative(value)}</time>;
}
