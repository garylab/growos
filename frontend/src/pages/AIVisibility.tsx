import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { api, type Competitor, type Job, type Prompt } from "@/lib/api";
import { useCompetitors, useDomains, useProjectId } from "@/hooks/useProject";
import { useActiveTab } from "@/hooks/useTabRoute";
import { GEO_TABS } from "@/lib/nav";
import { EmptyState, ErrorBox, InfoHint, Loading, Metric, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { delta, fmtInt, fmtPct } from "@/lib/utils";
import { fmtRelative } from "@/lib/time";
import { TimeAgo } from "@/components/ui/time";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

interface PromptRow { prompt_id: string; prompt: string; intent: string | null; topic: string | null; provider: string; samples: number; grounded_samples: number; answer_shown: number; brand_mention_rate: number; brand_mention_rate_when_shown: number | null; brand_avg_position: number | null; own_domain_cited_rate: number; competitors: Record<string, { rate: number; avg_position: number | null }>; top_cited_domains: [string, number][]; models: string[] }
interface Summary { run_id: string | null; observed_at: string | null; samples: number; prompts?: number; providers: string[]; brand_mention_rate: number | null; answer_shown_rate?: number | null; own_domain_cited_rate: number | null; competitors: Record<string, number> }
interface Visibility { summary: Summary; previous: Summary | null; by_prompt: PromptRow[]; methodology: Record<string, string> }
interface Observation { id: string; prompt_id: string; run_id: string; sample_index: number; provider_key: string; model: string; model_version: string | null; grounded: boolean; grounding_type: string; answer_text: string | null; citations: { url: string; domain: string; title: string | null }[]; brand_mentioned: boolean; brand_position: number | null; sentiment: string | null; latency_ms: number | null; error: string | null; observed_at: string; request_config: Record<string, unknown>; mentions: { entity_type: string; entity_name: string; position: number | null; list_rank: number | null; sentiment: string; context_snippet: string | null }[] }
interface AITraffic {
  domains: { hostname: string; available: boolean; reason?: string; days: number; sessions: number; previous_sessions: number; conversions: number;
             total_sessions: number; share_of_sessions: number; by_assistant: { assistant: string; sessions: number; conversions: number; revenue: number; sources: string[] }[];
             daily: { date: string; sessions: number }[]; landing_pages: { landing_page: string; sessions: number; conversions: number }[];
             definitions: Record<string, string> }[];
  visibility: Summary | null;
  methodology: Record<string, string>;
}
type AssistantTraffic = AITraffic["domains"][number]["by_assistant"][number];
type AILandingPage = AITraffic["domains"][number]["landing_pages"][number];
const ASSISTANT_TRAFFIC_COLUMNS: CsvColumn<AssistantTraffic>[] = [
  { key: "assistant", label: "Assistant", value: (r) => r.assistant }, { key: "visits", label: "Visits", value: (r) => r.sessions },
  { key: "conversions", label: "Conversions", value: (r) => r.conversions }, { key: "revenue", label: "Revenue", value: (r) => r.revenue },
  { key: "referrers", label: "Referrers", value: (r) => r.sources.join(", ") },
];
const AI_LANDING_COLUMNS: CsvColumn<AILandingPage>[] = [
  { key: "page", label: "Landing page", value: (r) => r.landing_page }, { key: "visits", label: "Visits", value: (r) => r.sessions },
  { key: "conversions", label: "Conversions", value: (r) => r.conversions },
];
interface CrawlerVerdict { token: string; operator: string; purpose: string; what: string; allowed: boolean; matched_group: string; matched_rule: string | null; explicit: boolean }
interface CrawlerAccess {
  available: boolean; reason?: string; checked?: boolean; status?: string; detail?: string; url?: string; status_code?: number;
  checked_at?: string | null; crawlers?: CrawlerVerdict[];
  blocked_answers?: string[]; blocked_search?: string[]; blocked_training?: string[];
  partially_blocked?: Record<string, string[]>; allowed_count?: number;
}
interface Citations { run_id: string | null; total_answers: number; domains: { domain: string; citations: number; answers: number; providers: string[]; sample_urls: string[] }[] }
type CitationDomain = Citations["domains"][number];
const PROMPT_ROW_COLUMNS: CsvColumn<PromptRow>[] = [
  { key: "prompt", label: "Prompt", value: (r) => r.prompt }, { key: "provider", label: "Provider", value: (r) => r.provider },
  { key: "intent", label: "Intent", value: (r) => r.intent }, { key: "topic", label: "Topic", value: (r) => r.topic },
  { key: "samples", label: "Samples", value: (r) => r.samples }, { key: "shown", label: "Answers shown", value: (r) => r.answer_shown },
  { key: "brand", label: "Brand mention rate", value: (r) => r.brand_mention_rate }, { key: "position", label: "Brand average position", value: (r) => r.brand_avg_position },
  { key: "cited", label: "Own domain cited rate", value: (r) => r.own_domain_cited_rate }, { key: "competitors", label: "Competitors", value: (r) => JSON.stringify(r.competitors) },
];
const ANSWER_COLUMNS: CsvColumn<Observation>[] = [
  { key: "observed", label: "Observed", value: (r) => r.observed_at }, { key: "provider", label: "Provider", value: (r) => r.provider_key },
  { key: "model", label: "Model", value: (r) => r.model_version ?? r.model }, { key: "prompt", label: "Prompt ID", value: (r) => r.prompt_id },
  { key: "grounded", label: "Grounded", value: (r) => r.grounded }, { key: "brand", label: "Brand mentioned", value: (r) => r.brand_mentioned },
  { key: "position", label: "Brand position", value: (r) => r.brand_position }, { key: "answer", label: "Answer", value: (r) => r.answer_text },
  { key: "mentions", label: "Mentions", value: (r) => JSON.stringify(r.mentions) }, { key: "citations", label: "Citations", value: (r) => JSON.stringify(r.citations) },
  { key: "error", label: "Error", value: (r) => r.error },
];
const SOURCE_COLUMNS: CsvColumn<CitationDomain>[] = [
  { key: "domain", label: "Domain", value: (r) => r.domain }, { key: "citations", label: "Citations", value: (r) => r.citations },
  { key: "answers", label: "Answers", value: (r) => r.answers }, { key: "providers", label: "Providers", value: (r) => r.providers.join(", ") },
  { key: "urls", label: "Example URLs", value: (r) => r.sample_urls.join("\n") },
];
const PROMPT_COLUMNS: CsvColumn<Prompt>[] = [
  { key: "prompt", label: "Prompt", value: (r) => r.text }, { key: "intent", label: "Intent", value: (r) => r.intent },
  { key: "topic", label: "Topic", value: (r) => r.topic }, { key: "language", label: "Language", value: (r) => r.language },
  { key: "country", label: "Country", value: (r) => r.country }, { key: "samples", label: "Samples per run", value: (r) => r.samples_per_run },
  { key: "active", label: "Active", value: (r) => r.is_active },
];
const RUN_COLUMNS: CsvColumn<Summary>[] = [
  { key: "run", label: "Run ID", value: (r) => r.run_id }, { key: "observed", label: "Observed", value: (r) => r.observed_at },
  { key: "samples", label: "Samples", value: (r) => r.samples }, { key: "prompts", label: "Prompts", value: (r) => r.prompts },
  { key: "providers", label: "Providers", value: (r) => r.providers.join(", ") }, { key: "brand", label: "Brand mention rate", value: (r) => r.brand_mention_rate },
  { key: "cited", label: "Own domain cited rate", value: (r) => r.own_domain_cited_rate }, { key: "competitors", label: "Competitors", value: (r) => JSON.stringify(r.competitors) },
];


export function AIVisibilityPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const { data: prompts, isLoading } = useQuery({ queryKey: ["prompts", pid], queryFn: () => api.get<Prompt[]>(`/projects/${pid}/geo/prompts`) });
  const run = useMutation({ mutationFn: (body: { samples?: number }) => api.post<Job>(`/projects/${pid}/geo/run`, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }) });
  const [adding, setAdding] = useState(false);
  const [trafficDays, setTrafficDays] = useState(90);
  const tab = useActiveTab(GEO_TABS, "visibility");
  if (isLoading) return <Loading />;
  return (
    <div>
      <PageHeader
        title="GEO AI Visibility"
        info="How often AI assistants mention your brand and competitors for the prompts your customers ask. Measured by repeated API sampling (OpenAI, Gemini, Perplexity…), not by scraping consumer apps."
        actions={<>
          {tab === "ai-traffic" && <Select className="w-36" value={trafficDays} onChange={(e) => setTrafficDays(Number(e.target.value))}>{[28, 90, 180, 365].map((n) => <option key={n} value={n}>Last {n} days</option>)}</Select>}
          {tab !== "ai-traffic" && <Button variant="outline" onClick={() => setAdding(true)}>Add prompts</Button>}
          <Button onClick={() => run.mutate({})} disabled={run.isPending || !prompts?.length}>Re-run</Button>
        </>}
      />
      <ErrorBox error={run.error} />
      {run.data && <div className="mb-4 text-sm text-muted-foreground">Job queued ({run.data.id.slice(0, 8)})…</div>}
      {tab === "visibility" && <div className="space-y-6"><CrawlerAccessCard pid={pid} /><VisibilityTab pid={pid} /></div>}
      {tab === "ai-traffic" && <AITrafficTab pid={pid} days={trafficDays} />}
      {tab === "answers" && <AnswersTab pid={pid} prompts={prompts ?? []} />}
      {tab === "influencing-sources" && <SourcesTab pid={pid} />}
      {tab === "prompts" && <PromptsTab pid={pid} prompts={prompts ?? []} onAdd={() => setAdding(true)} />}
      {tab === "runs" && <RunsTab pid={pid} />}
      <Dialog open={adding} onOpenChange={setAdding}><DialogContent title="Add prompts" description="One prompt per line. Write them the way a potential customer would ask an AI assistant."><AddPrompts pid={pid} onDone={() => setAdding(false)} /></DialogContent></Dialog>
    </div>
  );
}

