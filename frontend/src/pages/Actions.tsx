import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Action, type Outcome } from "@/lib/api";
import { useEnqueue } from "@/hooks/useJobs";
import { useDomains, useProjectId } from "@/hooks/useProject";
import { EmptyState, ErrorBox, Loading, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge, Badge } from "@/components/ui/badge";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { delta, fmtInt, fmtNum, fmtPct } from "@/lib/utils";
import { TimeAgo } from "@/components/ui/time";
import { fmtDuration } from "@/lib/time";
import { Metric } from "@/components/ui/misc";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

const ACTION_COLUMNS: CsvColumn<Action>[] = [
  { key: "title", label: "Title", value: (r) => r.title }, { key: "description", label: "Description", value: (r) => r.description },
  { key: "status", label: "Status", value: (r) => r.status }, { key: "owner", label: "Owner", value: (r) => r.owner },
  { key: "urls", label: "Target URLs", value: (r) => r.target_urls.join("\n") }, { key: "keywords", label: "Target keywords", value: (r) => r.target_keywords.join("\n") },
  { key: "created", label: "Created", value: (r) => r.created_at }, { key: "started", label: "Started", value: (r) => r.started_at },
  { key: "completed", label: "Completed", value: (r) => r.completed_at },
];

/** The "Results" page (route /results). It is backed by the ActionRecord model and the /actions API — the
 *  component keeps its ActionsPage name for that reason, but everything the user sees reads "Results". */
export function ActionsPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const { data: actions, isLoading } = useQuery({ queryKey: ["actions", pid], queryFn: () => api.get<Action[]>(`/projects/${pid}/actions`) });
  const [form, setForm] = useState({ title: "", description: "", target_urls: "", target_keywords: "", owner: "" });
  const [filter, setFilter] = useState({ q: "", status: "" });
  const add = useMutation({ mutationFn: () => api.post<Action>(`/projects/${pid}/actions`, { title: form.title, description: form.description || null, owner: form.owner || null, target_urls: form.target_urls.split("\n").map((s) => s.trim()).filter(Boolean), target_keywords: form.target_keywords.split("\n").map((s) => s.trim()).filter(Boolean) }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["actions", pid] }); setForm({ title: "", description: "", target_urls: "", target_keywords: "", owner: "" }); } });
  const upd = useMutation({ mutationFn: ({ id, ...b }: Partial<Action> & { id: string }) => api.patch<Action>(`/projects/${pid}/actions/${id}`, b), onSuccess: () => qc.invalidateQueries({ queryKey: ["actions", pid] }) });
  const del = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/actions/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["actions", pid] }) });
  const rows = (actions ?? []).filter((row) => (!filter.q || `${row.title} ${row.description ?? ""} ${row.owner ?? ""} ${row.target_keywords.join(" ")}`.toLowerCase().includes(filter.q.toLowerCase())) && (!filter.status || row.status === filter.status));
  const paged = usePaged(rows, 10);
  if (isLoading) return <Loading />;
  return (
    <div>
      <PageHeader title="Results" info="Each tracked action compares the weeks before and after it against Search Console, analytics and AI mention data. Start tracking from any Growth Plan item." />
      <div className="mb-4 flex gap-2"><Select className="w-40" value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}><option value="">All statuses</option>{["planned", "in_progress", "done", "cancelled"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</Select><SearchBox className="w-[32rem]" placeholder="Filter actions…" value={filter.q} onSearch={(v) => setFilter({ ...filter, q: v })} /><div className="ml-auto"><CsvExportButton filename="actions.csv" rows={rows} columns={ACTION_COLUMNS} /></div></div>
      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-3">
          {!actions?.length ? <EmptyState title="No actions yet">Create actions from opportunities or add one manually.</EmptyState> : <>
            {paged.items.map((a) => <ActionCard key={a.id} a={a} pid={pid} onUpdate={(b) => upd.mutate({ id: a.id, ...b })} onDelete={() => del.mutate(a.id)} />)}
            <Pagination state={paged} label="actions" />
          </>}
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>New action</CardTitle></CardHeader><CardContent>
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
              <Field label="Title"><Input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
              <Field label="Description"><Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
              <Field label="Owner"><Input value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} /></Field>
              <Field label="Target URLs (one per line)" help="Used to measure outcomes in Search Console."><Textarea rows={2} value={form.target_urls} onChange={(e) => setForm({ ...form, target_urls: e.target.value })} /></Field>
              <Field label="Target keywords (one per line)"><Textarea rows={2} value={form.target_keywords} onChange={(e) => setForm({ ...form, target_keywords: e.target.value })} /></Field>
              <ErrorBox error={add.error} />
              <Button type="submit" disabled={add.isPending}>Create</Button>
            </form>
          </CardContent></Card>
          <AnalyticsImport pid={pid} />
        </div>
      </div>
    </div>
  );
}

