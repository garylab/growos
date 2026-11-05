/** Time formatting. The API always sends UTC; everything here renders in the browser's own timezone. */

const MIN = 60_000, HOUR = 60 * MIN, DAY = 24 * HOUR, MONTH = 30 * DAY, YEAR = 365 * DAY;

/** Parse an API timestamp. A string with no timezone designator is treated as UTC, never as local time. */
export function parseUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  const d = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Full detail in the browser's timezone, e.g. "Tuesday, 3 November 2026 at 16:56:11 GMT+4". Used for hover. */
export const fmtAbsolute = (value: string | null | undefined) => {
  const d = parseUtc(value);
  return d ? d.toLocaleString(undefined, { dateStyle: "full", timeStyle: "long" }) : "—";
};

/** Compact absolute form for places that cannot host a tooltip, e.g. <option> labels. */
export const fmtDateTime = (value: string | null | undefined) => {
  const d = parseUtc(value);
  return d ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
};

/** Date only — for chart axes and tooltips. */
export const fmtDay = (value: string | null | undefined) => {
  const d = parseUtc(value);
  return d ? d.toLocaleDateString() : "—";
};

/**
 * "3 mins ago", "3 hours ago", "6 days ago", "6 months ago". Future times read "in 3 mins".
 * Anything a year or more away is shown as the date itself, since "14 months ago" helps nobody.
 */
export function fmtRelative(value: string | null | undefined): string {
  const d = parseUtc(value);
  if (!d) return "—";
  const ms = Date.now() - d.getTime();
  const abs = Math.abs(ms);
  if (abs >= YEAR) return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  if (abs < 45_000) return "just now";
  const [n, unit] = abs < HOUR ? [Math.round(abs / MIN), "min"]
    : abs < DAY ? [Math.round(abs / HOUR), "hour"]
    : abs < MONTH ? [Math.round(abs / DAY), "day"]
    : [Math.round(abs / MONTH), "month"];
  const label = `${n} ${unit}${n === 1 ? "" : "s"}`;
  return ms >= 0 ? `${label} ago` : `in ${label}`;
}

/** A duration in seconds as "1m 23s" / "45s" — used for GA4 average engagement time. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60), sec = total % 60;
  if (m < 60) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