function VisibilityTab({ pid }: { pid: string }) {
  const [filter, setFilter] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["visibility", pid], queryFn: () => api.get<Visibility>(`/projects/${pid}/geo/visibility`), refetchInterval: 15000 });
  // Every hook runs before the early returns below, or the hook count changes once data arrives.
  const promptRows = useMemo(() => (data?.by_prompt ?? []).filter((row) => !filter || `${row.prompt} ${row.provider} ${row.intent ?? ""} ${row.topic ?? ""}`.toLowerCase().includes(filter.toLowerCase())), [data?.by_prompt, filter]);
  const pagedPrompts = usePaged(promptRows);
  if (isLoading) return <Loading />;
  if (!data?.summary.run_id) return <EmptyState title="No sampling run yet">Add prompts, configure an AI provider under <Link className="text-primary underline" to="/integrations">Integrations</Link>, then run them.</EmptyState>;
  const s = data.summary, p = data.previous;
  const comps = Object.entries(s.competitors);
  return (
    <div className="space-y-6">
      <div className="flex justify-end -mb-3 text-xs text-muted-foreground items-center gap-1">
        Methodology
        <InfoHint width="w-80" className="align-middle">{Object.entries(data.methodology).map(([k, v]) => <p key={k} className="mt-1 first:mt-0"><span className="font-medium">{k.replace(/_/g, " ")}:</span> {v}</p>)}</InfoHint>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Metric label="Brand mention rate" value={fmtPct(s.brand_mention_rate, 0)} change={delta(s.brand_mention_rate, p?.brand_mention_rate)} source={`${s.samples} samples, ${s.prompts} prompts`} hint={`Share of sampled answers mentioning the brand or an alias.${s.answer_shown_rate != null && s.answer_shown_rate < 1 ? ` An answer was shown in ${fmtPct(s.answer_shown_rate, 0)} of samples — scraped surfaces such as Google AI Overview do not appear for every query, and samples with no answer count as "not mentioned".` : ""}`} />
        <Metric label="Own domain cited" value={fmtPct(s.own_domain_cited_rate, 0)} change={delta(s.own_domain_cited_rate, p?.own_domain_cited_rate)} source="grounded answers" />
        <Metric label="Providers" value={s.providers.length} source={s.providers.join(", ")} />
        <Metric label="Run" value={<span className="text-base"><TimeAgo value={s.observed_at} /></span>} source={p?.observed_at ? `previous: ${fmtRelative(p.observed_at)}` : "first run"} />
      </div>
      {comps.length > 0 && (
        <Card><CardHeader><CardTitle info="Mention rate across all prompts and providers in the latest run, compared with the previous run.">Share of voice: competitors in AI answers</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {[["__brand", s.brand_mention_rate ?? 0] as [string, number], ...comps].map(([n, r]) => { const before = n === "__brand" ? p?.brand_mention_rate : p?.competitors[n]; return (
              <div key={n} className="flex items-center gap-3 text-sm"><span className={`w-40 truncate ${n === "__brand" ? "font-semibold" : ""}`}>{n === "__brand" ? "Your brand" : n}</span><div className="flex-1 h-3 rounded bg-slate-100 dark:bg-slate-800"><div className={`h-3 rounded ${n === "__brand" ? "bg-primary" : "bg-amber-400"}`} style={{ width: `${r * 100}%` }} /></div><span className="w-12 text-right tabular-nums">{fmtPct(r, 0)}</span><span className="w-20 text-xs text-muted-foreground">{before != null ? `was ${fmtPct(before, 0)}` : ""}</span></div>); })}
          </CardContent></Card>
      )}
      <Card>
        <CardHeader><CardTitle info="Rates are the share of repeated samples. “Pos.” is the average order of first appearance among tracked entities (1 = mentioned first). “Shown” is how often the surface produced an answer at all — Google runs no AI Overview for many queries, and a brand rate of 0% across answers that never appeared means something different from being left out of one.">By prompt and provider</CardTitle></CardHeader>
        <CardContent>
          <div className="mb-3 flex gap-2"><Input className="max-w-sm" placeholder="Filter prompts or providers…" value={filter} onChange={(e) => setFilter(e.target.value)} /><div className="ml-auto"><CsvExportButton filename="ai-visibility-by-prompt.csv" rows={promptRows} columns={PROMPT_ROW_COLUMNS} /></div></div>
          <Table>
            <THead><TR><TH>Prompt</TH><TH>Provider</TH><TH>Samples</TH><TH>Shown</TH><TH>Grounded</TH><TH>Brand</TH><TH>Pos.</TH><TH>Own site cited</TH><TH>Competitors</TH><TH>Top cited domains</TH></TR></THead>
            <TBody>{pagedPrompts.items.map((r) => <TR key={r.prompt_id + r.provider}><TD className="max-w-xs text-xs">{r.prompt}<div className="text-muted-foreground">{r.intent}{r.topic ? ` · ${r.topic}` : ""}</div></TD><TD className="text-xs">{r.provider}<div className="text-muted-foreground">{r.models.join(", ")}</div></TD><TD>{r.samples}</TD><TD className={r.answer_shown < r.samples ? "text-amber-700 dark:text-amber-300" : undefined}>{r.answer_shown}/{r.samples}</TD><TD>{r.grounded_samples}/{r.samples}</TD><TD><Badge variant={r.brand_mention_rate >= 0.5 ? "success" : r.brand_mention_rate > 0 ? "warning" : "danger"}>{fmtPct(r.brand_mention_rate, 0)}</Badge>{r.answer_shown < r.samples && r.brand_mention_rate_when_shown != null && <div className="text-xs text-muted-foreground">{fmtPct(r.brand_mention_rate_when_shown, 0)} of answers shown</div>}</TD><TD className="tabular-nums">{r.brand_avg_position ?? "—"}</TD><TD>{fmtPct(r.own_domain_cited_rate, 0)}</TD><TD className="text-xs">{Object.entries(r.competitors).sort((a, b) => b[1].rate - a[1].rate).map(([n, v]) => <div key={n}>{n} <span className="text-muted-foreground">{fmtPct(v.rate, 0)}{v.avg_position ? ` · pos ${v.avg_position}` : ""}</span></div>)}</TD><TD className="text-xs text-muted-foreground">{r.top_cited_domains.slice(0, 4).map(([d, n]) => `${d} (${n})`).join(", ")}</TD></TR>)}</TBody>
          </Table>
          <Pagination state={pagedPrompts} label="rows" />
        </CardContent>
      </Card>
    </div>
  );
}

