import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Domain, type Project } from "@/lib/api";
import { useDomains, useProject, useProjectId } from "@/hooks/useProject";
import { ErrorBox, InfoHint, Loading, PageHeader } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { TimeAgo } from "@/components/ui/time";
import { RevenueModelCard } from "@/components/RevenueModel";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

interface Schedule { id: string; task_type: string; params: Record<string, unknown>; interval_minutes: number; is_enabled: boolean; next_run_at: string; last_enqueued_at: string | null; label: string | null }
const SCHEDULE_COLUMNS: CsvColumn<Schedule>[] = [
  { key: "task", label: "Task", value: (r) => r.task_type }, { key: "params", label: "Parameters", value: (r) => JSON.stringify(r.params) },
  { key: "interval", label: "Interval minutes", value: (r) => r.interval_minutes }, { key: "enabled", label: "Enabled", value: (r) => r.is_enabled },
  { key: "next", label: "Next run", value: (r) => r.next_run_at }, { key: "last", label: "Last run", value: (r) => r.last_enqueued_at },
];
const DOMAIN_TASKS = new Set(["crawl_domain", "measure_performance", "sync_search_console", "sync_bing_webmaster", "sync_analytics", "sync_backlinks"]);
const FREQUENCIES = [
  { value: 0, label: "Never" },
  { value: 360, label: "Every 6 hours" },
  { value: 1440, label: "Daily" },
  { value: 10080, label: "Weekly" },
  { value: 43200, label: "Monthly" },
];

interface ScheduleRow { key: string; taskType: string; description: string; domain?: Domain; schedule?: Schedule }

const scheduleKey = (taskType: string, domainId?: string) => `${taskType}:${domainId ?? ""}`;
const taskLabel = (taskType: string) => taskType.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());

