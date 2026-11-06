import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Competitor, type Domain } from "@/lib/api";
import { useCompetitors, useDomains, useProject, useProjectId } from "@/hooks/useProject";
import { useActiveTab } from "@/hooks/useTabRoute";
import { COMPETITOR_TABS } from "@/lib/nav";
import { useEnqueue } from "@/hooks/useJobs";
import { EmptyState, ErrorBox, Loading, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { Badge } from "@/components/ui/badge";
import { fmtInt, fmtPct } from "@/lib/utils";
import { TimeAgo } from "@/components/ui/time";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

interface Change { id: string; competitor: string | null; url: string; status_code: number | null; title: string | null; changed: boolean; change_ratio: number | null; diff_summary: { added?: string[]; removed?: string[]; prices_added?: string[]; prices_removed?: string[]; added_count?: number; removed_count?: number }; observed_at: string }
interface Watched { url: string; competitor: string | null; last_observed_at: string; status_code: number | null; changed_last_time: boolean; title: string | null }
interface Visibility { summary: { competitors: Record<string, number>; brand_mention_rate: number | null; samples: number }; previous: { competitors: Record<string, number>; brand_mention_rate: number | null } | null }
const COMPETITOR_COLUMNS: CsvColumn<Competitor>[] = [
  { key: "name", label: "Competitor", value: (r) => r.name }, { key: "aliases", label: "Aliases", value: (r) => r.aliases.join(", ") },
  { key: "notes", label: "Notes", value: (r) => r.notes },
];
const WATCH_COLUMNS: CsvColumn<WatchRow>[] = [
  { key: "url", label: "URL", value: (r) => r.url }, { key: "competitor", label: "Competitor", value: (r) => r.competitor },
  { key: "hostname", label: "Hostname", value: (r) => r.hostname }, { key: "status", label: "Status", value: (r) => r.obs?.status_code },
  { key: "checked", label: "Last checked", value: (r) => r.obs?.last_observed_at }, { key: "changed", label: "Changed last time", value: (r) => r.obs?.changed_last_time },
];

/** Per-tab page heading and its info tooltip, keyed by the tab id from COMPETITOR_TABS. */
const COMPETITOR_TAB_META: Record<string, { title: string; info: string }> = {
  "competitors": { title: "Competitors", info: "Who you are compared against in AI answers and search, plus change detection on their pricing and feature pages." },
  "watched-pages": { title: "Watched pages", info: "Change detection on the competitor pages you choose to watch, such as pricing and features." },
  "keyword-gap": { title: "Keyword gap", info: "Keywords your competitors rank for that you do not, ranked by opportunity." },
  "page-changes": { title: "Page changes", info: "What changed on a watched competitor page between two checks." },
};

export function CompetitorsPage() {
  const pid = useProjectId();
  const { data: competitors, isLoading } = useCompetitors();
  const { data: domains } = useDomains();
  const enqueue = useEnqueue();
  const tab = useActiveTab(COMPETITOR_TABS, "competitors");
  const [editing, setEditing] = useState<Competitor | null | "new">(null);
  const [addingWatch, setAddingWatch] = useState(false);
  if (isLoading) return <Loading />;
  return (
    <div>
      <PageHeader
        title={COMPETITOR_TAB_META[tab]?.title ?? "Competitors"}
        info={COMPETITOR_TAB_META[tab]?.info ?? "Who you are compared against in AI answers and search, plus change detection on their pricing and feature pages."}
        actions={<>
          {tab === "competitors" && <Button onClick={() => setEditing("new")}>Add competitor</Button>}
          {tab === "watched-pages" && <Button onClick={() => setAddingWatch(true)}>Add</Button>}
          {tab === "keyword-gap" && <Button variant="outline" onClick={() => enqueue.mutate({ task_type: "sync_ranked_keywords", params: {} })} disabled={enqueue.isPending}>Re-run</Button>}
          {tab !== "competitors" && tab !== "keyword-gap" && <Button variant="outline" onClick={() => enqueue.mutate({ task_type: "watch_competitor_pages", params: { include_home: true } })} disabled={enqueue.isPending}>Re-run</Button>}
        </>}
      />
      <ErrorBox error={enqueue.error} />
      {tab === "competitors" && <CompetitorTable pid={pid} competitors={competitors ?? []} domains={domains ?? []} onEdit={setEditing} />}
      {tab === "watched-pages" && <WatchedPages pid={pid} adding={addingWatch} onAddDone={() => setAddingWatch(false)} />}
      {tab === "keyword-gap" && <KeywordGap pid={pid} />}
      {tab === "page-changes" && <PageChanges pid={pid} />}
      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        {editing !== null && (
          <DialogContent title={editing === "new" ? "Add competitor" : `Edit ${editing.name}`}>
            <CompetitorForm pid={pid} competitor={editing === "new" ? null : editing} domains={domains ?? []} onDone={() => setEditing(null)} />
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}

/** Every competitor in one table: who they are, where they are, and how visible they are in AI answers. */
function CompetitorTable({ pid, competitors, domains, onEdit }: { pid: string; competitors: Competitor[]; domains: Domain[]; onEdit: (c: Competitor) => void }) {
  const [filter, setFilter] = useState("");
  const qc = useQueryClient();
  const { data: project } = useProject();
  const { data: vis } = useQuery({ queryKey: ["visibility", pid], queryFn: () => api.get<Visibility>(`/projects/${pid}/geo/visibility`) });
  const del = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/competitors/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["competitors", pid] }); qc.invalidateQueries({ queryKey: ["domains", pid] }); } });
  const rows = competitors.filter((row) => !filter || `${row.name} ${row.aliases.join(" ")} ${row.notes ?? ""}`.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows);
  if (!competitors.length) return <EmptyState title="No competitors yet">Add the competitors you want to track.</EmptyState>;
  return (
    <>
      <div className="mb-3 flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter competitors…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="competitors.csv" rows={rows} columns={COMPETITOR_COLUMNS} /></div></div>
      <Table>
        <THead><TR><TH>Competitor</TH><TH>Aliases</TH><TH>Websites</TH><TH className="text-right">AI mentions</TH><TH>Trend</TH><TH className="text-right">Watched URLs</TH><TH /></TR></THead>
        <TBody>
          {paged.items.map((c) => {
            const sites = domains.filter((d) => d.competitor_id === c.id);
            const rate = vis?.summary.competitors[c.name];
            const before = vis?.previous?.competitors[c.name];
            const d = rate != null && before != null ? rate - before : null;
            return (
              <TR key={c.id}>
                <TD><div className="font-medium">{c.name}</div>{c.notes && <div className="text-xs text-muted-foreground line-clamp-2">{c.notes}</div>}</TD>
                <TD className="text-xs text-muted-foreground">{c.aliases.join(", ") || "—"}</TD>
                <TD className="text-xs">{sites.length ? sites.map((s) => s.hostname).join(", ") : <span className="text-muted-foreground">—</span>}</TD>
                <TD className="text-right tabular-nums">{rate != null ? fmtPct(rate, 0) : <span className="text-xs text-muted-foreground">—</span>}</TD>
                <TD>{d == null ? <span className="text-xs text-muted-foreground">—</span>
                  : d >= 0.1 ? <Badge variant="warning">gaining +{Math.round(d * 100)} pts</Badge>
                  : d <= -0.1 ? <Badge variant="success">losing {Math.round(d * 100)} pts</Badge>
                  : <span className="text-xs text-muted-foreground">stable</span>}</TD>
                <TD className="text-right tabular-nums text-xs">{sites.reduce((n, s) => n + (s.watch_urls?.length ?? 0), 0)}</TD>
                <TD className="whitespace-nowrap text-right">
                  <Button size="sm" variant="ghost" onClick={() => onEdit(c)}>Edit</Button>
                  <Button size="sm" variant="ghost" onClick={() => { if (confirm(`Remove ${c.name}?`)) del.mutate(c.id); }}>Remove</Button>
                </TD>
              </TR>
            );
          })}
        </TBody>
      </Table>
      <Pagination state={paged} label="competitors" />
      <ErrorBox error={del.error} />
      {vis?.summary.samples ? <p className="mt-2 text-xs text-muted-foreground">AI mentions: share of {vis.summary.samples} sampled answers in the latest run. {project?.name ?? "Your brand"}: {fmtPct(vis.summary.brand_mention_rate, 0)}.</p> : null}
    </>
  );
}