function AnswersTab({ pid, prompts }: { pid: string; prompts: Prompt[] }) {
  const [f, setF] = useState({ prompt_id: "", provider_key: "" });
  const qs = new URLSearchParams({ limit: "100" }); if (f.prompt_id) qs.set("prompt_id", f.prompt_id); if (f.provider_key) qs.set("provider_key", f.provider_key);
  const { data, isLoading } = useQuery({ queryKey: ["observations", pid, f], queryFn: () => api.get<Observation[]>(`/projects/${pid}/geo/observations?${qs}`) });
  const [open, setOpen] = useState<Observation | null>(null);
  const paged = usePaged(data);
  return (
    <div className="space-y-3">
      <div className="flex gap-2"><Select className="w-96" value={f.prompt_id} onChange={(e) => setF({ ...f, prompt_id: e.target.value })}><option value="">All prompts</option>{prompts.map((p) => <option key={p.id} value={p.id}>{p.text.slice(0, 80)}</option>)}</Select><Input className="w-48" placeholder="provider (openai, gemini…)" value={f.provider_key} onChange={(e) => setF({ ...f, provider_key: e.target.value })} /><div className="ml-auto"><CsvExportButton filename="ai-answers.csv" rows={data ?? []} columns={ANSWER_COLUMNS} /></div></div>
      {isLoading ? <Loading /> : !data?.length ? <EmptyState title="No answers collected yet" /> : (
        <Table>
          <THead><TR><TH>When</TH><TH>Provider / model</TH><TH>Prompt</TH><TH>Grounded</TH><TH>Brand</TH><TH>Mentions</TH><TH>Citations</TH><TH /></TR></THead>
          <TBody>{paged.items.map((o) => <TR key={o.id}><TD className="text-xs whitespace-nowrap"><TimeAgo value={o.observed_at} /></TD><TD className="text-xs">{o.provider_key}<div className="text-muted-foreground">{o.model_version ?? o.model}</div></TD><TD className="text-xs max-w-xs truncate">{prompts.find((p) => p.id === o.prompt_id)?.text}</TD><TD><Badge variant={o.grounded ? "info" : "muted"}>{o.grounding_type}</Badge></TD><TD>{o.error ? <Badge variant="danger">error</Badge> : <Badge variant={o.brand_mentioned ? "success" : "danger"}>{o.brand_mentioned ? `yes${o.brand_position ? ` · #${o.brand_position}` : ""}` : "no"}</Badge>}</TD><TD className="text-xs">{o.mentions.map((m) => <span key={m.entity_name} className={`mr-1 ${m.entity_type === "brand" ? "font-medium" : ""}`}>{m.entity_name}{m.position ? `#${m.position}` : ""}</span>)}</TD><TD className="text-xs">{o.citations.length}</TD><TD><Button size="sm" variant="ghost" onClick={() => setOpen(o)}>View</Button></TD></TR>)}</TBody>
        </Table>
      )}
      <Pagination state={paged} label="answers" />
      <Dialog open={!!open} onOpenChange={(v) => !v && setOpen(null)}>{open && <DialogContent title={`${open.provider_key} · ${open.model_version ?? open.model}`} description={`${fmtRelative(open.observed_at)} · sample ${open.sample_index + 1} · ${open.grounding_type} · ${open.latency_ms} ms · locale ${JSON.stringify(open.request_config)}`}>
        {open.error ? <ErrorBox error={open.error} /> : <>
          <div className="text-sm whitespace-pre-wrap rounded bg-slate-50 dark:bg-slate-800/60 p-3 max-h-80 overflow-auto">{open.answer_text}</div>
          <div className="mt-3 text-sm"><span className="font-medium">Mentions:</span> {open.mentions.length ? open.mentions.map((m) => <div key={m.entity_name} className="text-xs mt-1"><Badge variant={m.entity_type === "brand" ? "default" : "warning"}>{m.entity_name}</Badge> position {m.position}{m.list_rank ? `, list rank ${m.list_rank}` : ""}, sentiment {m.sentiment} — <span className="text-muted-foreground">{m.context_snippet}</span></div>) : <span className="text-muted-foreground">none</span>}</div>
          <div className="mt-3 text-sm"><span className="font-medium">Citations:</span> {open.citations.length ? <ul className="text-xs list-disc pl-4">{open.citations.map((c) => <li key={c.url}><a className="text-primary hover:underline" href={c.url} target="_blank" rel="noreferrer">{c.title || c.url}</a> <span className="text-muted-foreground">({c.domain})</span></li>)}</ul> : <span className="text-muted-foreground">none (non-grounded or no citations returned)</span>}</div>
        </>}
      </DialogContent>}</Dialog>
    </div>
  );
}

/** Whether robots.txt lets the retrieval crawlers in. Shown above the visibility numbers because it is the first
 *  explanation for a brand that is absent from every answer: a page that cannot be fetched cannot be cited. */
function CrawlerAccessCard({ pid }: { pid: string }) {
  const { data: domains } = useDomains();
  const domain = (domains ?? []).find((d) => d.role === "primary");
  const { data } = useQuery({
    queryKey: ["ai-crawlers", pid, domain?.id],
    queryFn: () => api.get<CrawlerAccess>(`/projects/${pid}/seo/domains/${domain!.id}/ai-crawlers`),
    enabled: !!domain,
  });
  if (!data) return null;
  if (!data.available) return null;

  // An unreadable robots.txt is a different, worse story than a blocked bot, so it gets its own message rather
  // than being folded into a count of zero blocked crawlers.
  if (!data.checked) {
    return (
      <Card className="border-rose-300 dark:border-rose-900">
        <CardHeader><CardTitle>AI crawlers cannot read your robots.txt</CardTitle>
          <CardDescription>{data.detail}</CardDescription></CardHeader>
        <CardContent className="text-xs text-muted-foreground">
          {data.url} returned HTTP {data.status_code ?? "?"} · checked <TimeAgo value={data.checked_at} />
        </CardContent>
      </Card>
    );
  }

  const blocking = [...(data.blocked_answers ?? []), ...(data.blocked_search ?? [])];
  const partial = Object.entries(data.partially_blocked ?? {});
  const byToken = new Map((data.crawlers ?? []).map((c) => [c.token, c]));
  const ok = blocking.length === 0 && partial.length === 0;
  return (
    <Card className={ok ? undefined : "border-rose-300 dark:border-rose-900"}>
      <CardHeader>
        <CardTitle info="Read from your live robots.txt during the last site audit. Blocking a training crawler costs no visibility and is listed separately; blocking a retrieval crawler removes you from that assistant's answers entirely.">
          AI crawler access
        </CardTitle>
        <CardDescription>
          {ok
            ? `All ${data.allowed_count} retrieval crawlers we check may fetch the site.`
            : `${blocking.length} crawler(s) that AI assistants answer from are blocked by robots.txt.`}
          {" "}Checked <TimeAgo value={data.checked_at} />.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {blocking.length > 0 && (
          <Table>
            <THead><TR><TH>Crawler</TH><TH>Operator</TH><TH>What this costs</TH><TH>Rule</TH></TR></THead>
            <TBody>{blocking.map((t) => { const c = byToken.get(t); return (
              <TR key={t}>
                <TD className="text-xs font-medium">{t}</TD>
                <TD className="text-xs text-muted-foreground">{c?.operator}</TD>
                <TD className="text-xs">{c?.what}</TD>
                <TD className="text-xs font-mono text-muted-foreground">{c?.matched_rule ?? "—"}{c?.explicit === false ? " (via *)" : ""}</TD>
              </TR>); })}</TBody>
          </Table>
        )}
        {partial.map(([token, paths]) => (
          <p key={token} className="text-xs text-muted-foreground">
            <span className="font-medium">{token}</span> may fetch the home page but is blocked from {paths.length} crawled path(s): {paths.slice(0, 5).join(", ")}{paths.length > 5 ? "…" : ""}
          </p>
        ))}
        {(data.blocked_training ?? []).length > 0 && (
          <p className="text-xs text-muted-foreground">
            Opted out of model training: {(data.blocked_training ?? []).join(", ")}. That is a policy choice and does not affect whether assistants can cite you.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function AITrafficTab({ pid, days }: { pid: string; days: number }) {
  const [filter, setFilter] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["ai-traffic", pid, days], queryFn: () => api.get<AITraffic>(`/projects/${pid}/geo/ai-traffic?days=${days}`) });
  if (isLoading) return <Loading />;
  const d = data?.domains?.[0];
  if (!d?.available) return <EmptyState title="No analytics data yet">{d?.reason ?? "Connect Google Analytics 4 under Integrations, then sync it."}</EmptyState>;
  const vis = data?.visibility;
  const assistants = d.by_assistant.filter((row) => !filter || `${row.assistant} ${row.sources.join(" ")}`.toLowerCase().includes(filter.toLowerCase()));
  const landingPages = d.landing_pages.filter((row) => !filter || row.landing_page.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-end gap-3 text-xs text-muted-foreground">
        How this is measured
        <InfoHint width="w-80" className="align-middle">
          {Object.entries(data?.methodology ?? {}).map(([k, v]) => <p key={k} className="mt-1 first:mt-0"><span className="font-medium">{k}:</span> {v}</p>)}
          {d.definitions?.caveat && <p className="mt-1">{d.definitions.caveat}</p>}
        </InfoHint>
        <Input className="w-56" placeholder="Filter traffic rows…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Metric label="Visits from AI assistants" value={fmtInt(d.sessions)} change={delta(d.sessions, d.previous_sessions)} source={`vs previous ${d.days} days`} hint="Sessions whose referrer is a known AI assistant." />
        <Metric label="Share of all visits" value={fmtPct(d.share_of_sessions)} source={`${fmtInt(d.sessions)} of ${fmtInt(d.total_sessions)} sessions`} />
        <Metric label="Conversions from AI" value={fmtInt(d.conversions)} source={d.conversions === 0 ? "no key events recorded in GA4" : "key events"} />
        <Metric label="Brand mention rate" value={vis?.brand_mention_rate != null ? fmtPct(vis.brand_mention_rate, 0) : "—"} source={vis ? `${vis.samples} sampled answers` : "no run yet"} hint="From the latest AI visibility run — the cause behind these visits." />
      </div>
      {vis && d.sessions > 0 && vis.brand_mention_rate === 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/30 px-3 py-2 text-sm">
          AI assistants sent <b>{fmtInt(d.sessions)}</b> visits, yet your tracked prompts show a <b>0%</b> mention rate — you are probably measuring the wrong prompts.
        </div>
      )}
      {d.daily.length > 1 && (
        <Card><CardHeader><CardTitle info="Source: your analytics, session source/medium.">AI assistant visits over time</CardTitle></CardHeader>
          <CardContent><ResponsiveContainer width="100%" height={180}>
            <AreaChart data={d.daily}><CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" /><XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => String(v).slice(5)} /><YAxis tick={{ fontSize: 11 }} /><Tooltip />
              <Area type="monotone" dataKey="sessions" stroke="#7c3aed" fill="#ddd6fe" name="Visits" /></AreaChart>
          </ResponsiveContainer></CardContent></Card>
      )}
      <div className="grid lg:grid-cols-2 gap-4">
        <Card><CardHeader className="flex-row items-center justify-between space-y-0"><CardTitle>Which assistant sent them</CardTitle><CsvExportButton filename="ai-traffic-by-assistant.csv" rows={assistants} columns={ASSISTANT_TRAFFIC_COLUMNS} /></CardHeader><CardContent>
          <Table><THead><TR><TH>Assistant</TH><TH className="text-right">Visits</TH><TH className="text-right">Conversions</TH><TH>Referrer</TH></TR></THead>
            <TBody>{assistants.map((a) => <TR key={a.assistant}><TD className="font-medium">{a.assistant}</TD><TD className="text-right tabular-nums">{fmtInt(a.sessions)}</TD><TD className="text-right tabular-nums">{fmtInt(a.conversions)}</TD><TD className="text-xs text-muted-foreground">{a.sources.join(", ")}</TD></TR>)}</TBody></Table>
        </CardContent></Card>
        <Card><CardHeader className="flex-row items-center justify-between space-y-0"><CardTitle info="The pages assistants point people to — keep these accurate and current.">Where they landed</CardTitle><CsvExportButton filename="ai-traffic-landing-pages.csv" rows={landingPages} columns={AI_LANDING_COLUMNS} /></CardHeader><CardContent>
          <Table><THead><TR><TH>Landing page</TH><TH className="text-right">Visits</TH><TH className="text-right">Conv.</TH></TR></THead>
            <TBody>{landingPages.map((p) => <TR key={p.landing_page}><TD className="max-w-xs truncate text-xs"><a className="text-primary hover:underline" href={p.landing_page} target="_blank" rel="noreferrer">{p.landing_page.replace(/^https?:\/\/[^/]+/, "") || "/"}</a></TD><TD className="text-right tabular-nums">{fmtInt(p.sessions)}</TD><TD className="text-right tabular-nums">{fmtInt(p.conversions)}</TD></TR>)}</TBody></Table>
        </CardContent></Card>
      </div>
    </div>
  );
}

function SourcesTab({ pid }: { pid: string }) {
  const [filter, setFilter] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["citations", pid], queryFn: () => api.get<Citations>(`/projects/${pid}/geo/citations`) });
  const { data: competitors } = useCompetitors();
  const domains = useMemo(() => (data?.domains ?? []).filter((row) => !filter || `${row.domain} ${row.providers.join(" ")} ${row.sample_urls.join(" ")}`.toLowerCase().includes(filter.toLowerCase())), [data?.domains, filter]);
  const pagedDomains = usePaged(domains);
  if (isLoading) return <Loading />;
  if (!data?.domains.length) return <EmptyState title="No citations yet">Citations come only from grounded answers (OpenAI web search, Gemini Google Search, Perplexity).</EmptyState>;
  return (
    <Card><CardHeader><CardTitle info="Earning accurate coverage on these sites improves how AI describes you. If a domain is a rival product, add it as a competitor to track its share of voice.">Websites that influence AI answers</CardTitle><CardDescription>Cited across {data.total_answers} answers in the latest run.</CardDescription></CardHeader>
      <CardContent><div className="mb-3 flex gap-2"><Input className="max-w-sm" placeholder="Filter domains or providers…" value={filter} onChange={(e) => setFilter(e.target.value)} /><div className="ml-auto"><CsvExportButton filename="ai-influencing-sources.csv" rows={domains} columns={SOURCE_COLUMNS} /></div></div><Table><THead><TR><TH>Domain</TH><TH>Citations</TH><TH>Answers</TH><TH>Providers</TH><TH>Example URLs</TH><TH /></TR></THead>
        <TBody>{pagedDomains.items.map((d) => <TR key={d.domain}><TD className="font-medium">{d.domain}</TD><TD>{d.citations}</TD><TD>{d.answers}</TD><TD className="text-xs">{d.providers.join(", ")}</TD><TD className="text-xs">{d.sample_urls.map((u) => <div key={u}><a className="text-primary hover:underline truncate block max-w-md" href={u} target="_blank" rel="noreferrer">{u}</a></div>)}</TD><TD className="text-right whitespace-nowrap"><AddCompetitorButton pid={pid} domain={d.domain} competitors={competitors ?? []} /></TD></TR>)}</TBody></Table><Pagination state={pagedDomains} label="domains" /></CardContent></Card>
  );
}

function competitorNameFromDomain(domain: string): string {
  const base = domain.replace(/^www\./, "").split(".")[0].replace(/[-_]+/g, " ");
  return base.replace(/\b\w/g, (c) => c.toUpperCase());
}

function AddCompetitorButton({ pid, domain, competitors }: { pid: string; domain: string; competitors: Competitor[] }) {
  const qc = useQueryClient();
  const existing = competitors.find((c) => c.aliases.some((a) => a.toLowerCase().includes(domain.toLowerCase())) || c.name.toLowerCase() === competitorNameFromDomain(domain).toLowerCase());
  const add = useMutation({
    mutationFn: () => api.post(`/projects/${pid}/competitors`, { name: competitorNameFromDomain(domain), aliases: [domain], website: `https://${domain}` }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["competitors", pid] }); qc.invalidateQueries({ queryKey: ["domains", pid] }); },
  });
  if (existing) return <Badge variant="muted">tracked as {existing.name}</Badge>;
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => add.mutate()} disabled={add.isPending} title={`Track ${domain} as a competitor (name, alias and website are filled in)`}>
        <Plus className="h-3 w-3" /> Add as competitor
      </Button>
      {add.error ? <div className="text-xs text-red-700 dark:text-red-300 mt-1">{(add.error as Error).message}</div> : null}
    </>
  );
}

