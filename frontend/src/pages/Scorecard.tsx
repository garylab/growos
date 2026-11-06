import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorBox, InfoHint, Loading } from "@/components/ui/misc";
import { RevenueSummary, type Revenue } from "@/components/RevenueModel";
import { cn, fmtPct } from "@/lib/utils";
import { fmtDay } from "@/lib/time";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface Component { key: string; label: string; weight: number; weight_used: number; score: number | null; raw: any; unit: string; source: string; formula: string; note: string; available: boolean }
interface Lever { id: string; title: string; priority: number; category: string }
interface Index { key: string; label: string; question: string; score: number | null; grade: string; coverage: number; confidence: string; insufficient_data: boolean; provisional_score: number | null; insufficient_reason: string | null; formula: string; components: Component[]; missing: string[]; delta: number | null; previous_score: number | null; levers: Lever[] }
interface Scorecard { project: { name: string; brand: string }; generated_at: string; overall: { score: number | null; grade: string; label: string; formula: string; coverage: number; indices_counted: number; indices_total: number; delta: number | null; previous_score: number | null; weakest_link: { key: string; label: string; score: number } | null }; indices: Index[]; history: { date: string; overall: number | null; brand_influence?: number | null; brand_competitiveness?: number | null; monetization?: number | null }[]; revenue: Revenue; economics: Record<string, any>; data_sources: Record<string, any>; how_to_read: Record<string, string> }

const GRADE_COLOR: Record<string, string> = {
  A: "text-emerald-600 dark:text-emerald-400", B: "text-sky-600 dark:text-sky-400", C: "text-amber-600 dark:text-amber-400",
  D: "text-orange-600 dark:text-orange-400", E: "text-red-600 dark:text-red-400", "n/a": "text-muted-foreground",
};

const HISTORY_SERIES = [
  { key: "overall", label: "Growth Score", color: "#9333ea", width: 3 },
  { key: "brand_influence", label: "Brand Influence", color: "#2563eb", width: 1 },
  { key: "brand_competitiveness", label: "Competitiveness", color: "#d97706", width: 1 },
  { key: "monetization", label: "Monetization", color: "#059669", width: 1 },
] as const;

/** The scorecard query, shared so a host page can start it on mount rather than after its own data arrives.
 *
 *  Overview used to mount `ScorecardSection` only after its own query resolved, which serialised two requests
 *  that have no dependency on each other — on a large project that is ~1.4s + ~1.4s instead of ~1.4s total.
 *  Calling this hook alongside the host's own query makes them run together; react-query dedupes on the key, so
 *  `ScorecardSection` then reads the same in-flight request rather than issuing a second one. */
export function useScorecard(pid: string) {
  return useQuery({ queryKey: ["scorecard", pid], queryFn: () => api.get<Scorecard>(`/projects/${pid}/scorecard`), enabled: !!pid });
}