function CompetitorForm({ pid, competitor, domains, onDone }: { pid: string; competitor: Competitor | null; domains: Domain[]; onDone: () => void }) {
  const qc = useQueryClient();
  const sites = competitor ? domains.filter((d) => d.competitor_id === competitor.id) : [];
  const [form, setForm] = useState({
    name: competitor?.name ?? "",
    aliases: (competitor?.aliases ?? []).join(", "),
    website: "",
    notes: competitor?.notes ?? "",
  });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["competitors", pid] }); qc.invalidateQueries({ queryKey: ["domains", pid] }); };
  const save = useMutation({
    mutationFn: () => {
      const body = { name: form.name, aliases: form.aliases.split(",").map((s) => s.trim()).filter(Boolean), website: form.website || null, notes: form.notes || null };
      return competitor
        ? api.patch<Competitor>(`/projects/${pid}/competitors/${competitor.id}`, body)
        : api.post<Competitor>(`/projects/${pid}/competitors`, body);
    },
    onSuccess: () => { refresh(); onDone(); },
  });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label="Name"><Input required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label="Aliases (comma separated)" help="Other spellings or product names used to detect mentions."><Input value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} /></Field>
      <Field label={sites.length ? "Add another website" : "Website"} help={sites.length ? `Already tracking: ${sites.map((s) => s.hostname).join(", ")}` : undefined}>
        <Input value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} placeholder="https://competitor.com" />
      </Field>
      <Field label="Notes"><Textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
      <ErrorBox error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>{competitor ? "Save" : "Add"}</Button>
        <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

