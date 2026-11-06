import { type ReactNode, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { ErrorBox, InfoHint, Loading } from "@/components/ui/misc";
import { fmtInt } from "@/lib/utils";

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
  if (isLoading) return <Loading label="Loading revenue model…" />;
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
        <CardTitle info={<><p>{r.formula} — this is a model, not a measurement.</p>{r.caveats.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-4">{r.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>}</>}>Revenue model</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <Tile label="Run rate" value={money(r.current_run_rate)} hint="Annualised from the latest 28 days of traffic and conversion." />
          <Tile label="Achievable" value={money(r.achievable)} hint="Plus the clicks you already have impressions for but do not win." />
          <Tile label="Upside" value={money(r.upside)} hint={`About ${fmtInt(r.upside_sessions_28d)} extra visits per 28 days.`} />
          <Tile label="Valuation" value={r.indicative_valuation ? `${r.currency} ${fmtInt(r.indicative_valuation.low)}–${fmtInt(r.indicative_valuation.high)}` : "—"} hint={r.indicative_valuation?.basis ?? "Shown once an average order value is set."} />
        </div>
        <form className="grid grid-cols-2 gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <div className="col-span-2 grid grid-cols-2 gap-3">
            <ModelField label="Currency"><Select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{["USD", "AED", "EUR", "GBP", "CNY", "SGD"].map((c) => <option key={c}>{c}</option>)}</Select></ModelField>
            <ModelField label="Order value / LTV" hint="What one customer is worth on average."><Input type="number" step="any" min={0} placeholder="0" value={form.average_order_value} onChange={(e) => setForm({ ...form, average_order_value: e.target.value })} /></ModelField>
          </div>
          <ModelField label="Conversion rate" hint="Used until GA4 provides a measured conversion rate."><Input type="number" step="0.001" min={0} max={1} value={form.assumed_conversion_rate} onChange={(e) => setForm({ ...form, assumed_conversion_rate: e.target.value })} /></ModelField>
          <ModelField label="Revenue multiple" hint="Low and high valuation multiples.">
            <div className="grid grid-cols-2 gap-2"><Input aria-label="Low revenue multiple" type="number" step="0.5" min={0} value={form.revenue_multiple_low} onChange={(e) => setForm({ ...form, revenue_multiple_low: e.target.value })} /><Input aria-label="High revenue multiple" type="number" step="0.5" min={0} value={form.revenue_multiple_high} onChange={(e) => setForm({ ...form, revenue_multiple_high: e.target.value })} /></div>
          </ModelField>
          <div className="col-span-2 flex justify-end">
            <Button type="submit" disabled={save.isPending}>Save model</Button>
          </div>
        </form>
        <ErrorBox error={save.error} />
      </CardContent>
    </Card>
  );
}

function ModelField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <div className="space-y-1"><div className="flex h-4 items-center gap-1.5"><Label>{label}</Label>{hint && <InfoHint label={`${label} explanation`} hover>{hint}</InfoHint>}</div>{children}</div>;
}

function Tile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs font-medium text-muted-foreground flex items-center gap-1">{label}<InfoHint>{hint}</InfoHint></div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
