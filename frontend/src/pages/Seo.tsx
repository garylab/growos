import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { TimeSeriesChart } from "@/components/ui/timeseries-chart";
import { api, type Domain } from "@/lib/api";
import { useDomains, useProjectId } from "@/hooks/useProject";
import { useActiveTab } from "@/hooks/useTabRoute";
import { SEO_TABS } from "@/lib/nav";
import { useEnqueue } from "@/hooks/useJobs";
import { EmptyState, ErrorBox, InfoHint, Loading, Metric, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { cn, delta, fmtInt, fmtNum, fmtPct } from "@/lib/utils";
import { fmtDateTime } from "@/lib/time";
import { TimeAgo } from "@/components/ui/time";

interface CrawlRun { id: string; domain_id: string; finished_at: string | null; started_at: string; total_urls: number; html_pages: number; count_by_status: Record<string, number>; quality_scores: { overall?: { score: number; label: string }; categories?: { code: string; score: number; name: string }[] }; summary: { aplCode: string; status: string; text: string }[]; findings_count: Record<string, number>; provider_version: string | null }
interface Page { id: string; url: string; path: string; status_code: number | null; title: string | null; meta_description: string | null; h1: string | null; response_time_ms: number | null; seo_score: number | null; findings: number; robots_index: boolean | null }
interface Finding { id: string; url: string | null; code: string; category: string; severity: string; message: string; details: Record<string, unknown> }
interface Inspectable { codes: Record<string, { inspector: string; label: string }>; all_inspectors: Record<string, string> }
interface InspectIssue { url: string; detail: string; element: string | null; snippet: string | null; extra: Record<string, any> }
interface InspectResult { inspector: string; label: string; code: string | null; checked: number; pages_with_issues: number; pages_clean: number; issues: InspectIssue[]; errors: { url: string; error: string }[]; note: string }
interface Search { available: boolean; reason?: string; property?: string | null; last_sync?: string; data_range?: { start: string; end: string }; totals?: Totals; previous?: Totals; top_pages?: Row[]; top_queries?: Row[]; query_pages?: Row[] }
interface Totals { clicks: number; impressions: number; ctr: number; position: number }
interface Row { page?: string; query?: string; clicks: number; impressions: number; ctr: number; position: number }
interface Perf { id: string; url: string; strategy: string; measurement_type: string; tool_version: string | null; scores: Record<string, number | string | null>; metrics: Record<string, number | null>; audits: { id: string; title: string; score: number | null; display?: string }[]; observed_at: string }


/** Per-tab page heading and its info tooltip. Keyed by the tab id from SEO_TABS. */
const SEO_TAB_META: Record<string, { title: string; info: string }> = {
  "audit-and-pages": { title: "Audit & pages", info: "Technical audit from SiteOne Crawler, plus every crawled page with its SEO score and findings." },
  "search-performance": { title: "Search performance", info: "Clicks, impressions, CTR and average position from Google Search Console and Bing Webmaster Tools." },
  "page-performance": { title: "Page performance", info: "Core Web Vitals and Lighthouse scores measured through PageSpeed Insights." },
  "backlinks": { title: "Backlinks", info: "Referring domains and individual backlinks from the connected backlink provider." },
  "rankings": { title: "Rankings", info: "Tracked keyword positions on live search engine result pages, with movement since the last check." },
  "history": { title: "Crawl history", info: "Past crawls over time, and a side-by-side comparison of any two snapshots." },
};

export function SeoPage() {
  const pid = useProjectId();
  const { data: domains } = useDomains();
  const primaries = useMemo(() => (domains ?? []).filter((d) => d.role === "primary"), [domains]);
  const [domainId, setDomainId] = useState<string>("");
  const [searchDays, setSearchDays] = useState(28);
  const domain = primaries.find((d) => d.id === domainId) ?? primaries[0];
  const enqueue = useEnqueue();
  const tab = useActiveTab(SEO_TABS, "audit-and-pages");
  const { view } = useParams<{ view?: string }>();
  // Rankings engine lives here so its picker can sit in the page header; the query is shared (same key) with
  // RankingsTab, so react-query runs it once. Scoped to the rankings tab.
  const [rankEngine, setRankEngine] = useState("");
  const rankings = useQuery({
    queryKey: ["rankings", pid, domain?.id, rankEngine],
    queryFn: () => api.get<Rankings>(`/projects/${pid}/seo/domains/${domain!.id}/rankings${rankEngine ? `?provider_key=${rankEngine}` : ""}`),
    enabled: tab === "rankings" && !!domain,
    refetchInterval: 30000,
  });
  if (!domains) return <Loading />;
  if (!domain) return <EmptyState title="No website yet">Add your website under <Link className="text-primary underline" to="/settings">Settings</Link>.</EmptyState>;
  const rerun = () => {
    if (tab === "page-performance") {
      enqueue.mutate({ task_type: "measure_performance", params: { domain_id: domain.id } });
    } else if (tab === "search-performance") {
      enqueue.mutate({
        task_type: view === "bing" ? "sync_bing_webmaster" : "sync_search_console",
        params: view === "bing" ? { domain_id: domain.id } : { domain_id: domain.id, days: 90 },
      });
    } else if (tab === "backlinks") {
      enqueue.mutate({ task_type: "sync_backlinks", params: { domain_id: domain.id } });
    } else if (tab === "rankings") {
      enqueue.mutate({ task_type: "sync_rankings", params: {} });
    } else {
      enqueue.mutate({ task_type: "crawl_domain", params: { domain_id: domain.id } });
    }
  };
  return (
    <div>
      <PageHeader
        title={SEO_TAB_META[tab]?.title ?? "SEO Performance"}
        info={SEO_TAB_META[tab]?.info ?? "Technical audit, page and search performance for your site."}
        actions={
          <>
            {primaries.length > 1 && <Select className="w-56" value={domain.id} onChange={(e) => setDomainId(e.target.value)}>{primaries.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}</Select>}
            {tab === "search-performance" && <Select className="w-36" value={searchDays} onChange={(e) => setSearchDays(Number(e.target.value))}>{[7, 28, 90, 180].map((d) => <option key={d} value={d}>Last {d} days</option>)}</Select>}
            {tab === "rankings" && (rankings.data?.providers?.length ?? 0) > 1 && (
              <Select className="w-48" value={rankEngine} onChange={(e) => setRankEngine(e.target.value)}>
                <option value="">All search engines</option>
                {rankings.data!.providers!.map((k) => <option key={k} value={k}>{k}</option>)}
              </Select>
            )}
            <Button onClick={rerun} disabled={enqueue.isPending}>Re-run</Button>
          </>
        }
      />
      <ErrorBox error={enqueue.error} />
      {tab === "audit-and-pages" && <AuditTab pid={pid} domain={domain} />}
      {tab === "search-performance" && <SearchTab pid={pid} domain={domain} days={searchDays} />}
      {tab === "page-performance" && <PerformanceTab pid={pid} domain={domain} />}
      {tab === "backlinks" && <BacklinksTab pid={pid} domain={domain} />}
      {tab === "rankings" && <RankingsTab pid={pid} domain={domain} engine={rankEngine} />}
      {tab === "history" && <HistoryTab pid={pid} domain={domain} />}
    </div>
  );
}

function useCrawls(pid: string, domainId: string) {
  return useQuery({ queryKey: ["crawls", pid, domainId], queryFn: () => api.get<CrawlRun[]>(`/projects/${pid}/seo/crawls?domain_id=${domainId}`), refetchInterval: 15000 });
}

type PageSortKey = "seo_score" | "status_code" | "findings";
type SortDirection = "asc" | "desc";
const BORDERLESS_METRIC = "border-0 shadow-none";

const FINDING_CSV_COLUMNS: CsvColumn<Finding>[] = [
  { key: "severity", label: "Severity", value: (finding) => finding.severity },
  { key: "issue", label: "Issue", value: (finding) => finding.message },
  { key: "url", label: "URL", value: (finding) => finding.url },
  { key: "category", label: "Category", value: (finding) => finding.category },
  { key: "code", label: "Code", value: (finding) => finding.code },
  { key: "details", label: "Issue details", value: (finding) => JSON.stringify(finding.details ?? {}) },
];

function AuditTab({ pid, domain }: { pid: string; domain: Domain }) {
  const { data: runs, isLoading } = useCrawls(pid, domain.id);
  const run = runs?.find((r) => r.finished_at);
  const { view } = useParams<{ view?: string }>();
  const auditView = view === "pages" ? "pages" : "findings";
  const [findingFilter, setFindingFilter] = useState<{ severity: string; codes: string[] }>({ severity: "", codes: [] });
  const [issueTypesOpen, setIssueTypesOpen] = useState(false);
  const issueTypesRef = useRef<HTMLDetailsElement>(null);
  const [pageFilter, setPageFilter] = useState({ q: "", status: "", minScore: "", maxScore: "", issues: "" });
  const [pageSort, setPageSort] = useState<{ key: PageSortKey; direction: SortDirection }>({ key: "seo_score", direction: "asc" });
  const [issuePage, setIssuePage] = useState<Page | null>(null);
  const { data: allFindings } = useQuery({ queryKey: ["findings-all", run?.id], queryFn: () => api.get<Finding[]>(`/projects/${pid}/seo/crawls/${run!.id}/findings?limit=5000`), enabled: !!run });
  const { data: pages } = useQuery({ queryKey: ["pages", run?.id], queryFn: () => api.get<Page[]>(`/projects/${pid}/seo/crawls/${run!.id}/pages?limit=2000`), enabled: !!run });
  const { data: inspectable } = useQuery({ queryKey: ["inspectable", run?.id], queryFn: () => api.get<Inspectable>(`/projects/${pid}/seo/crawls/${run!.id}/inspectable`), enabled: !!run });
  const [inspecting, setInspecting] = useState<{ code: string; label: string } | null>(null);
  const findings = useMemo(() => (allFindings ?? []).filter((finding) =>
    (!findingFilter.severity || finding.severity === findingFilter.severity)
    && (!findingFilter.codes.length || findingFilter.codes.includes(finding.code)),
  ), [allFindings, findingFilter]);
  const findingsByUrl = useMemo(() => {
    const grouped = new Map<string, Finding[]>();
    for (const finding of allFindings ?? []) {
      if (!finding.url) continue;
      const pageFindings = grouped.get(finding.url) ?? [];
      pageFindings.push(finding);
      grouped.set(finding.url, pageFindings);
    }
    return grouped;
  }, [allFindings]);
  const filteredPages = useMemo(() => {
    const q = pageFilter.q.trim().toLowerCase();
    const minScore = pageFilter.minScore === "" ? null : Number(pageFilter.minScore);
    const maxScore = pageFilter.maxScore === "" ? null : Number(pageFilter.maxScore);
    return [...(pages ?? [])].filter((page) => {
      if (q && !page.url.toLowerCase().includes(q)) return false;
      if (pageFilter.status && String(page.status_code ?? "") !== pageFilter.status) return false;
      if (minScore != null && (page.seo_score == null || page.seo_score < minScore)) return false;
      if (maxScore != null && (page.seo_score == null || page.seo_score > maxScore)) return false;
      if (pageFilter.issues === "with" && page.findings === 0) return false;
      if (pageFilter.issues === "without" && page.findings > 0) return false;
      return true;
    }).sort((a, b) => {
      const av = a[pageSort.key], bv = b[pageSort.key];
      if (av == null && bv == null) return a.url.localeCompare(b.url);
      if (av == null) return 1;
      if (bv == null) return -1;
      const result = av - bv || a.url.localeCompare(b.url);
      return pageSort.direction === "asc" ? result : -result;
    });
  }, [pages, pageFilter, pageSort]);
  const pageCsvColumns = useMemo<CsvColumn<Page>[]>(() => [
    { key: "score", label: "Score", value: (page) => page.seo_score },
    { key: "url", label: "URL", value: (page) => page.url },
    { key: "issue_count", label: "Issue count", value: (page) => page.findings },
    { key: "title", label: "Title", value: (page) => page.title },
    { key: "meta_description", label: "Meta description", value: (page) => page.meta_description },
    { key: "h1", label: "H1", value: (page) => page.h1 },
    { key: "status", label: "Status", value: (page) => page.status_code },
    { key: "response_time", label: "Response time (ms)", value: (page) => page.response_time_ms },
    { key: "indexable", label: "Indexable", value: (page) => page.robots_index !== false },
    { key: "issue_summary", label: "Issue summary", value: (page) => (findingsByUrl.get(page.url) ?? []).map((finding) => `[${finding.severity}] ${finding.message}`).join(" | ") },
    { key: "issue_details", label: "Issue details", value: (page) => JSON.stringify((findingsByUrl.get(page.url) ?? []).map((finding) => ({ severity: finding.severity, code: finding.code, category: finding.category, message: finding.message, details: finding.details }))) },
  ], [findingsByUrl]);
  const pageStatuses = useMemo(() => [...new Set((pages ?? []).map((page) => page.status_code).filter((status): status is number => status != null))].sort((a, b) => a - b), [pages]);
  const issuePageFindings = useMemo(() => issuePage ? findingsByUrl.get(issuePage.url) ?? [] : [], [findingsByUrl, issuePage]);
  const pagedFindings = usePaged(findings);
  const pagedPages = usePaged(filteredPages);
  useEffect(() => {
    if (!issueTypesOpen) return;
    const closeOutside = (event: PointerEvent | FocusEvent) => {
      if (!issueTypesRef.current?.contains(event.target as Node)) setIssueTypesOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIssueTypesOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("focusin", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [issueTypesOpen]);
  if (isLoading) return <Loading />;
  if (!run) return <EmptyState title="No completed crawl yet">Click “Re-run” to create the first audit.</EmptyState>;
  const cats = run.quality_scores.categories ?? [];
  const byCode: Record<string, { count: number; severity: string }> = {};
  for (const f of allFindings ?? []) {
    const e = (byCode[f.code] ??= { count: 0, severity: f.severity });
    e.count += 1;
    if (f.severity === "critical") e.severity = "critical";
  }
  const codes = Object.entries(byCode).sort((a, b) => b[1].count - a[1].count);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        <Metric className={BORDERLESS_METRIC} label="Overall score" value={<>{run.quality_scores.overall?.score ?? "—"}<span className="text-sm text-muted-foreground">/10</span></>} hint={`SiteOne${run.provider_version ? ` ${run.provider_version}` : ""} weighted quality score.`} />
        {cats.map((c) => <Metric className={BORDERLESS_METRIC} key={c.code} label={c.name} value={c.score} hint="SiteOne category score." />)}
      </div>

      <nav aria-label="Audit results" className="flex gap-6 border-b">
        <div className={cn("-mb-px flex items-center gap-1.5 border-b-2 px-1 pb-2 text-sm font-medium", auditView === "findings" ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          <Link to="/seo/audit-and-pages/findings" aria-current={auditView === "findings" ? "page" : undefined}>Findings ({allFindings?.length ?? 0})</Link>
          <InfoHint>Click an issue type to filter. Types marked “explain” can be traced to the exact page and element.</InfoHint>
        </div>
        <div className={cn("-mb-px flex items-center gap-1.5 border-b-2 px-1 pb-2 text-sm font-medium", auditView === "pages" ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          <Link to="/seo/audit-and-pages/pages" aria-current={auditView === "pages" ? "page" : undefined}>Pages ({pages?.length ?? 0})</Link>
          <InfoHint>Page SEO score = 100 − 25 per critical − 10 per warning − 3 per info finding on the page.</InfoHint>
        </div>
      </nav>

      {auditView === "findings" && <div>
          <div className="flex flex-wrap gap-2 mb-3">
            <details ref={issueTypesRef} open={issueTypesOpen} onToggle={(event) => setIssueTypesOpen(event.currentTarget.open)} className="group relative">
              <summary className="flex h-9 min-w-48 cursor-pointer list-none items-center justify-between gap-3 rounded-md border bg-white py-1 pl-3 pr-1.5 text-sm shadow-sm dark:bg-slate-900 [&::-webkit-details-marker]:hidden">
                <span>{findingFilter.codes.length ? `${findingFilter.codes.length} issue types` : "All issue types"}</span>
                <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
              </summary>
              <div className="absolute left-0 z-30 mt-1 max-h-80 w-96 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-md border bg-white p-2 shadow-lg dark:bg-slate-900">
                <div className="mb-1 flex items-center justify-between border-b px-2 pb-2">
                  <span className="text-xs text-muted-foreground">Select multiple issue types</span>
                  {findingFilter.codes.length > 0 && <Button size="sm" variant="ghost" onClick={() => setFindingFilter({ ...findingFilter, codes: [] })}>Clear</Button>}
                </div>
                {codes.map(([code, info]) => {
                  const selected = findingFilter.codes.includes(code);
                  const insp = inspectable?.codes?.[code];
                  return (
                    <div key={code} className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-accent">
                      <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-sm">
                        <input type="checkbox" checked={selected} onChange={() => setFindingFilter((current) => ({ ...current, codes: selected ? current.codes.filter((item) => item !== code) : [...current.codes, code] }))} />
                        <span className={cn("min-w-0 flex-1 truncate", info.severity === "critical" && "text-red-700 dark:text-red-300")}>{code.replace(/^site_/, "").replace(/_/g, " ")}</span>
                        <b className="tabular-nums">{info.count}</b>
                      </label>
                      {insp && <button type="button" className="text-xs text-primary hover:underline" title={`Show which pages and where: ${insp.label}`} onClick={() => setInspecting({ code, label: insp.label })}>explain</button>}
                    </div>
                  );
                })}
              </div>
            </details>
            <Select className="w-40" value={findingFilter.severity} onChange={(e) => setFindingFilter({ ...findingFilter, severity: e.target.value })}><option value="">All severities</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Info</option></Select>
            <div className="ml-auto"><CsvExportButton filename={`${domain.hostname}-audit-findings.csv`} rows={findings} columns={FINDING_CSV_COLUMNS} /></div>
          </div>
          <Table containerClassName="rounded-none border-0">
            <THead><TR><TH>Severity</TH><TH>Issue</TH><TH>URL</TH><TH>Category</TH></TR></THead>
            <TBody>{pagedFindings.items.map((f) => <TR key={f.id}><TD><StatusBadge status={f.severity} /></TD><TD>{f.message}</TD><TD className="max-w-xs truncate text-xs">{f.url ? <a className="text-primary hover:underline" href={f.url} target="_blank" rel="noreferrer">{f.url.replace(domain.base_url, "/")}</a> : <span className="text-muted-foreground">whole site</span>}</TD><TD className="text-xs text-muted-foreground">{f.category}</TD></TR>)}</TBody>
          </Table>
          <Pagination state={pagedFindings} label="findings" />
      </div>}

      {auditView === "pages" && <div>
          <div className="mb-3 flex flex-wrap gap-2">
            <Select className="w-32" value={pageFilter.status} onChange={(e) => setPageFilter({ ...pageFilter, status: e.target.value })}><option value="">All statuses</option>{pageStatuses.map((status) => <option key={status} value={status}>{status}</option>)}</Select>
            <Select className="w-36" value={pageFilter.issues} onChange={(e) => setPageFilter({ ...pageFilter, issues: e.target.value })}><option value="">All issues</option><option value="with">With issues</option><option value="without">Without issues</option></Select>
            <Input type="number" min={0} max={100} className="w-28" placeholder="Min score" value={pageFilter.minScore} onChange={(e) => setPageFilter({ ...pageFilter, minScore: e.target.value })} />
            <Input type="number" min={0} max={100} className="w-28" placeholder="Max score" value={pageFilter.maxScore} onChange={(e) => setPageFilter({ ...pageFilter, maxScore: e.target.value })} />
            <SearchBox className="w-[32rem]" placeholder="Filter by URL…" value={pageFilter.q} onSearch={(v) => setPageFilter({ ...pageFilter, q: v })} />
            <div className="ml-auto"><CsvExportButton
              filename={`${domain.hostname}-audit-pages.csv`}
              rows={filteredPages}
              columns={pageCsvColumns}
              defaultSelected={["score", "url", "title", "meta_description", "h1", "status", "response_time", "issue_count", "indexable"]}
            /></div>
          </div>
          <Table containerClassName="rounded-none border-0">
            <THead><TR>
              <TH><button className="hover:text-foreground" onClick={() => setPageSort({ key: "seo_score", direction: pageSort.key === "seo_score" && pageSort.direction === "asc" ? "desc" : "asc" })}>Score {pageSort.key === "seo_score" ? (pageSort.direction === "asc" ? "↑" : "↓") : ""}</button></TH>
              <TH>URL</TH>
              <TH><button className="hover:text-foreground" onClick={() => setPageSort({ key: "findings", direction: pageSort.key === "findings" && pageSort.direction === "asc" ? "desc" : "asc" })}>Issues {pageSort.key === "findings" ? (pageSort.direction === "asc" ? "↑" : "↓") : ""}</button></TH>
              <TH>Title</TH><TH>Meta description</TH><TH>H1</TH>
              <TH><button className="hover:text-foreground" onClick={() => setPageSort({ key: "status_code", direction: pageSort.key === "status_code" && pageSort.direction === "asc" ? "desc" : "asc" })}>Status {pageSort.key === "status_code" ? (pageSort.direction === "asc" ? "↑" : "↓") : ""}</button></TH>
              <TH>Time</TH>
            </TR></THead>
            <TBody>{pagedPages.items.map((p) => <TR key={p.id}><TD className="tabular-nums font-medium">{p.seo_score ?? "—"}</TD><TD className="max-w-xs truncate text-xs"><a className="text-primary hover:underline" href={p.url} target="_blank" rel="noreferrer">{p.path}</a>{p.robots_index === false && <Badge variant="muted" className="ml-1">noindex</Badge>}</TD><TD className="text-xs">{p.findings > 0 ? <button className="font-medium text-primary hover:underline" onClick={() => setIssuePage(p)}>{p.findings}</button> : 0}</TD><TD className="max-w-xs truncate text-xs" title={p.title ?? ""}>{p.title ?? <span className="text-red-600">missing</span>}</TD><TD className="max-w-xs truncate text-xs" title={p.meta_description ?? ""}>{p.meta_description ?? <span className="text-amber-600">missing</span>}</TD><TD className="max-w-[10rem] truncate text-xs">{p.h1 ?? <span className="text-amber-600">missing</span>}</TD><TD className="text-xs">{p.status_code}</TD><TD className="text-xs tabular-nums">{p.response_time_ms} ms</TD></TR>)}</TBody>
          </Table>
          <Pagination state={pagedPages} label="pages" />
      </div>}

      <Dialog open={!!inspecting} onOpenChange={(o) => !o && setInspecting(null)}>
        {inspecting && run && <DialogContent className="max-w-4xl" title={inspecting.label} description="Re-fetches the most important pages and shows exactly where the problem is.">
          <InspectPanel pid={pid} runId={run.id} code={inspecting.code} base={domain.base_url} />
        </DialogContent>}
      </Dialog>
      <Dialog open={!!issuePage} onOpenChange={(open) => !open && setIssuePage(null)}>
        {issuePage && <DialogContent className="max-w-4xl" title={`Issues for ${issuePage.path}`} description={`${issuePageFindings.length} issue${issuePageFindings.length === 1 ? "" : "s"} found in the latest crawl.`}>
          <div className="mb-3 flex justify-end"><CsvExportButton filename={`${domain.hostname}-${issuePage.path.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "page"}-issues.csv`} rows={issuePageFindings} columns={FINDING_CSV_COLUMNS} label="Export issues" /></div>
          <div className="space-y-3">
            {issuePageFindings.map((finding) => <div key={finding.id} className="rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge status={finding.severity} /><span className="font-medium">{finding.message}</span></div>
              <div className="mt-1 text-xs text-muted-foreground">{finding.category} · {finding.code.replace(/^site_/, "").replace(/_/g, " ")}</div>
              {Object.keys(finding.details ?? {}).length > 0 && <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs dark:bg-slate-800/60">{JSON.stringify(finding.details, null, 2)}</pre>}
            </div>)}
          </div>
        </DialogContent>}
      </Dialog>
    </div>
  );
}

function InspectPanel({ pid, runId, code, base }: { pid: string; runId: string; code: string; base: string }) {
  const [limit, setLimit] = useState(25);
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ["inspect", runId, code, limit],
    queryFn: () => api.post<InspectResult>(`/projects/${pid}/seo/crawls/${runId}/inspect?code=${encodeURIComponent(code)}&limit=${limit}`),
  });
  if (isFetching) return <Loading label="Checking pages live…" />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span><b>{data.pages_with_issues}</b> of {data.checked} checked page(s) affected · {data.pages_clean} clean</span>
        <Select className="w-40 ml-auto" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>{[10, 25, 40, 60].map((n) => <option key={n} value={n}>check {n} pages</option>)}</Select>
        <Button size="sm" variant="outline" onClick={() => refetch()}>Re-check</Button>
      </div>
      <p className="text-xs text-muted-foreground">{data.note}</p>
      {data.issues.length === 0 ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-200">
          None of the checked pages has this problem right now. The crawler's count is a site-wide total and may be stale, cover pages outside this sample, or reflect a different request (for example a different Accept-Encoding).
        </div>
      ) : (
        <Table containerClassName="rounded-none border-0">
          <THead><TR><TH>Page</TH><TH>What is wrong</TH><TH>Where</TH><TH>Fix</TH></TR></THead>
          <TBody>{data.issues.map((i, n) => (
            <TR key={n}>
              <TD className="max-w-[14rem] truncate text-xs"><a className="text-primary hover:underline" href={i.url} target="_blank" rel="noreferrer">{i.url.replace(base.replace(/\/$/, ""), "") || "/"}</a></TD>
              <TD className="text-xs">{i.detail}</TD>
              <TD className="text-xs">{i.element && <code className="rounded bg-slate-100 dark:bg-slate-800 px-1">{i.element}</code>} {i.snippet && <span className="text-muted-foreground">“{i.snippet}”</span>}{i.extra?.sequence && <div className="text-muted-foreground">{i.extra.sequence}</div>}</TD>
              <TD className="text-xs text-muted-foreground">{i.extra?.fix && <code className="break-all">{i.extra.fix}</code>}{i.extra?.content_encoding && <>served as <b>{i.extra.content_encoding}</b></>}</TD>
            </TR>))}</TBody>
        </Table>
      )}
      {data.errors.length > 0 && <p className="text-xs text-muted-foreground">{data.errors.length} page(s) could not be fetched: {data.errors.slice(0, 3).map((e) => e.error).join(", ")}</p>}
    </div>
  );
}

function SearchTab({ pid, domain, days }: { pid: string; domain: Domain; days: number }) {
  const [reportFilter, setReportFilter] = useState("");
  const { view } = useParams<{ view?: string }>();
  const searchView = (["top-queries", "top-landing-pages", "query-pages", "bing"] as const).find((item) => item === view) ?? "top-queries";
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["search", pid, domain.id, days], queryFn: () => api.get<Search>(`/projects/${pid}/seo/domains/${domain.id}/search?days=${days}`) });
  const { data: bingData } = useQuery({ queryKey: ["bing", pid, domain.id, days], queryFn: () => api.get<BingSearch>(`/projects/${pid}/seo/domains/${domain.id}/search/bing?days=${days}`) });
  const bingExportRows: BingExportRow[] = [
    ...(bingData?.top_queries ?? []).map((row) => ({ ...row, type: "Query" })),
    ...(bingData?.top_pages ?? []).map((row) => ({ ...row, type: "Page" })),
  ];
  const matchReport = (value: string | undefined) => !reportFilter || (value ?? "").toLowerCase().includes(reportFilter.toLowerCase());
  const topQueries = (data?.top_queries ?? []).filter((row) => matchReport(row.query));
  const topPages = (data?.top_pages ?? []).filter((row) => matchReport(row.page));
  const queryPages = (data?.query_pages ?? []).filter((row) => matchReport(`${row.query ?? ""} ${row.page ?? ""}`));
  const filteredBingExportRows = bingExportRows.filter((row) => matchReport(row.key));
  const [prop, setProp] = useState(domain.gsc_property ?? "");
  const save = useMutation({ mutationFn: () => api.patch(`/projects/${pid}/domains/${domain.id}`, { gsc_property: prop }), onSuccess: () => qc.invalidateQueries({ queryKey: ["domains"] }) });
  if (isLoading) return <Loading />;
  if (!data?.available) {
    return (
      <div className="space-y-4">
        <EmptyState title="Search Console data not available">{data?.reason}. <Link className="text-primary underline" to="/integrations">Connect Search Console</Link>, set the property below, then click “Re-run”.</EmptyState>
        <Card><CardContent className="pt-5 flex gap-2 items-end"><div className="flex-1"><div className="text-xs text-muted-foreground mb-1">Search Console property for {domain.hostname}</div><Input value={prop} onChange={(e) => setProp(e.target.value)} placeholder="sc-domain:example.com" /></div><Button onClick={() => save.mutate()} disabled={save.isPending}>Save</Button></CardContent></Card>
        <BingPanel pid={pid} domain={domain} days={days} />
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Metric className={BORDERLESS_METRIC} label="Clicks" value={fmtInt(data.totals?.clicks)} change={delta(data.totals?.clicks, data.previous?.clicks)} source="vs previous period" />
        <Metric className={BORDERLESS_METRIC} label="Impressions" value={fmtInt(data.totals?.impressions)} change={delta(data.totals?.impressions, data.previous?.impressions)} source="vs previous period" />
        <Metric className={BORDERLESS_METRIC} label="CTR" value={fmtPct(data.totals?.ctr)} change={delta(data.totals?.ctr, data.previous?.ctr)} />
        <Metric className={BORDERLESS_METRIC} label="Avg position" value={fmtNum(data.totals?.position)} change={data.previous?.position ? -(delta(data.totals?.position, data.previous?.position) ?? 0) : null} hint="An upward trend means the position improved (a lower number)." />
      </div>
      <nav aria-label="Search performance reports" className="flex flex-wrap gap-x-6 gap-y-2 border-b">
        {[
          ["top-queries", "Top queries"],
          ["top-landing-pages", "Top landing pages"],
          ["query-pages", "Query × page (opportunity hunting)"],
          ["bing", "Bing search performance"],
        ].map(([id, label]) => (
          <Link key={id} to={`/seo/search-performance/${id}`} aria-current={searchView === id ? "page" : undefined}
            className={cn("-mb-px border-b-2 px-1 pb-2 text-sm font-medium", searchView === id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {label}
          </Link>
        ))}
      </nav>
      <div className="flex items-center gap-2">
        <SearchBox className="w-[32rem]" placeholder={searchView === "query-pages" ? "Filter queries or pages…" : "Filter current report…"} value={reportFilter} onSearch={setReportFilter} />
        <div className="ml-auto">
          {searchView === "top-queries" && <CsvExportButton filename={`${domain.hostname}-top-queries.csv`} rows={topQueries} columns={rowCsvColumns("query")} />}
          {searchView === "top-landing-pages" && <CsvExportButton filename={`${domain.hostname}-top-landing-pages.csv`} rows={topPages} columns={rowCsvColumns("page")} />}
          {searchView === "query-pages" && <CsvExportButton filename={`${domain.hostname}-query-pages.csv`} rows={queryPages} columns={rowCsvColumns("query", "page")} />}
          {searchView === "bing" && <CsvExportButton filename={`${domain.hostname}-bing-search-performance.csv`} rows={filteredBingExportRows} columns={BING_EXPORT_CSV_COLUMNS} />}
        </div>
      </div>
      {searchView === "top-queries" && <RowTable rows={topQueries} keyField="query" />}
      {searchView === "top-landing-pages" && <RowTable rows={topPages} keyField="page" />}
      {searchView === "query-pages" && <RowTable rows={queryPages} keyField="query" secondary="page" />}
      {searchView === "bing" && <BingPanel pid={pid} domain={domain} days={days} filter={reportFilter} />}
    </div>
  );
}

interface BingRow { key: string; clicks: number; impressions: number; position: number }
interface BingExportRow extends BingRow { type: string }
interface BingSearch {
  available: boolean; reason?: string; site_url: string | null; last_sync?: string | null;
  totals?: { clicks: number; impressions: number; ctr: number };
  daily?: { date: string; clicks: number; impressions: number }[];
  top_queries?: BingRow[]; top_pages?: BingRow[];
  aggregate_window?: { as_of: string | null; note: string };
}

/** Bing shown next to Google, never added to it — see the note the API returns with the aggregates. */
function BingPanel({ pid, domain, days, filter = "" }: { pid: string; domain: Domain; days: number; filter?: string }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["bing", pid, domain.id, days], queryFn: () => api.get<BingSearch>(`/projects/${pid}/seo/domains/${domain.id}/search/bing?days=${days}`) });
  const [site, setSite] = useState(domain.bing_site_url ?? "");
  const save = useMutation({ mutationFn: () => api.patch(`/projects/${pid}/domains/${domain.id}`, { bing_site_url: site }), onSuccess: () => qc.invalidateQueries({ queryKey: ["domains"] }) });
  if (!data) return null;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {data.available && <span>Site {data.site_url} · last sync <TimeAgo value={data.last_sync} /></span>}
        <InfoHint>Bing Webmaster Tools is first-party and free. Bing's index is what Microsoft Copilot answers from, so this is also the measurable half of Copilot visibility. Google and Bing are never summed.</InfoHint>
      </div>
        {!data.available ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{data.reason}. <Link className="text-primary underline" to="/integrations">Add the Bing Webmaster Tools API key</Link>, set the verified site URL below, then click “Re-run”.</p>
            <div className="flex gap-2 items-end">
              <div className="flex-1"><div className="text-xs text-muted-foreground mb-1">Bing site URL for {domain.hostname} (exactly as verified in Bing Webmaster Tools)</div><Input value={site} onChange={(e) => setSite(e.target.value)} placeholder="https://example.com" /></div>
              <Button onClick={() => save.mutate()} disabled={save.isPending}>Save</Button>
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-4">
              <Metric className={BORDERLESS_METRIC} label="Bing clicks" value={fmtInt(data.totals?.clicks)} source={`last ${days} days`} />
              <Metric className={BORDERLESS_METRIC} label="Bing impressions" value={fmtInt(data.totals?.impressions)} source={`last ${days} days`} />
              <Metric className={BORDERLESS_METRIC} label="Bing CTR" value={fmtPct(data.totals?.ctr)} />
            </div>
            <div className="grid lg:grid-cols-2 gap-4">
              <BingRows title="Top Bing queries" rows={(data.top_queries ?? []).filter((row) => !filter || row.key.toLowerCase().includes(filter.toLowerCase()))} />
              <BingRows title="Top Bing pages" rows={(data.top_pages ?? []).filter((row) => !filter || row.key.toLowerCase().includes(filter.toLowerCase()))} />
            </div>
            {data.aggregate_window && <p className="text-xs text-muted-foreground">{data.aggregate_window.note}{data.aggregate_window.as_of ? ` Stamped ${data.aggregate_window.as_of}.` : ""}</p>}
          </>
        )}
    </div>
  );
}

const BING_EXPORT_CSV_COLUMNS: CsvColumn<BingExportRow>[] = [
  { key: "type", label: "Type", value: (row) => row.type },
  { key: "item", label: "Query / page", value: (row) => row.key },
  { key: "clicks", label: "Clicks", value: (row) => row.clicks },
  { key: "impressions", label: "Impressions", value: (row) => row.impressions },
  { key: "position", label: "Position", value: (row) => row.position },
];

function BingRows({ title, rows }: { title: string; rows: BingRow[] }) {
  const paged = usePaged(rows);
  return (
    <div>
      <div className="mb-2 text-xs font-medium text-muted-foreground">{title}</div>
      <Table containerClassName="rounded-none border-0">
        <THead><TR><TH /><TH className="text-right">Clicks</TH><TH className="text-right">Impr.</TH><TH className="text-right">Pos.</TH></TR></THead>
        <TBody>{paged.items.map((r, i) => <TR key={i}><TD className="max-w-xs truncate text-xs">{r.key}</TD><TD className="text-right tabular-nums">{fmtInt(r.clicks)}</TD><TD className="text-right tabular-nums">{fmtInt(r.impressions)}</TD><TD className="text-right tabular-nums">{fmtNum(r.position)}</TD></TR>)}</TBody>
      </Table>
      <Pagination state={paged} label="rows" />
    </div>
  );
}

function rowCsvColumns(keyField: "query" | "page", secondary?: "page"): CsvColumn<Row>[] {
  return [
    { key: keyField, label: keyField === "query" ? "Query" : "Page", value: (row) => row[keyField] },
    ...(secondary ? [{ key: secondary, label: "Page", value: (row: Row) => row[secondary] }] : []),
    { key: "clicks", label: "Clicks", value: (row) => row.clicks },
    { key: "impressions", label: "Impressions", value: (row) => row.impressions },
    { key: "ctr", label: "CTR", value: (row) => row.ctr },
    { key: "position", label: "Position", value: (row) => row.position },
  ];
}

function RowTable({ rows, keyField, secondary }: { rows: Row[]; keyField: "query" | "page"; secondary?: "page" }) {
  const paged = usePaged(rows);
  return (
    <div>
        <Table containerClassName="rounded-none border-0">
          <THead><TR><TH>{keyField}</TH>{secondary && <TH>page</TH>}<TH className="text-right">Clicks</TH><TH className="text-right">Impr.</TH><TH className="text-right">CTR</TH><TH className="text-right">Pos.</TH></TR></THead>
          <TBody>{paged.items.map((r, i) => <TR key={i}><TD className="max-w-xs truncate text-xs">{r[keyField]}</TD>{secondary && <TD className="max-w-xs truncate text-xs text-muted-foreground">{r.page}</TD>}<TD className="text-right tabular-nums">{fmtInt(r.clicks)}</TD><TD className="text-right tabular-nums">{fmtInt(r.impressions)}</TD><TD className="text-right tabular-nums">{fmtPct(r.ctr)}</TD><TD className="text-right tabular-nums">{fmtNum(r.position)}</TD></TR>)}</TBody>
        </Table>
      <Pagination state={paged} label={keyField === "query" ? "queries" : "pages"} />
    </div>
  );
}

function PerformanceTab({ pid, domain }: { pid: string; domain: Domain }) {
  const { data, isLoading } = useQuery({ queryKey: ["perf", pid, domain.id], queryFn: () => api.get<Perf[]>(`/projects/${pid}/seo/domains/${domain.id}/performance`) });
  const [filter, setFilter] = useState({ q: "", type: "", strategy: "" });
  const filtered = useMemo(() => (data ?? []).filter((row) =>
    (!filter.q || row.url.toLowerCase().includes(filter.q.toLowerCase()))
    && (!filter.type || row.measurement_type === filter.type)
    && (!filter.strategy || row.strategy === filter.strategy),
  ), [data, filter]);
  const types = useMemo(() => [...new Set((data ?? []).map((row) => row.measurement_type))].sort(), [data]);
  const strategies = useMemo(() => [...new Set((data ?? []).map((row) => row.strategy))].sort(), [data]);
  const paged = usePaged(filtered);
  const columns: CsvColumn<Perf>[] = [
    { key: "url", label: "URL", value: (row) => row.url },
    { key: "type", label: "Type", value: (row) => row.measurement_type },
    { key: "strategy", label: "Strategy", value: (row) => row.strategy },
    { key: "performance", label: "Performance", value: (row) => row.scores.performance ?? row.scores.overall_category },
    { key: "seo", label: "SEO", value: (row) => row.scores.seo },
    { key: "accessibility", label: "Accessibility", value: (row) => row.scores.accessibility },
    { key: "lcp", label: "LCP (ms)", value: (row) => row.metrics.lcp_ms },
    { key: "cls", label: "CLS", value: (row) => row.metrics.cls },
    { key: "inp_tbt", label: "INP / TBT (ms)", value: (row) => row.metrics.inp_ms ?? row.metrics.tbt_ms },
    { key: "audits", label: "Failing audits", value: (row) => row.audits.map((audit) => audit.title).join(" | ") },
    { key: "measured", label: "Measured", value: (row) => row.observed_at },
  ];
  if (isLoading) return <Loading />;
  if (!data?.length) return <EmptyState title="No performance measurements yet">Click “Re-run” to create the first measurement.</EmptyState>;
  return (
    <div>
    <div className="mb-3 flex flex-wrap gap-2">
      <Select className="w-36" value={filter.type} onChange={(e) => setFilter({ ...filter, type: e.target.value })}><option value="">All types</option>{types.map((type) => <option key={type}>{type}</option>)}</Select>
      <Select className="w-44" value={filter.strategy} onChange={(e) => setFilter({ ...filter, strategy: e.target.value })}><option value="">All strategies</option>{strategies.map((strategy) => <option key={strategy}>{strategy}</option>)}</Select>
      <SearchBox className="w-[32rem]" placeholder="Filter by URL…" value={filter.q} onSearch={(v) => setFilter({ ...filter, q: v })} />
      <div className="ml-auto"><CsvExportButton filename={`${domain.hostname}-page-performance.csv`} rows={filtered} columns={columns} /></div>
    </div>
    <Table containerClassName="rounded-none border-0">
      <THead><TR><TH>URL</TH><TH>Type</TH><TH>Strategy</TH><TH>Perf</TH><TH>SEO</TH><TH>A11y</TH><TH>LCP</TH><TH>CLS</TH><TH>INP/TBT</TH><TH>Top failing audits</TH><TH>Measured</TH></TR></THead>
      <TBody>{paged.items.map((o) => <TR key={o.id}><TD className="max-w-xs truncate text-xs">{o.url}</TD><TD><Badge variant={o.measurement_type === "field" ? "info" : "muted"}>{o.measurement_type}</Badge></TD><TD className="text-xs">{o.strategy}</TD><TD className="tabular-nums font-medium">{o.scores.performance ?? o.scores.overall_category ?? "—"}</TD><TD className="tabular-nums">{o.scores.seo ?? "—"}</TD><TD className="tabular-nums">{o.scores.accessibility ?? "—"}</TD><TD className="tabular-nums text-xs">{o.metrics.lcp_ms != null ? `${Math.round(o.metrics.lcp_ms)} ms` : "—"}</TD><TD className="tabular-nums text-xs">{o.metrics.cls ?? "—"}</TD><TD className="tabular-nums text-xs">{o.metrics.inp_ms ?? o.metrics.tbt_ms ?? "—"}</TD><TD className="text-xs max-w-sm">{o.audits.slice(0, 3).map((a) => a.title).join("; ")}</TD><TD className="text-xs whitespace-nowrap"><TimeAgo value={o.observed_at} /></TD></TR>)}</TBody>
    </Table>
    <Pagination state={paged} label="measurements" />
    </div>
  );
}

interface ReferringDomainRow { referring_domain: string; backlinks: number; dofollow: number; domain_rating: number | null; first_seen: string | null; last_seen: string | null; example_url: string | null; is_new: boolean }
interface Backlinks {
  available: boolean; provider?: string; observed_on?: string; previous_observed_on?: string | null; reason?: string;
  connected_provider?: string | null;
  totals?: { referring_domains: number; backlinks: number; dofollow: number; dofollow_share: number; avg_domain_rating: number | null; gained: number; lost: number };
  history?: { date: string; referring_domains: number; backlinks: number }[];
  sample?: { backlinks: number | null; referring_domains: number | null; note: string | null } | null;
  domains?: ReferringDomainRow[];
}

function BacklinksTab({ pid, domain }: { pid: string; domain: Domain }) {
  const { data, isLoading } = useQuery({ queryKey: ["backlinks", pid, domain.id], queryFn: () => api.get<Backlinks>(`/projects/${pid}/seo/domains/${domain.id}/backlinks`), refetchInterval: 30000 });
  const { view: viewParam } = useParams<{ view?: string }>();
  const view = viewParam === "links" ? "links" : "domains";
  const [domainFilter, setDomainFilter] = useState({ q: "", status: "" });
  const filteredDomains = useMemo(() => (data?.domains ?? []).filter((row) =>
    (!domainFilter.q || row.referring_domain.toLowerCase().includes(domainFilter.q.toLowerCase()))
    && (!domainFilter.status || (domainFilter.status === "new" ? row.is_new : !row.is_new)),
  ), [data?.domains, domainFilter]);
  const paged = usePaged(filteredDomains);
  const domainColumns: CsvColumn<ReferringDomainRow>[] = [
    { key: "domain", label: "Domain", value: (row) => row.referring_domain },
    { key: "links", label: "Links", value: (row) => row.backlinks },
    { key: "dofollow", label: "Dofollow", value: (row) => row.dofollow },
    { key: "rating", label: "Domain rating", value: (row) => row.domain_rating },
    { key: "first_seen", label: "First seen", value: (row) => row.first_seen },
    { key: "last_seen", label: "Last seen", value: (row) => row.last_seen },
    { key: "example_url", label: "Example URL", value: (row) => row.example_url },
    { key: "new", label: "New", value: (row) => row.is_new },
  ];
  if (isLoading) return <Loading />;
  if (!data?.available) {
    return (
      <EmptyState title="No backlink data yet">
        {data?.connected_provider
          ? <>Connected to <b>{data.connected_provider}</b>. Click “Re-run” to fetch referring domains.</>
          : <>Connect a provider under <Link className="text-primary underline" to="/integrations">Integrations → Backlinks</Link> (DataForSEO, Ahrefs, Semrush, or any JSON endpoint), then sync.</>}
      </EmptyState>
    );
  }
  const t = data.totals!;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Metric className={BORDERLESS_METRIC} label="Referring domains" value={fmtInt(t.referring_domains)} source={`${data.provider} · ${data.observed_on}`} hint="Distinct domains linking to this site, as the connected index sees them." />
        <Metric className={BORDERLESS_METRIC} label="Backlinks" value={fmtInt(t.backlinks)} source={`${fmtPct(t.dofollow_share, 0)} dofollow`} />
        <Metric className={BORDERLESS_METRIC} label="Gained / lost" value={<span>{t.gained > 0 ? `+${t.gained}` : t.gained}<span className="text-base text-muted-foreground"> / −{t.lost}</span></span>} source={data.previous_observed_on ? `vs ${data.previous_observed_on}` : "no earlier snapshot"} hint="Domains appearing in, or missing from, the latest snapshot compared with the previous one." />
        <Metric className={BORDERLESS_METRIC} label="Authority score" value={t.avg_domain_rating != null ? fmtNum(t.avg_domain_rating, 0) : "—"} source="provider's own scale" hint="For sampled providers this is the site's profile authority score; otherwise it is the average rating of returned domains. Compare only within one provider." />
      </div>
      {data.sample && <div className="text-xs text-muted-foreground">
        Semrush profile totals are complete estimates; the explorer contains {fmtInt(data.sample.backlinks ?? 0)} selected links and {fmtInt(data.sample.referring_domains ?? 0)} selected referring domains, not the full index.
        {data.sample.note ? ` ${data.sample.note}` : ""}
      </div>}
      {(data.history?.length ?? 0) > 1 && (
        <Card>
          <CardHeader><CardTitle info="One point per sync. Indexes revise their data, so small wobbles are normal.">Referring domains</CardTitle></CardHeader>
          <CardContent>
            <TimeSeriesChart data={data.history ?? []} xKey="date" xTickFormatter={(d) => String(d).slice(5)}
              series={[{ key: "referring_domains", label: "Referring domains", color: "#2563eb" }]} />
          </CardContent>
        </Card>
      )}
      <nav aria-label="Backlink views" className="flex gap-6 border-b">
        {([["domains", "Referring domains"], ["links", "Backlinks"]] as const).map(([k, label]) => (
          <div key={k} className={cn("-mb-px flex items-center gap-1.5 border-b-2 px-1 pb-2 text-sm font-medium", view === k ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            <Link to={`/seo/backlinks/${k}`} aria-current={view === k ? "page" : undefined}>{label}</Link>
          </div>
        ))}
      </nav>
      {view === "links" && <BacklinkLinks pid={pid} domain={domain} />}
      {view === "domains" && (
      <div>
        <div className="mb-3 flex flex-wrap gap-2">
          <Select className="w-36" value={domainFilter.status} onChange={(e) => setDomainFilter({ ...domainFilter, status: e.target.value })}><option value="">All domains</option><option value="new">New</option><option value="existing">Existing</option></Select>
          <SearchBox className="w-[32rem]" placeholder="Filter by domain…" value={domainFilter.q} onSearch={(v) => setDomainFilter({ ...domainFilter, q: v })} />
          <InfoHint>Sorted by number of links. “New” marks domains that were not in the previous snapshot.</InfoHint>
          <div className="ml-auto"><CsvExportButton filename={`${domain.hostname}-referring-domains.csv`} rows={filteredDomains} columns={domainColumns} /></div>
        </div>
          <Table containerClassName="rounded-none border-0">
            <THead><TR><TH>Domain</TH><TH className="text-right">Links</TH><TH className="text-right">Dofollow</TH><TH className="text-right">Rating</TH><TH>First seen</TH><TH>Last seen</TH></TR></THead>
            <TBody>{paged.items.map((d) => (
              <TR key={d.referring_domain}>
                <TD className="text-xs">
                  <a className="text-primary hover:underline" href={d.example_url ?? `https://${d.referring_domain}`} target="_blank" rel="noreferrer">{d.referring_domain}</a>
                  {d.is_new && <Badge variant="success" className="ml-1">new</Badge>}
                </TD>
                <TD className="text-right tabular-nums">
                  <Link className="text-primary hover:underline" to={`/seo/backlinks/links?q=${encodeURIComponent(d.referring_domain)}`} title={`Show backlinks from ${d.referring_domain}`}>{fmtInt(d.backlinks)}</Link>
                </TD>
                <TD className="text-right tabular-nums">{d.dofollow ? fmtInt(d.dofollow) : <span className="text-muted-foreground">—</span>}</TD>
                <TD className="text-right tabular-nums">{d.domain_rating != null ? fmtNum(d.domain_rating, 0) : <span className="text-muted-foreground">—</span>}</TD>
                <TD className="text-xs text-muted-foreground">{d.first_seen ?? "—"}</TD>
                <TD className="text-xs text-muted-foreground">{d.last_seen ?? "—"}</TD>
              </TR>))}
            </TBody>
          </Table>
          <Pagination state={paged} label="domains" />
      </div>
      )}
    </div>
  );
}

interface LinkRow { url_from: string; url_to: string; referring_domain: string; anchor: string | null; page_title: string | null; dofollow: boolean; domain_rating: number | null; first_seen: string | null; last_seen: string | null }
interface LinkGroup { referring_domain: string; links: number; dofollow: number; nofollow: number; distinct_anchors: number; domain_rating: number | null; first_seen: string | null; last_seen: string | null; top_anchor: string | null }
interface Links { available: boolean; totals: { links: number; dofollow: number; nofollow: number; referring_domains: number; distinct_anchors: number }; groups: LinkGroup[]; links: LinkRow[]; top_anchors: { anchor: string; links: number }[] }

/** Flat list of individual backlinks: one row per link, no collapsing. The text filter lives in the URL so a
 *  "links" number on the Referring domains tab can deep-link straight to this site's backlinks. */
function BacklinkLinks({ pid, domain }: { pid: string; domain: Domain }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get("q") ?? "";
  const setQ = (v: string) => setSearchParams((prev) => { const next = new URLSearchParams(prev); if (v) next.set("q", v); else next.delete("q"); return next; }, { replace: true });
  const [follow, setFollow] = useState("");
  const filters = new URLSearchParams();
  if (q.trim()) filters.set("q", q.trim());
  if (follow) filters.set("dofollow", follow);
  const { data, isLoading } = useQuery({
    queryKey: ["backlink-links-flat", pid, domain.id, q, follow],
    queryFn: () => api.get<Links>(`/projects/${pid}/seo/domains/${domain.id}/backlinks/links?${filters}`),
  });
  const paged = usePaged(data?.links);
  if (isLoading) return <Loading />;
  if (!data?.available) {
    return <EmptyState title="No individual links stored yet">
      Referring domains are a cheaper call than the full link list. Click “Re-run” — if your provider or
      plan does not return individual links, the job logs say so and the domain view keeps working.
    </EmptyState>;
  }
  const t = data.totals;
  const linkColumns: CsvColumn<LinkRow>[] = [
    { key: "site", label: "Linking site", value: (row) => row.referring_domain },
    { key: "url_from", label: "Linking page", value: (row) => row.url_from },
    { key: "page_title", label: "Page title", value: (row) => row.page_title },
    { key: "anchor", label: "Anchor", value: (row) => row.anchor },
    { key: "url_to", label: "Target", value: (row) => row.url_to },
    { key: "dofollow", label: "Dofollow", value: (row) => row.dofollow },
    { key: "rating", label: "Domain rating", value: (row) => row.domain_rating },
    { key: "first_seen", label: "First seen", value: (row) => row.first_seen },
    { key: "last_seen", label: "Last seen", value: (row) => row.last_seen },
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select className="w-44" value={follow} onChange={(e) => setFollow(e.target.value)}>
          <option value="">Follow + nofollow</option><option value="true">Dofollow only</option><option value="false">Nofollow only</option>
        </Select>
        <SearchBox className="w-[36rem]" placeholder="Filter by domain, anchor or URL…" value={q} onSearch={setQ} />
        <span className="text-xs text-muted-foreground">{fmtInt(t.links)} links from {fmtInt(t.referring_domains)} site(s) · {fmtInt(t.dofollow)} dofollow · {fmtInt(t.distinct_anchors)} distinct anchors</span>
        <div className="ml-auto"><CsvExportButton filename={`${domain.hostname}-backlinks.csv`} rows={data.links} columns={linkColumns} /></div>
      </div>
      <Table containerClassName="rounded-none border-0">
        <THead><TR><TH>Linking page</TH><TH>Anchor</TH><TH>Target</TH><TH>Type</TH><TH className="text-right">DR</TH><TH>First seen</TH></TR></THead>
        <TBody>{paged.items.map((l, i) => (
          <TR key={`${l.url_from}|${l.anchor}|${i}`} className="align-top">
            <TD className="max-w-sm">
              <div className="text-xs font-medium">{l.referring_domain}</div>
              {l.page_title && <div className="truncate text-xs text-muted-foreground" title={l.page_title}>{l.page_title}</div>}
              <a className="block truncate text-xs text-primary hover:underline" href={l.url_from} target="_blank" rel="noreferrer" title={l.url_from}>{l.url_from}</a>
            </TD>
            <TD className="max-w-xs text-xs">
              {l.anchor ? <span title={l.anchor}>“{l.anchor}”</span> : <span className="italic text-muted-foreground">no anchor text (image or empty)</span>}
            </TD>
            <TD className="max-w-[12rem] text-xs">
              <span className="text-muted-foreground">→ </span>
              <a className="text-primary hover:underline" href={l.url_to} target="_blank" rel="noreferrer" title={l.url_to}>{l.url_to.replace(/^https?:\/\/[^/]+/, "") || "/"}</a>
            </TD>
            <TD className="text-xs">{l.dofollow ? <Badge variant="success">dofollow</Badge> : <Badge variant="muted">nofollow</Badge>}</TD>
            <TD className="text-right tabular-nums text-xs">{l.domain_rating != null ? fmtNum(l.domain_rating, 0) : "—"}</TD>
            <TD className="whitespace-nowrap text-xs text-muted-foreground">{l.first_seen ?? "—"}</TD>
          </TR>
        ))}
        </TBody>
      </Table>
      <Pagination state={paged} label="links" />
    </div>
  );
}

interface RankRow { id: string; engine: string; text: string; position: number | null; url: string | null; serp_features: string[]; change: number | null; is_new: boolean; lost: boolean }
interface Rankings {
  available: boolean; reason?: string; connected_provider?: string | null; observed_on?: string; previous_observed_on?: string | null;
  provider?: string; providers?: string[];
  totals?: { checked: number; ranking: number; absent: number; top_10: number; avg_position: number | null };
  history?: { date: string; ranking: number; avg_position: number | null }[];
  keywords?: RankRow[];
}

/** Where the target keywords actually sit, including the ones we rank nowhere for. */
function RankingsTab({ pid, domain, engine }: { pid: string; domain: Domain; engine: string }) {
  // One engine at a time: Google and Bing positions describe different result pages, so the API never pools them.
  // The engine picker lives in the page header; this reads the chosen value via the `engine` prop.
  const [filter, setFilter] = useState({ q: "", status: "" });
  const { data, isLoading } = useQuery({ queryKey: ["rankings", pid, domain.id, engine], queryFn: () => api.get<Rankings>(`/projects/${pid}/seo/domains/${domain.id}/rankings${engine ? `?provider_key=${engine}` : ""}`), refetchInterval: 30000 });
  const filtered = useMemo(() => (data?.keywords ?? []).filter((row) => {
    if (engine && row.engine !== engine) return false;
    if (filter.q && !row.text.toLowerCase().includes(filter.q.toLowerCase())) return false;
    if (filter.status === "ranking" && row.position == null) return false;
    if (filter.status === "absent" && row.position != null) return false;
    if (filter.status === "top10" && (row.position == null || row.position > 10)) return false;
    if (filter.status === "new" && !row.is_new) return false;
    if (filter.status === "lost" && !row.lost) return false;
    return true;
  }), [data?.keywords, filter, engine]);
  const paged = usePaged(filtered);
  const columns: CsvColumn<RankRow>[] = [
    { key: "keyword", label: "Keyword", value: (row) => row.text },
    { key: "engine", label: "Search engine", value: (row) => row.engine },
    { key: "position", label: "Position", value: (row) => row.position },
    { key: "change", label: "Change", value: (row) => row.change },
    { key: "new", label: "New", value: (row) => row.is_new },
    { key: "lost", label: "Lost", value: (row) => row.lost },
    { key: "url", label: "Ranking URL", value: (row) => row.url },
    { key: "features", label: "SERP features", value: (row) => row.serp_features.join(" | ") },
  ];
  if (isLoading) return <Loading />;
  if (!data?.available) {
    return <EmptyState title="No rank checks yet">
      {data?.connected_provider
        ? <>Connected to <b>{data.connected_provider}</b>. Click “Check rankings” — one SERP call per keyword, capped at 50 per run.</>
        : <>Connect a provider under <Link className="text-primary underline" to="/integrations">Integrations → Keyword & SERP data</Link>, then check rankings.</>}
    </EmptyState>;
  }
  const t = data.totals!;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Metric className={BORDERLESS_METRIC} label="Ranking" value={`${fmtInt(t.ranking)} / ${fmtInt(t.checked)}`} source={`${fmtInt(t.absent)} not found`} hint="Keywords where your site appeared anywhere in the checked SERP depth." />
        <Metric className={BORDERLESS_METRIC} label="Top 10" value={fmtInt(t.top_10)} source="first page" />
        <Metric className={BORDERLESS_METRIC} label="Avg. position" value={t.avg_position != null ? fmtNum(t.avg_position, 1) : "—"} source="ranking keywords only" hint="Averages only keywords you actually rank for, so it is not dragged down by absent ones." />
        <Metric className={BORDERLESS_METRIC} label="Checked" value={<span className="text-base">{data.observed_on}</span>} source={data.previous_observed_on ? `previous ${data.previous_observed_on}` : "first check"} />
      </div>
      {(data.history?.length ?? 0) > 1 && (
        <Card>
          <CardHeader><CardTitle info="Average position counts only keywords you rank for, so a newly-ranking keyword can push the average down while things improve.">Rankings over time</CardTitle></CardHeader>
          <CardContent>
            <TimeSeriesChart data={data.history ?? []} xKey="date" xTickFormatter={(d) => String(d).slice(5)}
              series={[{ key: "ranking", label: "Keywords ranking", color: "#2563eb", fill: "#bfdbfe", area: true }]} />
          </CardContent>
        </Card>
      )}
      <div>
        <div className="mb-3 flex flex-wrap gap-2">
          <Select className="w-36" value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}><option value="">All statuses</option><option value="ranking">Ranking</option><option value="absent">Absent</option><option value="top10">Top 10</option><option value="new">New</option><option value="lost">Lost</option></Select>
          <SearchBox className="w-[32rem]" placeholder="Filter keywords…" value={filter.q} onSearch={(v) => setFilter({ ...filter, q: v })} />
          <InfoHint>“Absent” means the SERP was checked and your site was not in it — which is a result, not a gap in the data. Each engine is measured separately, so a position on Bing is a different result page from one on Google.</InfoHint>
          <div className="ml-auto"><CsvExportButton filename={`${domain.hostname}-rankings.csv`} rows={filtered} columns={columns} /></div>
        </div>
          <Table containerClassName="rounded-none border-0">
            <THead><TR><TH>Keyword</TH><TH>Engine</TH><TH className="text-right">Position</TH><TH>Change</TH><TH>Ranking URL</TH><TH>SERP features</TH></TR></THead>
            <TBody>{paged.items.map((k) => (
              <TR key={`${k.id}-${k.engine}`}>
                <TD className="text-sm">{k.text}</TD>
                <TD className="text-xs text-muted-foreground">{k.engine}</TD>
                <TD className="text-right tabular-nums">{k.position ?? <span className="text-xs text-muted-foreground">absent</span>}</TD>
                <TD className="text-xs">
                  {k.is_new ? <Badge variant="success">new</Badge>
                   : k.lost ? <Badge variant="danger">lost</Badge>
                   : k.change ? <span className={k.change > 0 ? "text-emerald-600" : "text-red-600"}>{k.change > 0 ? `▲ ${k.change}` : `▼ ${Math.abs(k.change)}`}</span>
                   : <span className="text-muted-foreground">—</span>}
                </TD>
                <TD className="max-w-xs">{k.url ? <a className="block truncate text-xs text-primary hover:underline" href={k.url} target="_blank" rel="noreferrer" title={k.url}>{k.url.replace(/^https?:\/\/[^/]+/, "") || "/"}</a> : <span className="text-xs text-muted-foreground">—</span>}</TD>
                <TD className="text-xs text-muted-foreground">{k.serp_features.length ? k.serp_features.map((f) => f.replace(/_/g, " ")).join(", ") : "—"}</TD>
              </TR>))}
            </TBody>
          </Table>
          <Pagination state={paged} label="keywords" />
      </div>
    </div>
  );
}