/** The full Brand Scorecard, embeddable as a section (used inside Overview). Fetches its own data. */
export function ScorecardSection({ pid }: { pid: string }) {
  const { data, isLoading, error } = useScorecard(pid);
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(() => new Set());
  const toggleSeries = (key: string) => setHiddenSeries((previous) => {
    const next = new Set(previous);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  if (isLoading) return <Loading label="Loading scorecard…" />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const ov = data.overall;
  const hasHistory = (data.history?.filter((h) => h.overall != null).length ?? 0) >= 2;
  const visibleHistorySeries = HISTORY_SERIES.filter((series) => !hiddenSeries.has(series.key));
  const visibleHistoryMax = Math.max(0, ...data.history.flatMap((point) =>
    visibleHistorySeries.map((series) => point[series.key]).filter((value): value is number => value != null),
  ));
  const historyYAxisMax = visibleHistorySeries.length
    ? Math.min(100, Math.max(10, Math.ceil((visibleHistoryMax + 5) / 10) * 10))
    : 100;
  return (
    <div>
      {/* Hero: the one number, with its trend. Below it, the three indices that explain it. */}
      <Card className="mb-4">
        <CardContent className="pt-6">
          <div className="text-xs font-medium text-muted-foreground flex items-center gap-1">
            {ov.label}
            <InfoHint width="w-80">
              <p>{ov.formula}</p>
              <p className="mt-1">{ov.indices_counted}/{ov.indices_total} indices scored{ov.previous_score != null ? `; previously ${ov.previous_score}` : ""}.</p>
              {Object.entries(data.how_to_read).map(([k, v]) => <p key={k} className="mt-1">{v}</p>)}
              <p className="mt-1">Sources: {Object.entries(data.data_sources).map(([k, v]) => `${k}: ${v === true ? "yes" : v === false ? "no" : v}`).join(" · ")}</p>
            </InfoHint>
          </div>
          <div className={cn("mt-1 text-6xl font-semibold tabular-nums leading-none", GRADE_COLOR[ov.grade])}>{ov.score ?? "—"}</div>
          {/* Reads the same way as the three index cards below: the change, then how much of the model had data.
              The previous score is not repeated here — the delta already is the difference from it. */}
          <div className="mt-2 flex items-center gap-2 text-sm">
            <Delta delta={ov.delta} />
            <span className="text-muted-foreground">data {fmtPct(ov.coverage, 0)}</span>
          </div>
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-3 gap-4 mb-4">
        {data.indices.map((i) => <IndexHeadline key={i.key} index={i} history={data.history} revenue={i.key === "monetization" ? data.revenue : undefined} />)}
      </div>

      {hasHistory && (
        <Card className="mb-6">
          <CardHeader><CardTitle info="Snapshots taken as data is collected. Compare against your own past, not other companies. The scale starts at zero and adjusts to the selected lines.">Score history</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={data.history}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => String(d).slice(5)} />
                <YAxis domain={[0, historyYAxisMax]} tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip labelFormatter={(d) => fmtDay(String(d))} />
                {HISTORY_SERIES.map((series) => (
                  <Line key={series.key} type="monotone" dataKey={series.key} name={series.label} stroke={series.color} strokeWidth={series.width} dot={false} connectNulls hide={hiddenSeries.has(series.key)} />
                ))}
              </LineChart>
            </ResponsiveContainer>
            <div role="group" aria-label="Score history lines" className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
              {HISTORY_SERIES.map((series) => (
                <button
                  key={series.key}
                  type="button"
                  aria-pressed={!hiddenSeries.has(series.key)}
                  onClick={() => toggleSeries(series.key)}
                  className={cn("inline-flex items-center gap-1.5 rounded px-2 py-1 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary", hiddenSeries.has(series.key) && "opacity-50 line-through")}
                >
                  <span aria-hidden="true" className="inline-block w-3 border-t-2" style={{ borderColor: series.color }} />
                  {series.label}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {ov.score === null && (
        <div className="mb-6"><EmptyState title="Not enough data to score yet">
          Start on the <Link className="text-primary underline" to="/plan">Growth Plan</Link>.
        </EmptyState></div>
      )}
    </div>
  );
}

function Delta({ delta, className }: { delta: number | null; className?: string }) {
  if (delta == null) return null;
  const up = delta > 0, flat = delta === 0;
  return <span className={cn("inline-flex items-center gap-0.5 text-sm font-medium", up ? "text-emerald-600 dark:text-emerald-400" : flat ? "text-muted-foreground" : "text-red-600 dark:text-red-400", className)}>{up ? <TrendingUp className="h-3.5 w-3.5" /> : flat ? <Minus className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />} {Math.abs(delta)}</span>;
}

function Spark({ series, keyName, color }: { series: any[]; keyName: string; color: string }) {
  const pts = series.map((h) => h[keyName]).filter((v) => v != null) as number[];
  if (pts.length < 2) return null;
  const w = 120, h = 28, min = Math.min(...pts), max = Math.max(...pts), span = max - min || 1;
  const d = pts.map((v, n) => `${(n / (pts.length - 1)) * w},${h - ((v - min) / span) * (h - 4) - 2}`).join(" ");
  return <svg width={w} height={h} className="overflow-visible"><polyline points={d} fill="none" stroke={color} strokeWidth={1.5} /></svg>;
}

const LEVER_COLOR: Record<string, string> = { brand_influence: "#2563eb", brand_competitiveness: "#d97706", monetization: "#059669" };

function IndexHeadline({ index: i, history, revenue }: { index: Index; history: any[]; revenue?: Revenue }) {
  return (
    <Card>
      <CardContent className="pt-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xs font-medium text-muted-foreground flex items-center gap-1">
              {i.label}
              <InfoHint width="w-[34rem]">
                <IndexBreakdown index={i} />
                {revenue && <RevenueBlock revenue={revenue} />}
              </InfoHint>
            </div>
            <div className={cn("mt-1 text-4xl font-semibold tabular-nums leading-none", GRADE_COLOR[i.grade])}>{i.score ?? <span className="text-xl text-muted-foreground">Not scored</span>}</div>
            <div className="mt-1.5 flex items-center gap-2 text-xs">
              <Delta delta={i.delta} className="text-xs" />
              <span className="text-muted-foreground">{i.score !== null ? <>data {fmtPct(i.coverage, 0)}</> : <>data {fmtPct(i.coverage, 0)}{i.provisional_score !== null && <> · provisional {i.provisional_score}</>}</>}</span>
            </div>
          </div>
          <Spark series={history} keyName={i.key} color={LEVER_COLOR[i.key] ?? "#64748b"} />
        </div>
      </CardContent>
    </Card>
  );
}

/** The component table, laid out as a list so it fits inside the ⓘ popover without sideways scrolling. */
/** Revenue projection for the Monetization index.
 *
 *  Lives in that card's hint rather than on the card. On its face it is the headline run-rate/achievable/
 *  valuation row, but with no average order value set it is just a prompt to go and configure one — and a
 *  permanent instruction occupying a third of the scorecard grid is worse than one click away. Moving it also
 *  stops the Monetization card stretching the whole three-card row taller than its siblings. */
function RevenueBlock({ revenue }: { revenue: Revenue }) {
  return (
    <div className="mt-3 border-t pt-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">Revenue model (annualised)</div>
      <RevenueSummary revenue={revenue} />
    </div>
  );
}

function IndexBreakdown({ index: i }: { index: Index }) {
  return (
    <div className="space-y-2">
      <p className="font-medium text-foreground">{i.label} {i.score !== null ? `${i.score}/100` : "not scored"}</p>
      <p>{i.formula}</p>
      {i.insufficient_reason && <p className="text-amber-700 dark:text-amber-300">{i.insufficient_reason}</p>}
      <ul className="space-y-1.5 border-t pt-2">
        {i.components.map((c) => (
          <li key={c.key} className={cn(!c.available && "opacity-60")}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium text-foreground">{c.label}</span>
              <span className="tabular-nums whitespace-nowrap">
                {c.available ? c.score : "no data"} · {fmtPct(c.weight, 0)}
                {c.available && c.weight_used !== c.weight && ` (used ${fmtPct(c.weight_used, 0)})`}
              </span>
            </div>
            <div>{c.formula}</div>
            {c.note && <div className="opacity-80">{c.note}</div>}
            <div className="opacity-80">
              {c.source}
              {c.available && c.raw != null && <> · raw {typeof c.raw === "object" ? JSON.stringify(c.raw) : String(c.raw)}{c.unit ? ` ${c.unit}` : ""}</>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
