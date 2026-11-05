import { TrendingUp } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ReactNode } from "react";
import { api } from "@/lib/api";
import { useProjectId } from "@/hooks/useProject";
import { EmptyState, ErrorBox, InfoHint, Loading, Metric, PageHeader } from "@/components/ui/misc";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { delta, fmtInt, fmtNum, fmtPct } from "@/lib/utils";
import { fmtDay, fmtDuration } from "@/lib/time";
import { TimeAgo } from "@/components/ui/time";
import { ScorecardSection, useScorecard } from "@/pages/Scorecard";

/** Small uppercase section label with an optional click-to-reveal explanation. */
function SectionHeading({ children, info }: { children: ReactNode; info?: ReactNode }) {
  return (
    <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-2 flex items-center gap-1.5">
      {children}{info && <InfoHint>{info}</InfoHint>}
    </h2>
  );
}

interface OverviewData {
  project: { name: string; brand_name: string };
  seo: { domain_id: string; hostname: string; gsc_property: string | null; crawl: { run_id: string; finished_at: string; overall_score: number | null; categories: Record<string, number>; findings_count: Record<string, number>; html_pages: number; total_urls: number } | null; search: { available: boolean; totals?: { clicks: number; impressions: number; ctr: number; position: number }; previous?: { clicks: number; impressions: number; ctr: number; position: number }; daily?: { date: string; clicks: number; impressions: number }[] }; analytics: { available: boolean; totals?: AnalyticsTotals; previous?: AnalyticsTotals } }[];
  geo: { current: GeoSummary | null; previous: GeoSummary | null; runs_history: GeoSummary[]; ai_traffic?: { available: boolean; sessions: number; previous_sessions: number; share_of_sessions: number; by_assistant: { assistant: string; sessions: number }[] } };
  brand: { mentions: Record<string, number>; total: number; with_intent: number };
  opportunities: { counts: Record<string, number>; top: { id: string; title: string; module: string; priority_score: number; impact_score: number; confidence: number; effort: number; recommended_action: string; status: string }[] };
  actions: { counts: Record<string, number>; recent: { id: string; title: string; status: string; updated_at: string }[]; outcomes: { action_id: string; metric_key: string; baseline_value: number | null; current_value: number | null; delta_pct: number | null; measured_at: string }[] };
}
interface AnalyticsTotals { sessions: number; conversions: number; conversion_rate: number; avg_engagement_seconds: number; engagement_rate: number }
interface GeoSummary { run_id: string | null; observed_at: string | null; samples: number; prompts?: number; providers: string[]; brand_mention_rate: number | null; own_domain_cited_rate: number | null; competitors: Record<string, number> }