function PromptsTab({ pid, prompts, onAdd }: { pid: string; prompts: Prompt[]; onAdd: () => void }) {
  const [filter, setFilter] = useState("");
  const qc = useQueryClient();
  const upd = useMutation({ mutationFn: ({ id, ...body }: Partial<Prompt> & { id: string }) => api.patch(`/projects/${pid}/geo/prompts/${id}`, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts", pid] }) });
  const del = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/geo/prompts/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts", pid] }) });
  const rows = prompts.filter((row) => !filter || `${row.text} ${row.intent} ${row.topic ?? ""} ${row.language} ${row.country}`.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows);
  if (!prompts.length) return <EmptyState title="No prompts yet"><Button className="mt-2" onClick={onAdd}>Add prompts</Button></EmptyState>;
  return (
    <><div className="mb-3 flex gap-2"><Input className="max-w-sm" placeholder="Filter prompts…" value={filter} onChange={(e) => setFilter(e.target.value)} /><div className="ml-auto"><CsvExportButton filename="ai-prompts.csv" rows={rows} columns={PROMPT_COLUMNS} /></div></div><Table><THead><TR><TH>Prompt</TH><TH>Intent</TH><TH>Topic</TH><TH>Locale</TH><TH>Samples/run</TH><TH>Active</TH><TH /></TR></THead>
      <TBody>{paged.items.map((p) => <TR key={p.id}><TD className="max-w-md text-sm">{p.text}</TD><TD><Select value={p.intent} onChange={(e) => upd.mutate({ id: p.id, intent: e.target.value })} className="w-36">{["informational", "commercial", "comparison", "transactional", "navigational"].map((i) => <option key={i}>{i}</option>)}</Select></TD><TD className="text-xs">{p.topic ?? "—"}</TD><TD className="text-xs">{p.language}-{p.country}</TD><TD><Input type="number" min={1} max={10} className="w-16" defaultValue={p.samples_per_run} onBlur={(e) => upd.mutate({ id: p.id, samples_per_run: Number(e.target.value) })} /></TD><TD><input type="checkbox" checked={p.is_active} onChange={(e) => upd.mutate({ id: p.id, is_active: e.target.checked })} /></TD><TD><Button size="sm" variant="ghost" onClick={() => del.mutate(p.id)}>Delete</Button></TD></TR>)}</TBody></Table><Pagination state={paged} label="prompts" /></>
  );
}

function AddPrompts({ pid, onDone }: { pid: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ text: "", intent: "commercial", topic: "", language: "en", country: "US", samples: 3 });
  const add = useMutation({
    mutationFn: () => api.post(`/projects/${pid}/geo/prompts`, form.text.split("\n").map((t) => t.trim()).filter(Boolean).map((text) => ({ text, intent: form.intent, topic: form.topic || null, language: form.language, country: form.country, samples_per_run: form.samples }))),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["prompts", pid] }); onDone(); },
  });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
      <Field label="Prompts (one per line)"><Textarea rows={6} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} placeholder={"What is the best AI interview practice tool?\nTop platforms to hire developers in Singapore"} /></Field>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Intent"><Select value={form.intent} onChange={(e) => setForm({ ...form, intent: e.target.value })}>{["informational", "commercial", "comparison", "transactional", "navigational"].map((i) => <option key={i}>{i}</option>)}</Select></Field>
        <Field label="Topic"><Input value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value })} /></Field>
        <Field label="Language"><Input value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} /></Field>
        <Field label="Country"><Input value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} /></Field>
      </div>
      <Field label="Samples per run (repeated sampling per provider)"><Input type="number" min={1} max={10} value={form.samples} onChange={(e) => setForm({ ...form, samples: Number(e.target.value) })} /></Field>
      <ErrorBox error={add.error} />
      <Button type="submit" disabled={add.isPending}>Add</Button>
    </form>
  );
}