function HistoryTab({ pid, domain }: { pid: string; domain: Domain }) {
  const { data: runs } = useCrawls(pid, domain.id);
  const finished = (runs ?? []).filter((r) => r.finished_at);
  const [a, setA] = useState(""); const [b, setB] = useState("");
  const [filter, setFilter] = useState({ q: "", minScore: "" });
  const ra = a || finished[0]?.id, rb = b || finished[1]?.id;
  const filteredRuns = useMemo(() => finished.filter((run) => {
    const score = run.quality_scores.overall?.score;
    return (!filter.q || `${run.finished_at ?? ""} ${run.started_at}`.toLowerCase().includes(filter.q.toLowerCase()))
      && (filter.minScore === "" || (score != null && score >= Number(filter.minScore)));
  }), [runs, filter]);
  const pagedRuns = usePaged(filteredRuns, 10);
  const columns: CsvColumn<CrawlRun>[] = [
    { key: "finished", label: "Crawl finished", value: (run) => run.finished_at },
    { key: "urls", label: "URLs", value: (run) => run.total_urls },
    { key: "html", label: "HTML pages", value: (run) => run.html_pages },
    { key: "overall", label: "Overall score", value: (run) => run.quality_scores.overall?.score },
    { key: "critical", label: "Critical findings", value: (run) => run.findings_count.critical ?? 0 },
    { key: "warnings", label: "Warnings", value: (run) => run.findings_count.warning ?? 0 },
  ];
  const { data: cmp } = useQuery({ queryKey: ["compare", ra, rb], queryFn: () => api.get<{ pages_added: string[]; pages_removed: string[]; pages_changed: { url: string; changes: Record<string, { before: unknown; after: unknown }> }[]; findings_new: { code: string; url: string }[]; findings_resolved: { code: string; url: string }[]; score_delta: { overall: number } }>(`/projects/${pid}/seo/crawls/${ra}/compare/${rb}`), enabled: !!ra && !!rb && ra !== rb });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Input type="number" min={0} max={10} className="w-32" placeholder="Min score" value={filter.minScore} onChange={(e) => setFilter({ ...filter, minScore: e.target.value })} />
        <SearchBox className="w-[32rem]" placeholder="Filter by crawl date…" value={filter.q} onSearch={(v) => setFilter({ ...filter, q: v })} />
        <div className="ml-auto"><CsvExportButton filename={`${domain.hostname}-crawl-history.csv`} rows={filteredRuns} columns={columns} /></div>
      </div>
      <Table containerClassName="rounded-none border-0">
        <THead><TR><TH>Crawl</TH><TH>URLs</TH><TH>HTML</TH><TH>Overall</TH><TH>Critical</TH><TH>Warnings</TH></TR></THead>
        <TBody>{pagedRuns.items.map((r) => <TR key={r.id}><TD className="text-xs"><TimeAgo value={r.finished_at} /></TD><TD>{r.total_urls}</TD><TD>{r.html_pages}</TD><TD>{r.quality_scores.overall?.score}</TD><TD>{r.findings_count.critical ?? 0}</TD><TD>{r.findings_count.warning ?? 0}</TD></TR>)}</TBody>
      </Table>
      <Pagination state={pagedRuns} label="crawls" />
      {finished.length >= 2 && (
        <Card>
          <CardHeader><CardTitle info="Change detection between snapshots: pages added/removed, title/meta/H1/status changes, new and resolved findings.">Compare two crawls</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2 items-center text-sm">
              <Select className="w-64" value={ra} onChange={(e) => setA(e.target.value)}>{finished.map((r) => <option key={r.id} value={r.id}>{fmtDateTime(r.finished_at)}</option>)}</Select>
              <span className="text-muted-foreground">vs baseline</span>
              <Select className="w-64" value={rb} onChange={(e) => setB(e.target.value)}>{finished.map((r) => <option key={r.id} value={r.id}>{fmtDateTime(r.finished_at)}</option>)}</Select>
            </div>
            {cmp && (
              <div className="grid md:grid-cols-2 gap-4 text-sm">
                <div><div className="font-medium">Score delta: {cmp.score_delta.overall > 0 ? "+" : ""}{cmp.score_delta.overall.toFixed(1)}</div>
                  <div className="mt-2 font-medium">Pages added ({cmp.pages_added.length})</div><ul className="text-xs text-muted-foreground max-h-40 overflow-auto">{cmp.pages_added.map((u) => <li key={u}>{u}</li>)}</ul>
                  <div className="mt-2 font-medium">Pages removed ({cmp.pages_removed.length})</div><ul className="text-xs text-muted-foreground max-h-40 overflow-auto">{cmp.pages_removed.map((u) => <li key={u}>{u}</li>)}</ul></div>
                <div><div className="font-medium">New findings ({cmp.findings_new.length})</div><ul className="text-xs text-red-700 dark:text-red-300 max-h-40 overflow-auto">{cmp.findings_new.map((f, i) => <li key={i}>{f.code} {f.url}</li>)}</ul>
                  <div className="mt-2 font-medium">Resolved findings ({cmp.findings_resolved.length})</div><ul className="text-xs text-emerald-700 dark:text-emerald-300 max-h-40 overflow-auto">{cmp.findings_resolved.map((f, i) => <li key={i}>{f.code} {f.url}</li>)}</ul></div>
                <div className="md:col-span-2"><div className="font-medium">Changed pages ({cmp.pages_changed.length})</div>
                  <ul className="text-xs max-h-60 overflow-auto space-y-1">{cmp.pages_changed.map((p) => <li key={p.url}><span className="text-muted-foreground">{p.url}</span> {Object.entries(p.changes).map(([k, v]) => <span key={k} className="ml-2">{k}: <s>{String(v.before ?? "∅")}</s> → {String(v.after ?? "∅")}</span>)}</li>)}</ul></div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
