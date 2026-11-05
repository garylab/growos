import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { ErrorBox, InfoHint, Loading } from "@/components/ui/misc";
import { fmtInt, fmtPct } from "@/lib/utils";

export interface Revenue {
  currency: string; inputs: Record<string, any>; formula: string;
  current_run_rate: number | null; achievable: number | null; upside: number | null;
  upside_sessions_28d: number; upside_sources: string[];
  indicative_valuation: { low: number; high: number; basis: string } | null; caveats: string[];
}

/** The revenue model and its inputs. Lives in Settings because it is configuration, not a measurement. */
export function RevenueModelCard({ pid }: { pid: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["scorecard", pid],
    queryFn: () => api.get<{ revenue: Revenue; economics: Record<string, any> }>(`/projects/${pid}/scorecard`),
    enabled: !!pid,
  });
  if (isLoading) return <Card><CardContent className="pt-5"><Loading label="Loading revenue model…" /></CardContent></Card>;
  if (!data) return null;
  return <RevenueForm pid={pid} revenue={data.revenue} economics={data.economics} />;
}

/** The headline numbers only — shown next to Monetization Readiness on the Overview. */
export function RevenueSummary({ revenue: r }: { revenue: Revenue }) {
  const money = (v: number | null | undefined) => (v == null ? "—" : `${r.currency} ${fmtInt(v)}`);
  if (!r.inputs.average_order_value) {
    return <p className="text-xs text-muted-foreground">Set an average order value under Settings to project revenue.</p>;
  }
  return (
    <div className="grid grid-cols-3 gap-2">
      {[["Run rate", money(r.current_run_rate)], ["Achievable", money(r.achievable)],
        ["Valuation", r.indicative_valuation ? `${r.currency} ${fmtInt(r.indicative_valuation.low)}–${fmtInt(r.indicative_valuation.high)}` : "—"]].map(([k, v]) => (
        <div key={k}><div className="text-[11px] text-muted-foreground">{k}</div><div className="text-sm font-semibold tabular-nums">{v}</div></div>
      ))}
    </div>
  );
}

function RevenueForm({ pid, revenue: r, economics }: { pid: string; revenue: Revenue; economics: Record<string, any> }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    currency: economics.currency ?? "USD",
    average_order_value: economics.average_order_value ?? "",
    assumed_conversion_rate: economics.assumed_conversion_rate ?? 0.02,
    revenue_multiple_low: economics.revenue_multiple_low ?? 3,
    revenue_multiple_high: economics.revenue_multiple_high ?? 6,
  });
  const save = useMutation({
    mutationFn: () => api.put(`/projects/${pid}/scorecard/economics`, {
      currency: form.currency,
      average_order_value: form.average_order_value === "" ? null : Number(form.average_order_value),
      assumed_conversion_rate: Number(form.assumed_conversion_rate),
      revenue_multiple_low: Number(form.revenue_multiple_low),
      revenue_multiple_high: Number(form.revenue_multiple_high),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scorecard", pid] }),
  });
  const money = (v: number | null | undefined) => (v == null ? "—" : `${r.currency} ${fmtInt(v)}`);
  return (
    <Card>
      <CardHeader>
        <CardTitle info={`${r.formula} — a model, not a measurement. Change any input and the result changes.`}>Revenue model</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="Annual run rate" value={money(r.current_run_rate)} hint="The last 28 days of traffic and conversion, annualised." />
          <Tile label="Achievable" value={money(r.achievable)} hint="Plus the clicks you already have impressions for but do not win." />
          <Tile label="Upside" value={money(r.upside)} hint={`About ${fmtInt(r.upside_sessions_28d)} extra visits per 28 days.`} />
          <Tile label="Indicative valuation" value={r.indicative_valuation ? `${r.currency} ${fmtInt(r.indicative_valuation.low)} – ${fmtInt(r.indicative_valuation.high)}` : "—"} hint={r.indicative_valuation?.basis ?? "Shown once an average order value is set."} />
        </div>
        {!r.inputs.average_order_value && (
          <div className="rounded-md border border-amber-200 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/30 px-3 py-2 text-sm">
            Set an average order value below to produce monetary figures.
          </div>
        )}
        <div className="text-xs text-muted-foreground flex items-center gap-1">
          Conversion rate {fmtPct(r.inputs.conversion_rate)} · base {fmtInt(r.inputs.sessions_28d)} {r.inputs.basis ?? "no data"} per 28 days
          {(r.upside_sources.length > 0 || r.inputs.conversion_rate_source) && (
            <InfoHint width="w-80">
              {r.inputs.conversion_rate_source && <p>Conversion rate: {r.inputs.conversion_rate_source}.</p>}
              {r.upside_sources.length > 0 && <p className="mt-1">Upside comes from: {r.upside_sources.join("; ")}</p>}
            </InfoHint>
          )}
        </div>
        <form className="grid md:grid-cols-5 gap-3 items-end" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Currency"><Select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{["USD", "AED", "EUR", "GBP", "CNY", "SGD"].map((c) => <option key={c}>{c}</option>)}</Select></Field>
          <Field label="Average order value / LTV" help="What one customer is worth on average."><Input type="number" step="any" min={0} value={form.average_order_value} onChange={(e) => setForm({ ...form, average_order_value: e.target.value })} /></Field>
          <Field label="Assumed conversion rate" help="Replaced by the measured rate once GA4 has a key event."><Input type="number" step="0.001" min={0} max={1} value={form.assumed_conversion_rate} onChange={(e) => setForm({ ...form, assumed_conversion_rate: e.target.value })} /></Field>
          <Field label="Revenue multiple, low"><Input type="number" step="0.5" min={0} value={form.revenue_multiple_low} onChange={(e) => setForm({ ...form, revenue_multiple_low: e.target.value })} /></Field>
          <div className="flex gap-2 items-end">
            <Field label="high"><Input type="number" step="0.5" min={0} value={form.revenue_multiple_high} onChange={(e) => setForm({ ...form, revenue_multiple_high: e.target.value })} /></Field>
            <Button type="submit" disabled={save.isPending}>Save</Button>
          </div>
        </form>
        <ErrorBox error={save.error} />
        {r.caveats.length > 0 && (
          <div className="text-xs text-muted-foreground flex items-center gap-1">
            Caveats
            <InfoHint width="w-80"><ul className="list-disc pl-4 space-y-0.5">{r.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul></InfoHint>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs font-medium text-muted-foreground flex items-center gap-1">{label}<InfoHint>{hint}</InfoHint></div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
