import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cn } from "@/lib/utils";

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
  /** Which y-axis this series is measured against. Defaults to the left axis. */
  axis?: "left" | "right";
  /** Draw as a filled area instead of a plain line. */
  area?: boolean;
  fill?: string;
  width?: number;
}

interface Props {
  data: Record<string, any>[];
  xKey: string;
  series: ChartSeries[];
  height?: number;
  xTickFormatter?: (value: any) => string;
  leftTickFormatter?: (value: any) => string;
  rightTickFormatter?: (value: any) => string;
  tooltipLabelFormatter?: (value: any) => string;
  tooltipFormatter?: (value: any, name: any) => any;
  /** Clamp the computed left-axis maximum, e.g. a percentage that should never exceed 100. */
  leftMaxCap?: number;
}

/** Round a value up to a tidy axis maximum (1/2/5 × 10ⁿ) with ~10% headroom, optionally capped. */
function niceMax(max: number, cap?: number): number {
  if (max <= 0) return cap ?? 1;
  let target = max * 1.1;
  if (cap != null) target = Math.min(target, cap);
  const mag = Math.pow(10, Math.floor(Math.log10(target)));
  const n = target / mag;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  const result = step * mag;
  return cap != null ? Math.min(result, cap) : result;
}

/** A time-series line/area chart whose y-axes rescale to the lines that are currently shown. Each series has
 *  a toggle button beneath the chart (shown only when there is more than one), so a dominant line can be
 *  hidden to read the rest. Supports a second, right-hand axis for series on a different scale. */
export function TimeSeriesChart({
  data, xKey, series, height = 200,
  xTickFormatter, leftTickFormatter, rightTickFormatter, tooltipLabelFormatter, tooltipFormatter, leftMaxCap,
}: Props) {
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) => setHidden((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const visible = series.filter((s) => !hidden.has(s.key));
  const hasRight = series.some((s) => s.axis === "right");
  const maxFor = (axis: "left" | "right") => Math.max(0, ...data.flatMap((point) =>
    visible.filter((s) => (s.axis ?? "left") === axis)
      .map((s) => point[s.key]).filter((v): v is number => typeof v === "number")));
  const leftDomain: [number, number] = [0, niceMax(maxFor("left"), leftMaxCap)];
  const rightDomain: [number, number] = [0, niceMax(maxFor("right"))];
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickFormatter={xTickFormatter} />
          <YAxis yAxisId="left" domain={leftDomain} allowDataOverflow tick={{ fontSize: 11 }} allowDecimals={false} tickFormatter={leftTickFormatter} />
          {hasRight && <YAxis yAxisId="right" orientation="right" domain={rightDomain} allowDataOverflow tick={{ fontSize: 11 }} allowDecimals={false} tickFormatter={rightTickFormatter} />}
          <Tooltip labelFormatter={tooltipLabelFormatter} formatter={tooltipFormatter} />
          {series.map((s) => s.area
            ? <Area key={s.key} yAxisId={s.axis ?? "left"} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} fill={s.fill ?? s.color} dot={false} connectNulls hide={hidden.has(s.key)} />
            : <Line key={s.key} yAxisId={s.axis ?? "left"} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={s.width ?? 2} dot={false} connectNulls hide={hidden.has(s.key)} />)}
        </ComposedChart>
      </ResponsiveContainer>
      {series.length > 1 && (
        <div role="group" aria-label="Chart series" className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
          {series.map((s) => (
            <button key={s.key} type="button" aria-pressed={!hidden.has(s.key)} onClick={() => toggle(s.key)}
              className={cn("inline-flex items-center gap-1.5 rounded px-2 py-1 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary", hidden.has(s.key) && "opacity-50 line-through")}>
              <span aria-hidden="true" className="inline-block w-3 border-t-2" style={{ borderColor: s.color }} />
              {s.label}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
