import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProjectId } from "@/hooks/useProject";
import { useActiveTab } from "@/hooks/useTabRoute";
import { BRAND_TABS } from "@/lib/nav";
import { useEnqueue } from "@/hooks/useJobs";
import { EmptyState, ErrorBox, Loading, Metric, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { Button } from "@/components/ui/button";
import { CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Select } from "@/components/ui/input";
import { fmtRelative } from "@/lib/time";
import { TimeAgo } from "@/components/ui/time";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

interface Mention { id: string; provider_key: string; source_url: string | null; source_name: string | null; title: string | null; content_excerpt: string | null; author: string | null; published_at: string | null; entity_type: string; entity_name: string; sentiment: string; sentiment_method: string; topics: string[]; intent: string; engagement: Record<string, number | string | null> }
interface Summary { entities: { entity_name: string; entity_type: string; total: number; positive: number; neutral: number; negative: number }[]; intents: Record<string, number>; sources: Record<string, number>; last_collected_at: string | null; definitions: Record<string, string> }
type EntitySummary = Summary["entities"][number];
type EngagementGroup = "views" | "likes" | "comments" | "shares";

const ENGAGEMENT_KEYS: Record<EngagementGroup, string[]> = {
  views: ["views", "plays"],
  likes: ["likes", "reactions", "points"],
  comments: ["comments", "replies"],
  shares: ["shares", "reposts"],
};

function engagementValue(engagement: Mention["engagement"], group: EngagementGroup): number | null {
  for (const key of ENGAGEMENT_KEYS[group]) {
    const value = engagement[key];
    if (typeof value === "number") return value;
    if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return null;
}

function mentionLinkLabel(mention: Mention): string {
  if (mention.title?.trim()) return mention.title;
  return `View ${mention.source_name ?? mention.provider_key} post`;
}

const MENTION_COLUMNS: CsvColumn<Mention>[] = [
  { key: "published", label: "Published", value: (r) => r.published_at }, { key: "source", label: "Source", value: (r) => r.source_name ?? r.provider_key },
  { key: "author", label: "Author", value: (r) => r.author }, { key: "entity", label: "Entity", value: (r) => r.entity_name },
  { key: "type", label: "Entity type", value: (r) => r.entity_type }, { key: "title", label: "Title", value: (r) => r.title },
  { key: "url", label: "URL", value: (r) => r.source_url }, { key: "excerpt", label: "Excerpt", value: (r) => r.content_excerpt },
  { key: "sentiment", label: "Sentiment", value: (r) => r.sentiment }, { key: "intent", label: "Intent", value: (r) => r.intent },
  { key: "topics", label: "Topics", value: (r) => r.topics.join(", ") },
  { key: "views", label: "Views / plays", value: (r) => engagementValue(r.engagement, "views") },
  { key: "likes", label: "Likes / points", value: (r) => engagementValue(r.engagement, "likes") },
  { key: "comments", label: "Comments / replies", value: (r) => engagementValue(r.engagement, "comments") },
  { key: "shares", label: "Shares / reposts", value: (r) => engagementValue(r.engagement, "shares") },
];
const ENTITY_COLUMNS: CsvColumn<EntitySummary>[] = [
  { key: "entity", label: "Entity", value: (r) => r.entity_name }, { key: "type", label: "Type", value: (r) => r.entity_type },
  { key: "total", label: "Total", value: (r) => r.total }, { key: "positive", label: "Positive", value: (r) => r.positive },
  { key: "neutral", label: "Neutral", value: (r) => r.neutral }, { key: "negative", label: "Negative", value: (r) => r.negative },
];


/** Per-tab page heading and its info tooltip, keyed by the tab id from BRAND_TABS. */
const BRAND_TAB_META: Record<string, { title: string; info: string }> = {
  "mentions": { title: "Mentions", info: "Public mentions of your brand and competitors from Hacker News, Bluesky and any RSS/Atom feeds you configure." },
  "by-entity": { title: "By entity", info: "Mentions grouped by your brand and each competitor, with their share of the conversation." },
};

export function BrandPage() {
  const pid = useProjectId();
  const enqueue = useEnqueue();
  const tab = useActiveTab(BRAND_TABS, "mentions");
  const { data: summary, isLoading } = useQuery({ queryKey: ["brand-summary", pid], queryFn: () => api.get<Summary>(`/projects/${pid}/brand/summary`), refetchInterval: 15000 });
  const [f, setF] = useState({ entity_type: "", intent: "", sentiment: "", provider_key: "" });
  const qs = new URLSearchParams({ limit: "200" }); Object.entries(f).forEach(([k, v]) => v && qs.set(k, v));
  const { data: mentions } = useQuery({ queryKey: ["mentions", pid, f], queryFn: () => api.get<Mention[]>(`/projects/${pid}/brand/mentions?${qs}`) });
  const pagedMentions = usePaged(mentions);
  const pagedEntities = usePaged(summary?.entities);
  if (isLoading) return <Loading />;
  const brand = summary?.entities.filter((e) => e.entity_type === "brand") ?? [];
  const total = summary?.entities.reduce((a, e) => a + e.total, 0) ?? 0;
  return (
    <div>
      <PageHeader title={BRAND_TAB_META[tab]?.title ?? "Brand Monitoring"} info={BRAND_TAB_META[tab]?.info ?? "Public mentions of your brand and competitors from Hacker News, Bluesky and any RSS/Atom feeds you configure."}
        actions={<Button onClick={() => enqueue.mutate({ task_type: "monitor_brand_mentions", params: {} })} disabled={enqueue.isPending}>Re-run</Button>} />
      <ErrorBox error={enqueue.error} />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Metric label="Mentions collected" value={total} source={summary?.last_collected_at ? `last run ${fmtRelative(summary.last_collected_at)}` : "never collected"} />
        <Metric label="Brand mentions" value={brand.reduce((a, e) => a + e.total, 0)} source={brand.length ? `${brand.reduce((a, e) => a + e.positive, 0)} positive · ${brand.reduce((a, e) => a + e.negative, 0)} negative` : ""} hint={summary?.definitions.sentiment} />
        <Metric label="With customer intent" value={Object.entries(summary?.intents ?? {}).filter(([k]) => k !== "none").reduce((a, [, v]) => a + v, 0)} source={Object.entries(summary?.intents ?? {}).filter(([k]) => k !== "none").map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")} hint={summary?.definitions.intent} />
        <Metric label="Sources" value={Object.keys(summary?.sources ?? {}).length} source={Object.entries(summary?.sources ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")} />
      </div>
        {tab === "mentions" && (<>
          <div className="flex flex-wrap gap-2 mb-3">
            <Select className="w-48" value={f.entity_type} onChange={(e) => setF({ ...f, entity_type: e.target.value })}><option value="">Brand + competitors</option><option value="brand">Brand only</option><option value="competitor">Competitors only</option></Select>
            <Select className="w-56" value={f.intent} onChange={(e) => setF({ ...f, intent: e.target.value })}><option value="">Any intent</option>{["question", "recommendation_request", "purchase_intent", "complaint"].map((i) => <option key={i} value={i}>{i.replace(/_/g, " ")}</option>)}</Select>
            <Select className="w-40" value={f.sentiment} onChange={(e) => setF({ ...f, sentiment: e.target.value })}><option value="">Any sentiment</option>{["positive", "neutral", "negative"].map((i) => <option key={i}>{i}</option>)}</Select>
            <Select className="w-40" value={f.provider_key} onChange={(e) => setF({ ...f, provider_key: e.target.value })}><option value="">Any source</option>{["hackernews", "bluesky", "rss"].map((i) => <option key={i}>{i}</option>)}</Select>
            <div className="ml-auto"><CsvExportButton filename="brand-mentions.csv" rows={mentions ?? []} columns={MENTION_COLUMNS} /></div>
          </div>
          {!mentions?.length ? <EmptyState title="No mentions found">Click “Re-run” to check for mentions.</EmptyState> : (
            <Table><THead><TR><TH>Published</TH><TH>Source</TH><TH>Author</TH><TH>Entity</TH><TH>Mention</TH><TH>Sentiment</TH><TH>Intent</TH><TH>Topics</TH><TH className="text-right">Views</TH><TH className="text-right">Likes</TH><TH className="text-right">Comments</TH><TH className="text-right">Shares</TH></TR></THead>
              <TBody>{pagedMentions.items.map((m) => <TR key={m.id}>
                <TD className="text-xs whitespace-nowrap"><TimeAgo value={m.published_at} /></TD>
                <TD className="text-xs whitespace-nowrap">{m.source_name ?? m.provider_key}</TD>
                <TD className="text-xs whitespace-nowrap">{m.engagement.author_url ? <a className="text-primary hover:underline" href={String(m.engagement.author_url)} target="_blank" rel="noreferrer">{m.author ?? "View profile"}</a> : (m.author ?? "—")}</TD>
                <TD><Badge variant={m.entity_type === "brand" ? "default" : "warning"}>{m.entity_name}</Badge></TD>
                <TD className="max-w-md text-sm"><a className="font-medium text-primary hover:underline" href={m.source_url ?? "#"} target="_blank" rel="noreferrer">{mentionLinkLabel(m)}</a><div className="text-xs text-muted-foreground line-clamp-2 cursor-help" title={m.content_excerpt ?? undefined}>{m.content_excerpt}</div></TD>
                <TD><StatusBadge status={m.sentiment} /></TD>
                <TD className="text-xs">{m.intent !== "none" ? m.intent.replace(/_/g, " ") : "—"}</TD>
                <TD className="text-xs">{m.topics.join(", ")}</TD>
                {(["views", "likes", "comments", "shares"] as EngagementGroup[]).map((group) => <TD key={group} className="text-xs text-right tabular-nums text-muted-foreground">{engagementValue(m.engagement, group)?.toLocaleString() ?? "—"}</TD>)}
              </TR>)}</TBody></Table>
          )}
          <Pagination state={pagedMentions} label="mentions" />
        </>)}
        {tab === "by-entity" && (<>
          <section><CardHeader className="flex-row items-center justify-between space-y-0"><CardTitle info="Sentiment is lexicon-based and coarse. Use it as a triage signal, then read the sources.">Mentions by entity</CardTitle><CsvExportButton filename="mentions-by-entity.csv" rows={summary?.entities ?? []} columns={ENTITY_COLUMNS} /></CardHeader>
            <CardContent><Table><THead><TR><TH>Entity</TH><TH>Type</TH><TH>Total</TH><TH>Positive</TH><TH>Neutral</TH><TH>Negative</TH></TR></THead><TBody>{pagedEntities.items.map((e) => <TR key={e.entity_name}><TD className="font-medium">{e.entity_name}</TD><TD className="text-xs">{e.entity_type}</TD><TD>{e.total}</TD><TD className="text-emerald-700 dark:text-emerald-300">{e.positive}</TD><TD>{e.neutral}</TD><TD className="text-red-700 dark:text-red-300">{e.negative}</TD></TR>)}</TBody></Table><Pagination state={pagedEntities} label="entities" /></CardContent></section>
        </>)}
    </div>
  );
}