/** Watched pages as one table with the same add / edit / remove buttons as the competitor list. */
function WatchedPages({ pid, adding, onAddDone }: { pid: string; adding: boolean; onAddDone: () => void }) {
  const [filter, setFilter] = useState("");
  const { data: domains } = useDomains();
  const { data: competitors } = useCompetitors();
  const { data: watched } = useQuery({ queryKey: ["watched", pid], queryFn: () => api.get<Watched[]>(`/projects/${pid}/brand/watched`) });
  const [editing, setEditing] = useState<WatchRow | null>(null);
  const sites = (domains ?? []).filter((d) => d.role === "competitor");
  const save = useSaveWatchUrls(pid);

  const rows: WatchRow[] = sites.flatMap((d) =>
    (d.watch_urls ?? []).map((url) => ({
      domainId: d.id,
      hostname: d.hostname,
      url,
      competitor: competitors?.find((c) => c.id === d.competitor_id)?.name ?? d.hostname,
      obs: watched?.find((w) => w.url === url),
    })));

  const filteredRows = rows.filter((row) => !filter || `${row.url} ${row.hostname} ${row.competitor}`.toLowerCase().includes(filter.toLowerCase()));
  const pagedRows = usePaged(filteredRows);

  const remove = (row: WatchRow) => {
    const site = sites.find((d) => d.id === row.domainId);
    if (!site) return;
    save.mutate([{ id: site.id, urls: (site.watch_urls ?? []).filter((u) => u !== row.url) }]);
  };

  return (
    <>
      {!sites.length ? (
        <EmptyState title="No competitor websites yet">Add a competitor with a website first, then watch its pricing and feature pages.</EmptyState>
      ) : !rows.length ? (
        <EmptyState title="No watched pages yet">Use “Add watched page” to pick the pages worth checking for changes.</EmptyState>
      ) : (
        <>
          <div className="mb-3 flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter watched pages…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="watched-competitor-pages.csv" rows={filteredRows} columns={WATCH_COLUMNS} /></div></div>
          <Table>
            <THead><TR><TH>URL</TH><TH>Competitor</TH><TH>Status</TH><TH>Last checked</TH><TH>Changed last time</TH><TH /></TR></THead>
            <TBody>{pagedRows.items.map((r) => (
              <TR key={`${r.domainId}:${r.url}`}>
                <TD className="text-xs max-w-md truncate" title={r.url}>{r.url}</TD>
                <TD>{r.competitor}</TD>
                <TD>{r.obs?.status_code ?? <span className="text-xs text-muted-foreground">—</span>}</TD>
                <TD className="text-xs"><TimeAgo value={r.obs?.last_observed_at} fallback="never" /></TD>
                <TD>{r.obs?.changed_last_time
                  ? <Link to="/competitors/page-changes" title="See what changed"><Badge variant="warning" className="cursor-pointer hover:opacity-80">yes</Badge></Link>
                  : <span className="text-muted-foreground">no</span>}</TD>
                <TD className="whitespace-nowrap text-right">
                  <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Edit</Button>
                  <Button size="sm" variant="ghost" onClick={() => { if (confirm(`Stop watching ${r.url}?`)) remove(r); }}>Remove</Button>
                </TD>
              </TR>))}
            </TBody>
          </Table>
          <Pagination state={pagedRows} label="pages" />
          <ErrorBox error={save.error} />
        </>
      )}
      <Dialog open={adding || editing !== null} onOpenChange={(o) => { if (!o) { setEditing(null); onAddDone(); } }}>
        {(adding || editing) && (
          <DialogContent title={editing ? "Edit watched page" : "Add watched pages"} className="max-w-md">
            <WatchedPageForm pid={pid} sites={sites} competitors={competitors ?? []} row={editing}
              onDone={() => { setEditing(null); onAddDone(); }} />
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}

interface WatchRow { domainId: string; hostname: string; url: string; competitor: string; obs?: Watched }

/** Watch URLs are a list on the competitor's domain, so every edit is a rewrite of that list. */
function useSaveWatchUrls(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (updates: { id: string; urls: string[] }[]) => {
      for (const u of updates) await api.patch(`/projects/${pid}/domains/${u.id}`, { watch_urls: u.urls });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["domains", pid] }),
  });
}

