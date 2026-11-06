import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Select } from "./input";

export const PAGE_SIZES = [10, 25, 50, 100];

export interface PageState {
  page: number; setPage: (n: number) => void;
  size: number; setSize: (n: number) => void;
  total: number; pages: number; from: number; to: number;
}

/**
 * Client-side paging over a list already in memory. Every list endpoint here returns a bounded set
 * (aggregated or capped server-side), so slicing locally keeps filtering instant and the controls identical
 * everywhere. A list that outgrows its server cap needs offset paging in the API instead.
 */
export function usePaged<T>(rows: T[] | undefined, initialSize = 25): PageState & { items: T[] } {
  const all = useMemo(() => rows ?? [], [rows]);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(initialSize);
  const total = all.length;
  const pages = Math.max(1, Math.ceil(total / size));
  // Filtering or reloading can shrink the list under the current page; never strand the user on an empty one.
  useEffect(() => { if (page > pages) setPage(1); }, [pages, page]);
  const current = Math.min(page, pages);
  const start = (current - 1) * size;
  const items = all.slice(start, start + size);
  return {
    items, page: current, setPage, size,
    setSize: (n: number) => { setSize(n); setPage(1); },
    total, pages, from: total ? start + 1 : 0, to: start + items.length,
  };
}

/** Row count, page size and prev/next. Renders nothing when the list is too short to page. */
export function Pagination({ state, label = "rows", className }: { state: PageState; label?: string; className?: string }) {
  const { page, setPage, size, setSize, total, pages, from, to } = state;
  if (total <= PAGE_SIZES[0]) return null;
  return (
    <div className={cn("sticky bottom-0 z-20 mt-3 flex flex-wrap items-center justify-between gap-3 bg-slate-50 py-2 text-xs text-muted-foreground dark:bg-slate-950", className)}>
      <div className="flex items-center gap-2">
        <label htmlFor={`page-size-${label}`}>Per page</label>
        <Select
          id={`page-size-${label}`}
          className="h-7 w-16 py-0 pl-2 pr-7 text-xs shadow-none"
          value={size}
          onChange={(e) => setSize(Number(e.target.value))}
        >
          {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
        </Select>
      </div>
      <div className="tabular-nums">{from}–{to} of {total}</div>
      <div className="flex items-center gap-1">
        <button type="button" className="rounded-md border px-2 py-1 disabled:opacity-40 enabled:hover:bg-slate-100 dark:enabled:hover:bg-slate-800"
          onClick={() => setPage(page - 1)} disabled={page <= 1} aria-label="Previous page">
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="tabular-nums px-1">{page} / {pages}</span>
        <button type="button" className="rounded-md border px-2 py-1 disabled:opacity-40 enabled:hover:bg-slate-100 dark:enabled:hover:bg-slate-800"
          onClick={() => setPage(page + 1)} disabled={page >= pages} aria-label="Next page">
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
