import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Domain, type Keyword, type Project } from "@/lib/api";
import { useDomains, useProject, useProjectId } from "@/hooks/useProject";
import { ErrorBox, Loading, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { useEnqueue } from "@/hooks/useJobs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { TimeAgo } from "@/components/ui/time";
import { fmtInt, fmtNum } from "@/lib/utils";
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
  const { data: keywords } = useQuery({ queryKey: ["keywords", pid], queryFn: () => api.get<Keyword[]>(`/projects/${pid}/keywords`) });
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
  const [kw, setKw] = useState({ text: "", importance: 3 });
  const addKw = useMutation({ mutationFn: () => api.post(`/projects/${pid}/keywords`, kw.text.split("\n").map((t) => t.trim()).filter(Boolean).map((text) => ({ text, importance: kw.importance, country: project?.default_country, language: project?.default_language }))), onSuccess: () => { qc.invalidateQueries({ queryKey: ["keywords", pid] }); setKw({ text: "", importance: 3 }); } });
  const delKw = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/keywords/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["keywords", pid] }) });
  const promoteKw = useMutation({ mutationFn: (id: string) => api.patch(`/projects/${pid}/keywords/${id}`, { is_target: true, importance: 3 }), onSuccess: () => qc.invalidateQueries({ queryKey: ["keywords", pid] }) });
  const enqueue = useEnqueue();
  const [sched, setSched] = useState({ task_type: "sync_search_console", interval_minutes: 1440, domain_id: "" });
  const addSched = useMutation({ mutationFn: () => api.post(`/projects/${pid}/schedules`, { task_type: sched.task_type, interval_minutes: sched.interval_minutes, params: sched.domain_id ? { domain_id: sched.domain_id } : {}, label: `${sched.task_type} every ${sched.interval_minutes} min` }), onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules", pid] }) });
  const delSched = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/schedules/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules", pid] }) });
  const delProject = useMutation({ mutationFn: () => api.delete(`/projects/${pid}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); window.location.href = "/"; } });
  const primaryDomains = (domains ?? []).filter((d) => d.role === "primary" && (!domainFilter || `${d.hostname} ${d.gsc_property ?? ""} ${d.ga4_property ?? ""}`.toLowerCase().includes(domainFilter.toLowerCase())));
  const filteredSchedules = (schedules ?? []).filter((row) => !scheduleFilter || `${row.task_type} ${row.label ?? ""} ${JSON.stringify(row.params)}`.toLowerCase().includes(scheduleFilter.toLowerCase()));
  const pagedSchedules = usePaged(filteredSchedules, 10);
  const targets = (keywords ?? []).filter((k) => k.is_target);
  const candidates = (keywords ?? []).filter((k) => !k.is_target);
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
        <Card className="lg:col-span-2"><CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle info="Keywords you want to be found for. Volume, difficulty and CPC come from the connected keyword provider and are estimates, not measurements. Only target keywords are priced and rank-checked.">Target keywords ({targets.length})</CardTitle>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => enqueue.mutate({ task_type: "discover_keywords", params: {} })} disabled={enqueue.isPending} title="Expand your target keywords into candidates using Google autocomplete, People Also Ask and Trends. Candidates arrive switched off, for you to promote.">Discover keywords</Button>
            <Button size="sm" variant="outline" onClick={() => enqueue.mutate({ task_type: "sync_keyword_metrics", params: {} })} disabled={enqueue.isPending}>Re-run</Button>
          </div>
        </CardHeader><CardContent className="space-y-3">
          <KeywordTable pid={pid} keywords={targets} onDelete={(id) => delKw.mutate(id)} />
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); addKw.mutate(); }}><Textarea rows={3} placeholder="one keyword per line" value={kw.text} onChange={(e) => setKw({ ...kw, text: e.target.value })} /><div className="flex gap-2 items-center"><Select className="w-40" value={kw.importance} onChange={(e) => setKw({ ...kw, importance: Number(e.target.value) })}>{[1, 2, 3, 4, 5].map((i) => <option key={i} value={i}>importance {i}</option>)}</Select><Button type="submit" disabled={addKw.isPending}>Add keywords</Button></div></form>
        </CardContent></Card>
        {!!candidates.length && (
          <Card className="lg:col-span-2"><CardHeader><CardTitle info="Found by “Discover keywords” from Google autocomplete, People Also Ask and Trends. They are not tracked or priced until you promote one — that is what keeps discovery cheap and pricing deliberate.">Keyword candidates ({candidates.length})</CardTitle></CardHeader><CardContent>
            <CandidateTable keywords={candidates} onPromote={(id) => promoteKw.mutate(id)} onDelete={(id) => delKw.mutate(id)} busy={promoteKw.isPending} />
          </CardContent></Card>
        )}
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

interface KeywordMetrics {
  available: boolean; provider?: string; observed_on?: string; reason?: string; connected_provider?: string | null;
  totals?: { keywords: number; total_volume: number; avg_difficulty: number | null; unpriced: number };
  keywords?: { id: string; text: string; importance: number; search_volume: number | null; difficulty: number | null; cpc: number | null; intent: string | null; volume_change: number | null }[];
}

/** Discovered candidates: where each came from, and the one click that starts spending money on it. */
function CandidateTable({ keywords, onPromote, onDelete, busy }:
  { keywords: Keyword[]; onPromote: (id: string) => void; onDelete: (id: string) => void; busy: boolean }) {
  const [filter, setFilter] = useState("");
  const rows = keywords.filter((row) => !filter || `${row.text} ${row.source ?? ""} ${(row.tags ?? []).join(" ")}`.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows, 25);
  const columns: CsvColumn<Keyword>[] = [
    { key: "keyword", label: "Keyword", value: (r) => r.text }, { key: "source", label: "Found via", value: (r) => r.source },
    { key: "tags", label: "Tags", value: (r) => (r.tags ?? []).join(", ") }, { key: "country", label: "Country", value: (r) => r.country },
    { key: "language", label: "Language", value: (r) => r.language },
  ];
  return (
    <>
      <div className="mb-3 flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter candidates…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="keyword-candidates.csv" rows={rows} columns={columns} /></div></div>
      <Table>
        <THead><TR><TH>Keyword</TH><TH>Found via</TH><TH>From seed</TH><TH /></TR></THead>
        <TBody>{paged.items.map((k) => (
          <TR key={k.id}>
            <TD className="text-sm">{k.text}</TD>
            <TD className="text-xs text-muted-foreground">{(k.source ?? "").replace(/^serpapi:/, "").replace(/\+/g, " + ")}</TD>
            <TD className="text-xs text-muted-foreground">{(k.tags ?? []).find((t) => t.startsWith("seed:"))?.slice(5) ?? "—"}</TD>
            <TD className="text-right whitespace-nowrap">
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onPromote(k.id)} title="Track this keyword: it becomes a target, so pricing and rank checks include it.">Make target</Button>
              <Button size="sm" variant="ghost" onClick={() => onDelete(k.id)}>Discard</Button>
            </TD>
          </TR>))}
        </TBody>
      </Table>
      <Pagination state={paged} label="candidates" />
    </>
  );
}

function KeywordTable({ pid, keywords, onDelete }: { pid: string; keywords: Keyword[]; onDelete: (id: string) => void }) {
  const [filter, setFilter] = useState("");
  const { data } = useQuery({ queryKey: ["keyword-metrics", pid], queryFn: () => api.get<KeywordMetrics>(`/projects/${pid}/seo/keyword-metrics`), enabled: !!pid });
  const priced = new Map((data?.keywords ?? []).map((k) => [k.id, k]));
  const rows = keywords.map((k) => ({ ...k, m: priced.get(k.id) })).filter((row) => !filter || `${row.text} ${row.m?.intent ?? ""} ${row.country} ${row.language}`.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows, 25);
  const columns: CsvColumn<(typeof rows)[number]>[] = [
    { key: "keyword", label: "Keyword", value: (r) => r.text }, { key: "volume", label: "Volume", value: (r) => r.m?.search_volume },
    { key: "difficulty", label: "Difficulty", value: (r) => r.m?.difficulty }, { key: "cpc", label: "CPC", value: (r) => r.m?.cpc },
    { key: "intent", label: "Intent", value: (r) => r.m?.intent }, { key: "priority", label: "Priority", value: (r) => r.importance },
    { key: "country", label: "Country", value: (r) => r.country }, { key: "language", label: "Language", value: (r) => r.language },
  ];
  if (!keywords.length) return <p className="text-sm text-muted-foreground">No target keywords yet — add some below.</p>;
  return (
    <>
      {data?.available
        ? <p className="text-xs text-muted-foreground">{data.provider} · {data.observed_on} · {fmtInt(data.totals!.total_volume)} searches/mo across {data.totals!.keywords} priced keyword(s){data.totals!.unpriced > 0 && ` · ${data.totals!.unpriced} not priced yet`}</p>
        : <p className="text-xs text-muted-foreground">{data?.connected_provider ? "Click “Refresh keyword data” to fetch volume and difficulty." : "Connect a provider under Integrations → Keyword & SERP data to see volume, difficulty and CPC."}</p>}
      <div className="flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter target keywords…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="target-keywords.csv" rows={rows} columns={columns} /></div></div>
      <Table>
        <THead><TR><TH>Keyword</TH><TH className="text-right">Volume</TH><TH className="text-right">Difficulty</TH><TH className="text-right">CPC</TH><TH>Intent</TH><TH className="text-right">Priority</TH><TH /></TR></THead>
        <TBody>{paged.items.map((k) => (
          <TR key={k.id}>
            <TD className="text-sm">{k.text}<div className="text-xs text-muted-foreground">{k.language}-{k.country}</div></TD>
            <TD className="text-right tabular-nums">
              {k.m?.search_volume != null ? fmtInt(k.m.search_volume) : <span className="text-xs text-muted-foreground">—</span>}
              {!!k.m?.volume_change && <div className={"text-xs " + (k.m.volume_change > 0 ? "text-emerald-600" : "text-red-600")}>{k.m.volume_change > 0 ? "+" : ""}{fmtInt(k.m.volume_change)}</div>}
            </TD>
            <TD className="text-right tabular-nums">{k.m?.difficulty != null ? fmtNum(k.m.difficulty, 0) : <span className="text-xs text-muted-foreground">—</span>}</TD>
            <TD className="text-right tabular-nums text-xs">{k.m?.cpc != null ? `$${k.m.cpc.toFixed(2)}` : <span className="text-muted-foreground">—</span>}</TD>
            <TD className="text-xs text-muted-foreground">{k.m?.intent ?? "—"}</TD>
            <TD className="text-right text-xs text-muted-foreground">{k.importance}/5</TD>
            <TD className="text-right"><Button size="sm" variant="ghost" onClick={() => onDelete(k.id)}>Remove</Button></TD>
          </TR>))}
        </TBody>
      </Table>
      <Pagination state={paged} label="keywords" />
    </>
  );
}