function WatchedPageForm({ pid, sites, competitors, row, onDone }: { pid: string; sites: Domain[]; competitors: Competitor[]; row: WatchRow | null; onDone: () => void }) {
  const save = useSaveWatchUrls(pid);
  const [domainId, setDomainId] = useState(row?.domainId ?? sites[0]?.id ?? "");
  const [text, setText] = useState(row?.url ?? "");
  const site = sites.find((d) => d.id === domainId);
  const [error, setError] = useState<string | null>(null);

  const entered = text.split("\n").map((u) => u.trim()).filter(Boolean);
  const offSite = site ? entered.filter((u) => !u.includes(site.hostname)) : [];

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!site || !entered.length) return;
    const existing = (site.watch_urls ?? []).filter((u) => u !== row?.url);
    const fresh = [...new Set(entered)].filter((u) => !existing.includes(u));
    if (!fresh.length) { setError(entered.length > 1 ? "All of those pages are already watched on this site." : "That page is already watched on this site."); return; }
    const updates = [{ id: site.id, urls: [...existing, ...fresh] }];
    // Moving a page to a different site means dropping it from the old one too.
    if (row && row.domainId !== site.id) {
      const old = sites.find((d) => d.id === row.domainId);
      if (old) updates.push({ id: old.id, urls: (old.watch_urls ?? []).filter((u) => u !== row.url) });
    }
    save.mutate(updates, { onSuccess: onDone });
  };

  const placeholder = site ? `${site.base_url.replace(/\/$/, "")}/pricing` : "https://competitor.com/pricing";
  return (
    <form className="space-y-3" onSubmit={submit}>
      <Field label="Competitor site" help="Which competitor these pages belong to.">
        <Select value={domainId} onChange={(e) => setDomainId(e.target.value)}>
          {sites.map((d) => <option key={d.id} value={d.id}>{competitors.find((c) => c.id === d.competitor_id)?.name ?? d.hostname} — {d.hostname}</option>)}
        </Select>
      </Field>
      {row ? (
        <Field label="Page URL" help="Pricing, features or any page worth checking for changes.">
          <Input required autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} />
        </Field>
      ) : (
        <Field label="Page URLs" help="One per line. Pages already watched on this site are skipped.">
          <Textarea required autoFocus rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder={`${placeholder}\n${placeholder.replace(/\/pricing$/, "/features")}`} />
        </Field>
      )}
      {offSite.length > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          {offSite.length === 1 ? "That URL is" : `${offSite.length} of those URLs are`} not on {site!.hostname}; changes will still be attributed to that competitor.
        </p>
      )}
      <ErrorBox error={error ?? save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || !entered.length}>{row ? "Save" : entered.length > 1 ? `Add ${entered.length} pages` : "Add"}</Button>
        <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