function ActionCard({ a, pid, onUpdate, onDelete }: { a: Action; pid: string; onUpdate: (b: Partial<Action>) => void; onDelete: () => void }) {
  const qc = useQueryClient();
  const { data: outcomes } = useQuery({ queryKey: ["outcomes", a.id], queryFn: () => api.get<Outcome[]>(`/projects/${pid}/actions/${a.id}/outcomes`) });
  const measure = useMutation({ mutationFn: () => api.post<Outcome[]>(`/projects/${pid}/actions/${a.id}/measure`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["outcomes", a.id] }); qc.invalidateQueries({ queryKey: ["overview"] }); } });
  const latest = (outcomes ?? []).reduce<Record<string, Outcome>>((acc, o) => (acc[o.metric_key] ? acc : ((acc[o.metric_key] = o), acc)), {});
  return (
    <Card><CardContent className="pt-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0"><div className="font-medium flex items-center gap-2">{a.title}<StatusBadge status={a.status} />{a.plan_item_id && <Badge variant="muted">from the plan</Badge>}</div>{a.description && <p className="text-sm text-muted-foreground mt-1">{a.description}</p>}<div className="text-xs text-muted-foreground mt-1">{a.owner ? `owner ${a.owner} · ` : ""}created <TimeAgo value={a.created_at} />{a.started_at && <> · started <TimeAgo value={a.started_at} /></>}{a.completed_at && <> · completed <TimeAgo value={a.completed_at} /></>}</div>{(a.target_urls.length || a.target_keywords.length) ? <div className="text-xs text-muted-foreground mt-1">targets: {a.target_urls.join(", ")} {a.target_keywords.map((k) => `“${k}”`).join(", ")}</div> : null}</div>
        <div className="flex flex-col gap-1 shrink-0"><Select className="w-36" value={a.status} onChange={(e) => onUpdate({ status: e.target.value })}>{["planned", "in_progress", "done", "cancelled"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</Select><Button size="sm" variant="outline" onClick={() => measure.mutate()} disabled={measure.isPending}>Measure outcomes</Button><Button size="sm" variant="ghost" onClick={onDelete}>Delete</Button></div>
      </div>
      <ErrorBox error={measure.error} />
      {Object.keys(latest).length > 0 && (
        <Table><THead><TR><TH>Metric</TH><TH>Source</TH><TH>Baseline</TH><TH>Current</TH><TH>Change</TH><TH>Measured</TH></TR></THead>
          <TBody>{Object.values(latest).map((o) => { const lowerBetter = o.metric_key === "gsc_position"; const good = o.delta != null && (lowerBetter ? o.delta < 0 : o.delta > 0); return <TR key={o.id}><TD className="text-xs font-medium">{o.metric_key}</TD><TD className="text-xs"><Badge variant={o.measurement_type === "first_party" ? "success" : "muted"}>{o.measurement_type.replace("_", " ")}</Badge> <span className="text-muted-foreground">{o.source}</span></TD><TD className="tabular-nums text-xs">{fmtNum(o.baseline_value, 2)}<div className="text-muted-foreground">{o.baseline_period.start} → {o.baseline_period.end}</div></TD><TD className="tabular-nums text-xs">{fmtNum(o.current_value, 2)}<div className="text-muted-foreground">{o.comparison_period.start} → {o.comparison_period.end}</div></TD><TD className={`tabular-nums text-sm font-medium ${o.delta == null ? "" : good ? "text-emerald-600" : "text-red-600"}`}>{o.delta_pct != null ? `${o.delta_pct > 0 ? "+" : ""}${o.delta_pct.toFixed(1)}%` : o.delta != null ? fmtNum(o.delta, 2) : "n/a"}</TD><TD className="text-xs"><TimeAgo value={o.measured_at} /></TD></TR>; })}</TBody></Table>
      )}
      {measure.isSuccess && !measure.data.length && <p className="text-xs text-muted-foreground mt-2">No comparable data yet: outcomes need data from both before and after the action's start date.</p>}
    </CardContent></Card>
  );
}

interface Analytics { available: boolean; reason?: string; ga4_property: string | null; last_sync?: string; data_range?: { start: string; end: string }; providers?: string[]; totals?: Tot; previous?: Tot; landing_pages?: { landing_page: string; sessions: number; conversions: number; conversion_rate: number }[]; sources?: { source: string; medium: string; sessions: number; conversions: number }[] }
interface Tot { sessions: number; users: number; conversions: number; revenue: number; conversion_rate: number; engaged_sessions: number; avg_engagement_seconds: number; engagement_rate: number }
type LandingPage = NonNullable<Analytics["landing_pages"]>[number];
const LANDING_COLUMNS: CsvColumn<LandingPage>[] = [
  { key: "page", label: "Landing page", value: (r) => r.landing_page }, { key: "sessions", label: "Sessions", value: (r) => r.sessions },
  { key: "conversions", label: "Conversions", value: (r) => r.conversions }, { key: "rate", label: "Conversion rate", value: (r) => r.conversion_rate },
];

function AnalyticsImport({ pid }: { pid: string }) {
  const qc = useQueryClient();
  const { data: domains } = useDomains();
  const primary = (domains ?? []).filter((d) => d.role === "primary");
  const [domainId, setDomainId] = useState("");
  const domain = primary.find((d) => d.id === domainId) ?? primary[0];
  const [file, setFile] = useState<File | null>(null);
  const [prop, setProp] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const enqueue = useEnqueue();
  const { data } = useQuery({ queryKey: ["analytics", domain?.id], queryFn: () => api.get<Analytics>(`/projects/${pid}/domains/${domain!.id}/analytics`), enabled: !!domain, refetchInterval: 20000 });
  const landingPages = (data?.landing_pages ?? []).filter((row) => !filter || row.landing_page.toLowerCase().includes(filter.toLowerCase()));
  const pagedPages = usePaged(landingPages, 10);
  const saveProp = useMutation({ mutationFn: () => api.patch(`/projects/${pid}/domains/${domain!.id}`, { ga4_property: prop }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["domains", pid] }); qc.invalidateQueries({ queryKey: ["analytics"] }); } });
  const imp = useMutation({ mutationFn: async () => { const fd = new FormData(); fd.append("file", file!); return api.post<{ imported: number }>(`/projects/${pid}/domains/${domain!.id}/analytics/import`, fd); }, onSuccess: () => qc.invalidateQueries({ queryKey: ["analytics"] }) });
  if (!domain) return null;
  const propValue = prop ?? domain.ga4_property ?? "";
  return (
    <Card><CardHeader><CardTitle info="Google Analytics 4 sessions, key events (conversions) and revenue per landing page. Feeds the low-conversion landing page rule.">Website analytics</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {primary.length > 1 && <Select value={domain.id} onChange={(e) => { setDomainId(e.target.value); setProp(null); }}>{primary.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}</Select>}
        <div className="flex gap-2 items-end">
          <Field label="GA4 property ID"><Input className="w-44" placeholder="123456789" value={propValue} onChange={(e) => setProp(e.target.value)} /></Field>
          <Button size="sm" variant="outline" onClick={() => saveProp.mutate()} disabled={saveProp.isPending || prop === null}>Save</Button>
          <Button size="sm" onClick={() => enqueue.mutate({ task_type: "sync_analytics", params: { domain_id: domain.id, days: 90 } })} disabled={enqueue.isPending || !domain.ga4_property}>Re-run</Button>
        </div>
        <ErrorBox error={saveProp.error || enqueue.error} />
        {enqueue.isSuccess && <p className="text-xs text-muted-foreground">Sync job queued…</p>}
        {data?.available ? (
          <>
            <div className="text-xs text-muted-foreground">Sources: {data.providers?.join(", ")} · data {data.data_range?.start} → {data.data_range?.end} · last sync <TimeAgo value={data.last_sync} /></div>
            <div className="grid grid-cols-2 gap-2">
              <Metric label="Sessions (28d)" value={fmtInt(data.totals?.sessions)} change={delta(data.totals?.sessions, data.previous?.sessions)} source="vs previous 28d" />
              <Metric label="Conversions (28d)" value={fmtInt(data.totals?.conversions)} change={delta(data.totals?.conversions, data.previous?.conversions)} source={`rate ${fmtPct(data.totals?.conversion_rate)}`} />
              <Metric label="Avg. engagement" value={fmtDuration(data.totals?.avg_engagement_seconds)} change={delta(data.totals?.avg_engagement_seconds, data.previous?.avg_engagement_seconds)} source={`${fmtInt(data.totals?.engaged_sessions)} engaged sessions`} hint="GA4 average engagement time per session: total engagement time ÷ sessions." />
              <Metric label="Engagement rate" value={fmtPct(data.totals?.engagement_rate, 0)} change={delta(data.totals?.engagement_rate, data.previous?.engagement_rate)} source="engaged / all sessions" />
            </div>
            <div className="flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter landing pages…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="analytics-landing-pages.csv" rows={landingPages} columns={LANDING_COLUMNS} /></div></div>
            <Table><THead><TR><TH>Landing page</TH><TH className="text-right">Sessions</TH><TH className="text-right">Conv.</TH><TH className="text-right">Rate</TH></TR></THead>
              <TBody>{pagedPages.items.map((r) => <TR key={r.landing_page}><TD className="text-xs max-w-xs truncate">{r.landing_page}</TD><TD className="text-right tabular-nums">{fmtInt(r.sessions)}</TD><TD className="text-right tabular-nums">{fmtInt(r.conversions)}</TD><TD className="text-right tabular-nums">{fmtPct(r.conversion_rate)}</TD></TR>)}</TBody></Table>
            <Pagination state={pagedPages} label="landing pages" />
          </>
        ) : data ? <p className="text-xs text-muted-foreground">{data.reason}</p> : null}
        <details><summary className="text-xs text-muted-foreground cursor-pointer">Or import a CSV (date, landing_page, sessions, conversions[, users, revenue, source, medium])</summary>
          <div className="mt-2 space-y-2"><Input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /><Button size="sm" variant="outline" onClick={() => imp.mutate()} disabled={!file || imp.isPending}>Import</Button>{imp.data && <p className="text-xs text-emerald-700 dark:text-emerald-300">Imported {imp.data.imported} rows.</p>}<ErrorBox error={imp.error} /></div>
        </details>
      </CardContent></Card>
  );
}
