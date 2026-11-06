import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Domain, type Project } from "@/lib/api";
import { useDomains, useProject, useProjectId } from "@/hooks/useProject";
import { ErrorBox, Loading, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { TimeAgo } from "@/components/ui/time";
import { RevenueModelCard } from "@/components/RevenueModel";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

interface Schedule { id: string; task_type: string; params: Record<string, unknown>; interval_minutes: number; is_enabled: boolean; next_run_at: string; last_enqueued_at: string | null; label: string | null }
const DOMAIN_COLUMNS: CsvColumn<Domain>[] = [
  { key: "host", label: "Host", value: (r) => r.hostname }, { key: "url", label: "Base URL", value: (r) => r.base_url },
  { key: "gsc", label: "Search Console property", value: (r) => r.gsc_property }, { key: "ga4", label: "GA4 property", value: (r) => r.ga4_property },
];
const SCHEDULE_COLUMNS: CsvColumn<Schedule>[] = [
  { key: "task", label: "Task", value: (r) => r.task_type }, { key: "params", label: "Parameters", value: (r) => JSON.stringify(r.params) },
  { key: "interval", label: "Interval minutes", value: (r) => r.interval_minutes }, { key: "enabled", label: "Enabled", value: (r) => r.is_enabled },
  { key: "next", label: "Next run", value: (r) => r.next_run_at }, { key: "last", label: "Last run", value: (r) => r.last_enqueued_at },
];

export function SettingsPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const { data: project, isLoading } = useProject();
  const { data: domains } = useDomains();
  const { data: schedules } = useQuery({ queryKey: ["schedules", pid], queryFn: () => api.get<Schedule[]>(`/projects/${pid}/schedules`) });
  const { data: tasks } = useQuery({ queryKey: ["tasks"], queryFn: () => api.get<Record<string, string>>("/tasks") });
  const [form, setForm] = useState<Partial<Project> & { aliases?: string } | null>(null);
  const [domainFilter, setDomainFilter] = useState("");
  const [scheduleFilter, setScheduleFilter] = useState("");
  const f = form ?? { ...project, aliases: project?.brand_aliases.join(", ") };
  const save = useMutation({ mutationFn: () => api.patch<Project>(`/projects/${pid}`, { name: f.name, brand_name: f.brand_name, description: f.description, default_country: f.default_country, default_language: f.default_language, brand_aliases: (f.aliases ?? "").split(",").map((s) => s.trim()).filter(Boolean) }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["project", pid] }); qc.invalidateQueries({ queryKey: ["projects"] }); } });
  const [url, setUrl] = useState("");
  const addDomain = useMutation({ mutationFn: () => api.post<Domain>(`/projects/${pid}/domains`, { url, role: "primary" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["domains", pid] }); setUrl(""); } });
  const delDomain = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/domains/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["domains", pid] }) });
  const [sched, setSched] = useState({ task_type: "sync_search_console", interval_minutes: 1440, domain_id: "" });
  const addSched = useMutation({ mutationFn: () => api.post(`/projects/${pid}/schedules`, { task_type: sched.task_type, interval_minutes: sched.interval_minutes, params: sched.domain_id ? { domain_id: sched.domain_id } : {}, label: `${sched.task_type} every ${sched.interval_minutes} min` }), onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules", pid] }) });
  const delSched = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/schedules/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules", pid] }) });
  const delProject = useMutation({ mutationFn: () => api.delete(`/projects/${pid}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); window.location.href = "/"; } });
  const primaryDomains = (domains ?? []).filter((d) => d.role === "primary" && (!domainFilter || `${d.hostname} ${d.gsc_property ?? ""} ${d.ga4_property ?? ""}`.toLowerCase().includes(domainFilter.toLowerCase())));
  const filteredSchedules = (schedules ?? []).filter((row) => !scheduleFilter || `${row.task_type} ${row.label ?? ""} ${JSON.stringify(row.params)}`.toLowerCase().includes(scheduleFilter.toLowerCase()));
  const pagedSchedules = usePaged(filteredSchedules, 10);
  if (isLoading || !project) return <Loading />;
  const needsDomain = ["crawl_domain", "measure_performance", "sync_search_console", "sync_analytics"].includes(sched.task_type);
  return (
    <div>
      <PageHeader title="Settings" />
      <div className="grid lg:grid-cols-2 gap-4">
        <Card><CardHeader><CardTitle>Project & brand</CardTitle></CardHeader><CardContent>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <Field label="Project name"><Input value={f.name ?? ""} onChange={(e) => setForm({ ...f, name: e.target.value })} /></Field>
            <Field label="Brand name"><Input value={f.brand_name ?? ""} onChange={(e) => setForm({ ...f, brand_name: e.target.value })} /></Field>
            <Field label="Brand aliases (comma separated)"><Input value={f.aliases ?? ""} onChange={(e) => setForm({ ...f, aliases: e.target.value })} /></Field>
            <Field label="Description (used by the AI analyst)"><Textarea rows={3} value={f.description ?? ""} onChange={(e) => setForm({ ...f, description: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3"><Field label="Default country"><Input value={f.default_country ?? ""} onChange={(e) => setForm({ ...f, default_country: e.target.value })} /></Field><Field label="Default language"><Input value={f.default_language ?? ""} onChange={(e) => setForm({ ...f, default_language: e.target.value })} /></Field></div>
            <ErrorBox error={save.error} /><Button type="submit" disabled={save.isPending}>Save</Button>
          </form>
        </CardContent></Card>
        <Card><CardHeader><CardTitle info="The sites you own — crawled, measured and tracked in search. Competitors live on the Competitors page.">Your websites</CardTitle></CardHeader><CardContent className="space-y-3">
          <div className="flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter websites…" value={domainFilter} onSearch={setDomainFilter} /><CsvExportButton filename="websites.csv" rows={primaryDomains} columns={DOMAIN_COLUMNS} /></div>
          <Table><THead><TR><TH>Host</TH><TH>Search Console property</TH><TH /></TR></THead><TBody>{primaryDomains.map((d) => <TR key={d.id}><TD>{d.hostname}</TD><TD className="text-xs">{d.gsc_property ?? <span className="text-muted-foreground">set under SEO → Search performance</span>}</TD><TD className="text-right"><Button size="sm" variant="ghost" onClick={() => delDomain.mutate(d.id)}>Remove</Button></TD></TR>)}</TBody></Table>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); addDomain.mutate(); }}><Input placeholder="https://www.example.com" value={url} onChange={(e) => setUrl(e.target.value)} /><Button type="submit" disabled={addDomain.isPending}>Add website</Button></form>
          <ErrorBox error={addDomain.error} />
        </CardContent></Card>
        <Card><CardHeader><CardTitle info="The worker enqueues these jobs automatically. Recommended: Search Console daily, crawl weekly, AI visibility weekly, mentions daily.">Recurring schedules</CardTitle></CardHeader><CardContent className="space-y-3">
          <div className="flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter schedules…" value={scheduleFilter} onSearch={setScheduleFilter} /><CsvExportButton filename="recurring-schedules.csv" rows={filteredSchedules} columns={SCHEDULE_COLUMNS} /></div>
          <Table><THead><TR><TH>Task</TH><TH>Every</TH><TH>Next run</TH><TH>Last</TH><TH /></TR></THead><TBody>{pagedSchedules.items.map((s) => <TR key={s.id}><TD className="text-xs">{s.task_type}{s.params.domain_id ? ` (${(domains ?? []).find((d) => d.id === s.params.domain_id)?.hostname ?? "domain"})` : ""}</TD><TD>{s.interval_minutes >= 1440 ? `${s.interval_minutes / 1440} d` : `${s.interval_minutes} min`}</TD><TD className="text-xs"><TimeAgo value={s.next_run_at} fallback="not scheduled" /></TD><TD className="text-xs"><TimeAgo value={s.last_enqueued_at} fallback="never" /></TD><TD className="text-right"><Button size="sm" variant="ghost" onClick={() => delSched.mutate(s.id)}>Remove</Button></TD></TR>)}</TBody></Table>
          <Pagination state={pagedSchedules} label="schedules" />
          <form className="grid grid-cols-3 gap-2 items-end" onSubmit={(e) => { e.preventDefault(); addSched.mutate(); }}>
            <Field label="Task"><Select value={sched.task_type} onChange={(e) => setSched({ ...sched, task_type: e.target.value })}>{Object.entries(tasks ?? {}).filter(([k]) => k !== "ai_analysis").map(([k, v]) => <option key={k} value={k} title={v}>{k}</option>)}</Select></Field>
            <Field label="Interval"><Select value={sched.interval_minutes} onChange={(e) => setSched({ ...sched, interval_minutes: Number(e.target.value) })}><option value={360}>6 hours</option><option value={1440}>daily</option><option value={10080}>weekly</option><option value={43200}>monthly</option></Select></Field>
            {needsDomain ? <Field label="Website"><Select value={sched.domain_id} onChange={(e) => setSched({ ...sched, domain_id: e.target.value })}><option value="">choose…</option>{(domains ?? []).filter((d) => d.role === "primary").map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}</Select></Field> : <div />}
            <Button type="submit" className="col-span-3" disabled={addSched.isPending || (needsDomain && !sched.domain_id)}>Add schedule</Button>
          </form>
          <ErrorBox error={addSched.error} />
        </CardContent></Card>
        <div className="lg:col-span-2"><RevenueModelCard pid={pid} /></div>
        <UsageBudgetCard pid={pid} settings={project.settings as Record<string, any>} />
        <Card className="border-red-200 dark:border-red-900"><CardHeader><CardTitle>Danger zone</CardTitle></CardHeader><CardContent><Button variant="destructive" onClick={() => { if (confirm("Delete this project and all its data?")) delProject.mutate(); }}>Delete project</Button></CardContent></Card>
      </div>
    </div>
  );
}

interface Usage { tokens_this_month: number; budget: number; budget_used_pct: number | null; by_provider: { provider_key: string; tokens: number; calls: number }[]; by_operation: { operation: string; tokens: number }[]; monthly_tokens: { month: string; tokens: number }[] }

function UsageBudgetCard({ pid, settings }: { pid: string; settings: Record<string, any> }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["usage", pid], queryFn: () => api.get<Usage>(`/projects/${pid}/usage`) });
  const [budget, setBudget] = useState<string>("");
  const [digest, setDigest] = useState<boolean>(settings?.digest_enabled !== false);
  const saveBudget = useMutation({ mutationFn: () => api.put(`/projects/${pid}/usage/budget`, { monthly_token_budget: Number(budget || 0) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["usage", pid] }) });
  const saveDigest = useMutation({ mutationFn: (on: boolean) => api.patch(`/projects/${pid}`, { settings: { ...settings, digest_enabled: on } }), onSuccess: () => qc.invalidateQueries({ queryKey: ["project", pid] }) });
  const budgetValue = budget !== "" ? Number(budget) : (data?.budget ?? 0);
  const pct = data?.budget_used_pct;
  return (
    <Card>
      <CardHeader><CardTitle info="AI tokens spent this month on visibility sampling, the analyst and content writing. Set a monthly cap so a project cannot run away; 0 means unlimited.">AI usage & budget</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-md border p-3"><div className="text-xs text-muted-foreground">Tokens this month</div><div className="mt-1 text-2xl font-semibold tabular-nums">{(data?.tokens_this_month ?? 0).toLocaleString()}</div></div>
          <div className="rounded-md border p-3"><div className="text-xs text-muted-foreground">Monthly budget</div><div className="mt-1 text-2xl font-semibold tabular-nums">{data?.budget ? data.budget.toLocaleString() : "unlimited"}</div>{pct != null && <div className={"mt-1 text-xs " + (pct >= 1 ? "text-red-600" : pct >= 0.8 ? "text-amber-600" : "text-muted-foreground")}>{Math.round(pct * 100)}% used</div>}</div>
        </div>
        {pct != null && <div className="h-2 w-full rounded bg-slate-100 dark:bg-slate-800 overflow-hidden"><div className={"h-2 " + (pct >= 1 ? "bg-red-500" : pct >= 0.8 ? "bg-amber-500" : "bg-primary")} style={{ width: `${Math.min(100, pct * 100)}%` }} /></div>}
        <form className="flex gap-2 items-end" onSubmit={(e) => { e.preventDefault(); saveBudget.mutate(); }}>
          <Field label="Monthly token budget (0 = unlimited)"><Input type="number" min={0} step={1000} value={budget} placeholder={String(budgetValue)} onChange={(e) => setBudget(e.target.value)} /></Field>
          <Button type="submit" disabled={saveBudget.isPending}>Save budget</Button>
        </form>
        {(data?.by_provider?.length ?? 0) > 0 && (
          <div className="text-xs text-muted-foreground">This month: {data!.by_provider.map((p) => `${p.provider_key} ${p.tokens.toLocaleString()} tokens (${p.calls} calls)`).join(" · ")}</div>
        )}
        <label className="flex items-center gap-2 text-sm pt-2 border-t"><input type="checkbox" checked={digest} onChange={(e) => { setDigest(e.target.checked); saveDigest.mutate(e.target.checked); }} /> Email members a weekly summary (Mondays)</label>
      </CardContent>
    </Card>
  );
}