interface GapRow { keyword: string; search_volume: number | null; branded: boolean; your_position: number | null; your_url: string | null; competitors: Record<string, number>; best_competitor_position: number; competitors_ranking: number }
interface Gap {
  available: boolean; reason?: string; connected_provider?: string | null; observed_on?: string;
  own_hosts?: string[]; competitor_hosts?: string[];
  totals?: { competitor_keywords: number; your_keywords: number; gaps: number; gap_volume: number; branded_excluded: number; shown: number };
  keywords?: GapRow[];
}
const GAP_COLUMNS: CsvColumn<GapRow>[] = [
  { key: "keyword", label: "Keyword", value: (r) => r.keyword }, { key: "volume", label: "Search volume", value: (r) => r.search_volume },
  { key: "branded", label: "Branded", value: (r) => r.branded }, { key: "your_position", label: "Your position", value: (r) => r.your_position },
  { key: "your_url", label: "Your URL", value: (r) => r.your_url }, { key: "competitors", label: "Competitor positions", value: (r) => JSON.stringify(r.competitors) },
];
const CHANGE_COLUMNS: CsvColumn<Change>[] = [
  { key: "observed", label: "Observed", value: (r) => r.observed_at }, { key: "competitor", label: "Competitor", value: (r) => r.competitor },
  { key: "url", label: "URL", value: (r) => r.url }, { key: "status", label: "Status", value: (r) => r.status_code },
  { key: "title", label: "Title", value: (r) => r.title }, { key: "ratio", label: "Change ratio", value: (r) => r.change_ratio },
  { key: "details", label: "Change details", value: (r) => JSON.stringify(r.diff_summary) },
];

/** What competitors rank for, with your position beside theirs. */
function KeywordGap({ pid }: { pid: string }) {
  const [filter, setFilter] = useState("");
  const [onlyGaps, setOnlyGaps] = useState(true);
  const [hideBranded, setHideBranded] = useState(true);
  const { data, isLoading } = useQuery({
    queryKey: ["keyword-gap", pid, onlyGaps, hideBranded],
    queryFn: () => api.get<Gap>(`/projects/${pid}/seo/keyword-gap?only_gaps=${onlyGaps}&exclude_branded=${hideBranded}`),
    refetchInterval: 30000,
  });
  const rows = (data?.keywords ?? []).filter((row) => !filter || row.keyword.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows);
  if (isLoading) return <Loading />;
  if (!data?.available) {
    return <EmptyState title="No ranking data yet">
      {data?.connected_provider
        ? <>Connected to <b>{data.connected_provider}</b>. Click “Sync ranked keywords” — one call per site.</>
        : <>Connect a provider under <Link className="text-primary underline" to="/integrations">Integrations → Keyword & SERP data</Link>, then sync.</>}
    </EmptyState>;
  }
  const t = data.totals!;
  const hosts = data.competitor_hosts ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={onlyGaps} onChange={(e) => setOnlyGaps(e.target.checked)} />
          Only keywords you do not rank for
        </label>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={hideBranded} onChange={(e) => setHideBranded(e.target.checked)} />
          Hide competitors' brand names
        </label>
        <span>{fmtInt(t.shown)} shown of {fmtInt(t.gaps)} gap(s) · {fmtInt(t.gap_volume)} searches/mo out of reach{t.branded_excluded > 0 && hideBranded && ` · ${fmtInt(t.branded_excluded)} branded hidden`} · checked {data.observed_on}</span>
        <SearchBox className="w-[32rem]" placeholder="Filter keywords…" value={filter} onSearch={setFilter} />
        <div className="ml-auto"><CsvExportButton filename="competitor-keyword-gap.csv" rows={rows} columns={GAP_COLUMNS} /></div>
      </div>
      <Table>
        <THead><TR>
          <TH>Keyword</TH><TH className="text-right">Volume</TH><TH className="text-right">You</TH>
          {hosts.map((h) => <TH key={h} className="text-right">{h}</TH>)}
        </TR></THead>
        <TBody>{paged.items.map((k) => (
          <TR key={k.keyword}>
            <TD className="text-sm">{k.keyword}{k.branded && <Badge variant="muted" className="ml-1">brand</Badge>}</TD>
            <TD className="text-right tabular-nums">{k.search_volume != null ? fmtInt(k.search_volume) : <span className="text-xs text-muted-foreground">—</span>}</TD>
            <TD className="text-right tabular-nums">{k.your_position
              ? <a className="text-primary hover:underline" href={k.your_url ?? undefined} target="_blank" rel="noreferrer">{k.your_position}</a>
              : <Badge variant="warning">absent</Badge>}</TD>
            {hosts.map((h) => <TD key={h} className="text-right tabular-nums text-xs">{k.competitors[h] ?? <span className="text-muted-foreground">—</span>}</TD>)}
          </TR>))}
        </TBody>
      </Table>
      <Pagination state={paged} label="keywords" />
    </div>
  );
}