export function SettingsPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const { data: project, isLoading } = useProject();
  const { data: domains } = useDomains();
  const { data: schedules } = useQuery({ queryKey: ["schedules", pid], queryFn: () => api.get<Schedule[]>(`/projects/${pid}/schedules`) });
  const { data: tasks } = useQuery({ queryKey: ["tasks"], queryFn: () => api.get<Record<string, string>>("/tasks") });
  const [form, setForm] = useState<Partial<Project> & { aliases?: string } | null>(null);
  const f = form ?? { ...project, aliases: project?.brand_aliases.join(", ") };
  const save = useMutation({ mutationFn: () => api.patch<Project>(`/projects/${pid}`, { name: f.brand_name, brand_name: f.brand_name, description: f.description, default_country: f.default_country, default_language: f.default_language, brand_aliases: (f.aliases ?? "").split(",").map((s) => s.trim()).filter(Boolean) }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["project", pid] }); qc.invalidateQueries({ queryKey: ["projects"] }); } });
  const [url, setUrl] = useState("");
  const addDomain = useMutation({ mutationFn: () => api.post<Domain>(`/projects/${pid}/domains`, { url, role: "primary" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["domains", pid] }); setUrl(""); } });
  const delDomain = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/domains/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["domains", pid] }) });
  const setSchedule = useMutation({
    mutationFn: ({ row, interval }: { row: ScheduleRow; interval: number }) => {
      if (!row.schedule && interval === 0) return Promise.resolve();
      const payload = {
        task_type: row.taskType,
        interval_minutes: interval || row.schedule?.interval_minutes || 1440,
        params: row.domain ? { domain_id: row.domain.id } : (row.schedule?.params ?? {}),
        label: row.domain ? `${row.taskType} · ${row.domain.hostname}` : row.taskType,
        is_enabled: interval > 0,
      };
      return row.schedule
        ? api.patch(`/projects/${pid}/schedules/${row.schedule.id}`, payload)
        : api.post(`/projects/${pid}/schedules`, payload);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules", pid] }),
  });
  const delProject = useMutation({ mutationFn: () => api.delete(`/projects/${pid}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); window.location.href = "/"; } });
  const primaryDomains = (domains ?? []).filter((domain) => domain.role === "primary");
  const scheduleMap = new Map((schedules ?? []).map((schedule) => [scheduleKey(schedule.task_type, schedule.params.domain_id as string | undefined), schedule]));
  const scheduleRows: ScheduleRow[] = Object.entries(tasks ?? {}).flatMap(([taskType, description]) => {
    if (DOMAIN_TASKS.has(taskType)) {
      return primaryDomains.map((domain) => ({ key: scheduleKey(taskType, domain.id), taskType, description, domain, schedule: scheduleMap.get(scheduleKey(taskType, domain.id)) }));
    }
    return [{ key: scheduleKey(taskType), taskType, description, schedule: scheduleMap.get(scheduleKey(taskType)) }];
  });
  if (isLoading || !project) return <Loading />;
  return (
    <div>
      <PageHeader title="Settings" />
      <div className="grid gap-8 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Brand</CardTitle></CardHeader><CardContent className="space-y-5">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <Field label="Brand name"><Input required value={f.brand_name ?? ""} onChange={(e) => setForm({ ...f, brand_name: e.target.value })} /></Field>
            <Field label="Brand aliases (comma separated)"><Input value={f.aliases ?? ""} onChange={(e) => setForm({ ...f, aliases: e.target.value })} /></Field>
            <Field label="Description (used by the AI analyst)"><Textarea rows={3} value={f.description ?? ""} onChange={(e) => setForm({ ...f, description: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3"><Field label="Default country"><Input value={f.default_country ?? ""} onChange={(e) => setForm({ ...f, default_country: e.target.value })} /></Field><Field label="Default language"><Input value={f.default_language ?? ""} onChange={(e) => setForm({ ...f, default_language: e.target.value })} /></Field></div>
            <ErrorBox error={save.error} /><Button type="submit" disabled={save.isPending}>Save</Button>
          </form>
          <div className="border-t pt-4">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5"><Label>Website URLs</Label><InfoHint label="Website URLs explanation" hover>Add every website owned by this brand. Competitor websites are managed under Competitors.</InfoHint></div>
              <div className="space-y-2">
                {primaryDomains.map((domain) => (
                  <div key={domain.id} className="flex items-center gap-2">
                    <Input value={domain.base_url} readOnly />
                    <Button type="button" size="sm" variant="ghost" onClick={() => delDomain.mutate(domain.id)}>Remove</Button>
                  </div>
                ))}
                <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); addDomain.mutate(); }}>
                  <Input type="url" required placeholder="https://www.example.com" value={url} onChange={(event) => setUrl(event.target.value)} />
                  <Button type="submit" disabled={addDomain.isPending}>Add</Button>
                </form>
              </div>
            </div>
            <ErrorBox error={addDomain.error || delDomain.error} />
          </div>
        </CardContent></Card>
        <RevenueModelCard pid={pid} />
        <Card className="border-0 bg-transparent shadow-none lg:col-span-2"><CardHeader className="flex-row items-center justify-between space-y-0 p-0 pb-3"><CardTitle info="Choose how often each task runs automatically. Select Never to turn a task off without removing its history.">Recurring schedules</CardTitle><CsvExportButton filename="recurring-schedules.csv" rows={schedules ?? []} columns={SCHEDULE_COLUMNS} /></CardHeader><CardContent className="space-y-3 p-0">
          <Table><THead><TR><TH>Task</TH><TH>Scope</TH><TH>Every</TH><TH>Next run</TH><TH>Last run</TH></TR></THead><TBody>{scheduleRows.map((row) => (
            <TR key={row.key}>
              <TD><div className="flex items-center gap-1.5 text-sm font-medium">{taskLabel(row.taskType)}<InfoHint label={`${taskLabel(row.taskType)} description`} hover>{row.description}</InfoHint></div></TD>
              <TD className="text-xs text-muted-foreground">{row.domain?.hostname ?? "Brand all data"}</TD>
              <TD><Select className="w-40" value={row.schedule?.is_enabled ? row.schedule.interval_minutes : 0} disabled={setSchedule.isPending} onChange={(event) => setSchedule.mutate({ row, interval: Number(event.target.value) })}>
                {FREQUENCIES.map((frequency) => <option key={frequency.value} value={frequency.value}>{frequency.label}</option>)}
              </Select></TD>
              <TD className="text-xs"><TimeAgo value={row.schedule?.is_enabled ? row.schedule.next_run_at : null} fallback="—" /></TD>
              <TD className="text-xs"><TimeAgo value={row.schedule?.last_enqueued_at} fallback="Never" /></TD>
            </TR>
          ))}</TBody></Table>
          {!primaryDomains.length && <p className="text-xs text-muted-foreground">Add a website above to configure website-specific tasks.</p>}
          <ErrorBox error={setSchedule.error} />
        </CardContent></Card>
        <UsageBudgetCard pid={pid} settings={project.settings as Record<string, any>} />
        <Card>
          <CardHeader><CardTitle>Danger zone</CardTitle></CardHeader>
          <CardContent><Button variant="destructive" onClick={() => { if (confirm("Delete this brand and all its data?")) delProject.mutate(); }}>Delete brand</Button></CardContent>
        </Card>
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
      <CardHeader><CardTitle info="AI tokens spent this month on visibility sampling, the analyst and content writing. Set a monthly cap for this brand; 0 means unlimited.">AI usage & budget</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div>
          <div className="flex items-baseline justify-center gap-1.5 p-3 text-center"><span className="text-2xl font-semibold tabular-nums">{(data?.tokens_this_month ?? 0).toLocaleString()}</span><span className="text-sm text-muted-foreground">tokens / this month</span></div>
        </div>
        {pct != null && <div className="h-2 w-full rounded bg-slate-100 dark:bg-slate-800 overflow-hidden"><div className={"h-2 " + (pct >= 1 ? "bg-red-500" : pct >= 0.8 ? "bg-amber-500" : "bg-primary")} style={{ width: `${Math.min(100, pct * 100)}%` }} /></div>}
        <form className="flex gap-2 items-end" onSubmit={(e) => { e.preventDefault(); saveBudget.mutate(); }}>
          <Field label="Monthly token budget (0 = unlimited)"><Input type="number" min={0} step={1000} value={budget} placeholder={String(budgetValue)} onChange={(e) => setBudget(e.target.value)} /></Field>
          <Button type="submit" disabled={saveBudget.isPending}>Save budget</Button>
        </form>
        <label className="flex items-center gap-2 pt-2 text-sm"><input type="checkbox" checked={digest} onChange={(e) => { setDigest(e.target.checked); saveDigest.mutate(e.target.checked); }} /> Email members a weekly summary (Mondays)</label>
      </CardContent>
    </Card>
  );
}