function RunsTab({ pid }: { pid: string }) {
  const [filter, setFilter] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["geo-runs", pid], queryFn: () => api.get<Summary[]>(`/projects/${pid}/geo/runs`) });
  const rows = (data ?? []).filter((row) => !filter || `${row.observed_at ?? ""} ${row.providers.join(" ")}`.toLowerCase().includes(filter.toLowerCase()));
  const pagedRuns = usePaged(rows, 10);
  if (isLoading) return <Loading />;
  if (!data?.length) return <EmptyState title="No runs yet" />;
  return (
    <><div className="mb-3 flex gap-2"><Input className="max-w-sm" placeholder="Filter runs or providers…" value={filter} onChange={(e) => setFilter(e.target.value)} /><div className="ml-auto"><CsvExportButton filename="ai-visibility-runs.csv" rows={rows} columns={RUN_COLUMNS} /></div></div><Table><THead><TR><TH>Run</TH><TH>Samples</TH><TH>Prompts</TH><TH>Providers</TH><TH>Brand mention rate</TH><TH>Own domain cited</TH><TH>Competitors</TH></TR></THead>
      <TBody>{pagedRuns.items.map((r) => <TR key={r.run_id}><TD className="text-xs"><TimeAgo value={r.observed_at} /></TD><TD>{r.samples}</TD><TD>{r.prompts}</TD><TD className="text-xs">{r.providers.join(", ")}</TD><TD className="font-medium">{fmtPct(r.brand_mention_rate, 0)}</TD><TD>{fmtPct(r.own_domain_cited_rate, 0)}</TD><TD className="text-xs">{Object.entries(r.competitors).slice(0, 5).map(([n, v]) => `${n} ${fmtPct(v, 0)}`).join(" · ")}</TD></TR>)}</TBody></Table><Pagination state={pagedRuns} label="runs" /></>
  );
}