function PageChanges({ pid }: { pid: string }) {
  const [filter, setFilter] = useState("");
  const { data: changes } = useQuery({ queryKey: ["competitor-changes", pid], queryFn: () => api.get<Change[]>(`/projects/${pid}/brand/competitor-changes`), refetchInterval: 20000 });
  const rows = (changes ?? []).filter((row) => !filter || `${row.competitor ?? ""} ${row.url} ${row.title ?? ""}`.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows, 10);
  if (!changes?.length) return <EmptyState title="No changes detected yet">Changes appear after at least two checks of a watched URL.</EmptyState>;
  return (
    <>
      <div className="mb-3 flex items-center gap-2"><Link to="/competitors/watched-pages" className="text-xs text-primary hover:underline">← Back to watched pages</Link><SearchBox className="ml-3 w-[32rem]" placeholder="Filter changes…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="competitor-page-changes.csv" rows={rows} columns={CHANGE_COLUMNS} /></div></div>
      {paged.items.map((c) => (
        <Card key={c.id} className="mb-3"><CardContent className="pt-5">
          <div className="flex justify-between gap-3">
            <div className="min-w-0"><span className="font-medium">{c.competitor ?? "Site"}</span> · <a className="text-primary hover:underline text-sm" href={c.url} target="_blank" rel="noreferrer">{c.url}</a></div>
            <div className="shrink-0 text-xs text-muted-foreground"><TimeAgo value={c.observed_at} /> · {fmtPct(c.change_ratio, 0)} changed</div>
          </div>
          {(c.diff_summary.prices_added?.length || c.diff_summary.prices_removed?.length) ? <div className="mt-2 text-sm"><Badge variant="warning">pricing</Badge> added: {c.diff_summary.prices_added?.join(", ") || "—"} · removed: {c.diff_summary.prices_removed?.join(", ") || "—"}</div> : null}
          <div className="grid md:grid-cols-2 gap-3 mt-2 text-xs">
            <div><div className="font-medium text-emerald-700 dark:text-emerald-300">Added ({c.diff_summary.added_count})</div><ul className="max-h-40 overflow-auto">{c.diff_summary.added?.map((l, i) => <li key={i}>+ {l}</li>)}</ul></div>
            <div><div className="font-medium text-red-700 dark:text-red-300">Removed ({c.diff_summary.removed_count})</div><ul className="max-h-40 overflow-auto">{c.diff_summary.removed?.map((l, i) => <li key={i}>− {l}</li>)}</ul></div>
          </div>
        </CardContent></Card>
      ))}
      <Pagination state={paged} label="changes" />
    </>
  );
}