export function Overview() {
  const pid = useProjectId();
  const { data, isLoading, error } = useQuery({ queryKey: ["overview", pid], queryFn: () => api.get<OverviewData>(`/projects/${pid}/overview`), refetchInterval: 20000 });
  // Started here, not inside ScorecardSection: that only mounts past the early return below, so its request
  // used to wait for this one even though neither depends on the other. Same key, so it reuses this fetch.
  // Waiting for both is what stops the scorecard landing late and shoving every section below it down the
  // page; a reserved height cannot fix that, since the scorecard's own height depends on its data (history
  // chart, revenue block and empty state are all conditional). Now that they run together, waiting is free.
  const scorecard = useScorecard(pid);
  if (isLoading || scorecard.isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const primary = data.seo[0];
  const geo = data.geo.current;
  const aiTraffic = data.geo.ai_traffic;
  const comps = geo ? Object.entries(geo.competitors).slice(0, 5) : [];
  const nothingConfigured = !primary?.crawl && !primary?.search?.available && !geo && !data.brand.total;

  return (
    <div>
      <PageHeader title="Overview" />
      {nothingConfigured && (
        <div className="mb-6">
          <EmptyState title="No data collected yet">
            Add your website under <Link className="text-primary underline" to="/settings">Settings</Link>, then connect providers under <Link className="text-primary underline" to="/integrations">Integrations</Link>.
          </EmptyState>
        </div>
      )}

      <SectionHeading info="Three indices out of 100, built only from data actually collected.">Brand scorecard</SectionHeading>
      <div className="mb-6"><ScorecardSection pid={pid} /></div>

      <SectionHeading info="First-party data from Google Search Console, last 28 days vs the previous 28 days.">Traditional search</SectionHeading>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {primary?.search?.available ? (
          <>
            <Metric label="Clicks" value={fmtInt(primary.search.totals?.clicks)} change={delta(primary.search.totals?.clicks, primary.search.previous?.clicks)} source="GSC · vs previous 28 days" hint="Clicks from Google Search results to your site." />
            <Metric label="Impressions" value={fmtInt(primary.search.totals?.impressions)} change={delta(primary.search.totals?.impressions, primary.search.previous?.impressions)} source="GSC" hint="Times a page appeared in search results." />
            <Metric label="CTR" value={fmtPct(primary.search.totals?.ctr)} change={delta(primary.search.totals?.ctr, primary.search.previous?.ctr)} source="clicks / impressions" />
            <Metric label="Avg. position" value={fmtNum(primary.search.totals?.position)} change={primary.search.previous?.position && primary.search.totals?.position ? -(delta(primary.search.totals.position, primary.search.previous.position) ?? 0) : null} source="impression-weighted" hint="Lower is better. The change indicator is inverted, so an upward trend means improvement." />
          </>
        ) : (
          <Card className="col-span-2 lg:col-span-4"><CardContent className="py-6 text-sm text-muted-foreground"><Link className="text-primary underline" to="/integrations">Connect Google Search Console</Link> to see search performance.</CardContent></Card>
        )}
      </div>
      {primary?.search?.available && primary.search.daily && primary.search.daily.length > 1 && (
        <Card className="mb-6">
          <CardHeader><CardTitle info="Source: Google Search Console (first-party).">Clicks & impressions, last 90 days</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={primary.search.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
                <YAxis yAxisId="l" tick={{ fontSize: 11 }} /><YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} />
                <Tooltip />
                <Area yAxisId="r" type="monotone" dataKey="impressions" stroke="#94a3b8" fill="#e2e8f0" name="Impressions" />
                <Area yAxisId="l" type="monotone" dataKey="clicks" stroke="#2563eb" fill="#bfdbfe" name="Clicks" />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {primary?.analytics?.available && (
        <>
          <SectionHeading info="First-party data from Google Analytics 4, last 28 days vs the previous 28 days.">Website analytics</SectionHeading>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <Metric label="Sessions" value={fmtInt(primary.analytics.totals?.sessions)} change={delta(primary.analytics.totals?.sessions, primary.analytics.previous?.sessions)} source="GA4 · vs previous 28 days" />
            <Metric label="Conversions (key events)" value={fmtInt(primary.analytics.totals?.conversions)} change={delta(primary.analytics.totals?.conversions, primary.analytics.previous?.conversions)} source="GA4" />
            <Metric label="Conversion rate" value={fmtPct(primary.analytics.totals?.conversion_rate)} change={delta(primary.analytics.totals?.conversion_rate, primary.analytics.previous?.conversion_rate)} source="conversions / sessions" />
            <Metric label="Avg. engagement" value={fmtDuration(primary.analytics.totals?.avg_engagement_seconds)} change={delta(primary.analytics.totals?.avg_engagement_seconds, primary.analytics.previous?.avg_engagement_seconds)} source={`${fmtPct(primary.analytics.totals?.engagement_rate, 0)} of sessions engaged`} hint="GA4 average engagement time per session: total engagement time ÷ sessions." />
          </div>
        </>
      )}
      <SectionHeading info="Sampled by querying AI assistants via their provider APIs and inspecting the answers.">GEO AI visibility</SectionHeading>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {geo ? (
          <>
            <Metric label="Brand mention rate" value={fmtPct(geo.brand_mention_rate, 0)} change={delta(geo.brand_mention_rate, data.geo.previous?.brand_mention_rate)} source={`${geo.samples} samples · ${geo.providers.join(", ")}`} hint="Share of sampled AI answers that mention the brand or an alias." />
            <Metric label="Own site cited" value={fmtPct(geo.own_domain_cited_rate, 0)} change={delta(geo.own_domain_cited_rate, data.geo.previous?.own_domain_cited_rate)} source="grounded answers only" hint="Share of answers whose citations include your own domain." />
            <Metric
              label="Visits from AI assistants"
              value={aiTraffic?.available ? fmtInt(aiTraffic.sessions) : "—"}
              change={aiTraffic?.available ? delta(aiTraffic.sessions, aiTraffic.previous_sessions) : null}
              source={aiTraffic?.available ? `${fmtPct(aiTraffic.share_of_sessions)} of all visits · last 28 days` : "Connect GA4 or import analytics data"}
              hint="Sessions referred by ChatGPT, Perplexity, Gemini and similar, compared with the previous 28 days."
            />
            <Metric
              label="AI answers sampled"
              value={fmtInt(geo.samples)}
              source={[geo.prompts != null ? `${fmtInt(geo.prompts)} prompts` : null, `${geo.providers.length} providers`, "latest run"].filter(Boolean).join(" · ")}
              hint="Number of AI answers collected in the latest run, including repeated samples across prompts and providers. This shows the sample size behind the mention and citation rates."
            />
          </>
        ) : (
          <Card className="col-span-2 lg:col-span-4"><CardContent className="py-6 text-sm text-muted-foreground">No run yet. <Link className="text-primary underline" to="/ai-visibility">Run GEO AI Visibility</Link>.</CardContent></Card>
        )}
      </div>
      {data.geo.runs_history.length > 1 && (
        <Card className="mb-6">
          <CardHeader><CardTitle info="Each point is one sampling run across all prompts and providers.">Brand mention rate</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={[...data.geo.runs_history].reverse().map((r) => ({ t: r.observed_at ? fmtDay(r.observed_at) : "", rate: (r.brand_mention_rate ?? 0) * 100 }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" /><XAxis dataKey="t" tick={{ fontSize: 11 }} /><YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" /><Tooltip />
                <Line type="monotone" dataKey="rate" stroke="#7c3aed" name="Brand mention %" />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {geo && (
        <Card className="mb-6">
          <CardContent className="pt-5">
            <div className="text-xs font-medium text-muted-foreground">Competitors AI mention rate</div>
            {comps.length ? (
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
                {comps.map(([n, r]) => (
                  <div key={n} className="min-w-0 flex items-center gap-2 text-sm">
                    <span className="w-32 shrink-0 truncate" title={n}>{n}</span>
                    <div className="min-w-0 flex-1 h-2 rounded bg-slate-100 dark:bg-slate-800"><div className="h-2 rounded bg-amber-400" style={{ width: `${r * 100}%` }} /></div>
                    <span className="w-12 shrink-0 text-right tabular-nums">{fmtPct(r, 0)}</span>
                    {data.geo.previous && data.geo.previous.competitors[n] != null && r - data.geo.previous.competitors[n] >= 0.1 && <span className="inline-flex shrink-0 items-center gap-0.5 text-xs text-amber-700 dark:text-amber-300"><TrendingUp className="h-3 w-3" /> gaining</span>}
                  </div>
                ))}
              </div>
            ) : <p className="text-sm text-muted-foreground mt-2">No competitor mentioned in the latest run.</p>}
          </CardContent>
        </Card>
      )}

      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
            <CardTitle info="Ranked by priority = impact × confidence × effort factor.">Biggest acquisition opportunities</CardTitle>
            <Link className="shrink-0 text-sm text-muted-foreground underline" to="/plan">Full plan</Link>
          </CardHeader>
          <CardContent>
            {data.opportunities.top.length ? (
              <ol className="space-y-2">
                {data.opportunities.top.map((o) => (
                  <li key={o.id} className="flex items-baseline gap-3 leading-tight">
                    <span className="w-12 shrink-0 text-right text-lg font-semibold tabular-nums text-primary">{o.priority_score.toFixed(0)}</span>
                    <Link to="/plan" className="min-w-0 font-medium hover:underline">{o.title}</Link>
                  </li>
                ))}
              </ol>
            ) : <p className="text-sm text-muted-foreground">No items yet.</p>}
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle info={<><span className="block">From the latest SiteOne crawl.</span>{primary?.crawl && <span className="mt-1.5 block border-t pt-1.5"><TimeAgo value={primary.crawl.finished_at} /> · {primary.crawl.html_pages} HTML pages</span>}</>}>Site health</CardTitle></CardHeader>
            <CardContent className="text-sm">
              {primary?.crawl ? (
                <>
                  <div className="text-3xl font-semibold">{primary.crawl.overall_score ?? "—"}<span className="text-base text-muted-foreground">/10</span></div>
                  <div className="flex flex-wrap gap-1">{Object.entries(primary.crawl.categories).map(([k, v]) => <span key={k} className="rounded bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs">{k} {v}</span>)}</div>
                  <div className="mt-2 text-xs">{primary.crawl.findings_count.critical ?? 0} critical · {primary.crawl.findings_count.warning ?? 0} warnings</div>
                </>
              ) : <p className="text-muted-foreground">No crawl yet.</p>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Are actions producing results?</CardTitle></CardHeader>
            <CardContent className="text-sm space-y-2">
              {data.actions.outcomes.length ? data.actions.outcomes.slice(0, 5).map((o, i) => (
                <div key={i} className="flex justify-between"><span className="text-muted-foreground">{o.metric_key}</span><span className={o.delta_pct != null && o.delta_pct > 0 ? "text-emerald-600" : "text-red-600"}>{o.delta_pct != null ? `${o.delta_pct > 0 ? "+" : ""}${o.delta_pct.toFixed(1)}%` : "—"}</span></div>
              )) : <p className="text-muted-foreground">No measured outcomes yet.</p>}
              <div className="text-xs text-muted-foreground pt-1">{Object.entries(data.actions.counts).map(([k, v]) => `${v} ${k}`).join(" · ") || "No actions"}</div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
