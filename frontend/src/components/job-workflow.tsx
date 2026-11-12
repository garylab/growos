import { ArrowDown, ArrowRight, ChartNoAxesCombined, Database, ListChecks, Sparkles } from "lucide-react";
import { InfoHint } from "@/components/ui/info-hint";
import { cn } from "@/lib/utils";

export interface CatalogItem { task_type: string; label: string; cost: "free" | "paid"; scope: string; default: boolean }

// These are product workflow stages, not queue dependencies. Availability and cost classification come from
// the catalog; a new task is still shown even before it receives a description here.
const stages = [
  { key: "collect", title: "Collect data", icon: Database },
  { key: "discover", title: "Discover", icon: Sparkles },
  { key: "measure", title: "Measure visibility", icon: ChartNoAxesCombined },
  { key: "plan", title: "Plan & track", icon: ListChecks },
] as const;
type Stage = typeof stages[number]["key"];
interface JobDetail { stage: Stage; title: string; description: string; payment?: string }
const details: Record<string, JobDetail> = {
  crawl_domain: { stage: "collect", title: "Website crawl & SEO audit", description: "Find pages and technical SEO issues." },
  measure_performance: { stage: "collect", title: "Page speed", description: "Measure performance with Lighthouse / PageSpeed." },
  sync_search_console: { stage: "collect", title: "Google Search Console", description: "Import search clicks, impressions and queries." },
  sync_bing_webmaster: { stage: "collect", title: "Bing Webmaster Tools", description: "Import search performance from Bing." },
  sync_analytics: { stage: "collect", title: "Website analytics", description: "Import traffic and conversions from GA4." },
  suggest_keywords: {
    stage: "discover", title: "Suggest keywords", description: "Find search terms from your website and search data.",
    payment: "May use AI input and output tokens to read your website and suggest more keywords when saved Search Console and crawl data are insufficient. Using the saved data itself costs no provider credits.",
  },
  suggest_competitors: {
    stage: "discover", title: "Suggest competitors", description: "Find competitors from citations and your website.",
    payment: "May use AI input and output tokens to identify competitors from your website when saved AI citations do not provide enough suggestions. Reusing saved citations costs no provider credits.",
  },
  suggest_prompts: {
    stage: "discover", title: "Suggest AI prompts", description: "Turn target keywords into buyer questions.",
    payment: "Uses search-provider credits to fetch People Also Ask questions for your target keywords. May also use AI input and output tokens to generate additional prompts from your website. Sampling the answers is a separate job.",
  },
  run_ai_visibility: {
    stage: "measure", title: "AI visibility sampling", description: "Check brand mentions and citations in AI answers.",
    payment: "Uses AI tokens for model API answers, or search-provider credits for supported AI search surfaces. Usage grows with active prompts, samples per prompt and the providers sampled; grounding or search calls may add charges.",
  },
  sync_rankings: {
    stage: "measure", title: "Keyword rankings", description: "Check search positions for your target keywords.",
    payment: "Uses search-provider credits to fetch results for each target keyword across connected ranking providers. Extra result pages or AI Overview requests may consume additional searches.",
  },
  sync_keyword_metrics: {
    stage: "measure", title: "Keyword metrics", description: "Refresh search volume, difficulty and CPC.",
    payment: "Uses keyword-data provider credits or API quota to look up metrics such as search volume, difficulty and cost per click for your target keywords. CPC is a reported metric; this job does not buy ads.",
  },
  sync_backlinks: {
    stage: "measure", title: "Backlinks", description: "Refresh referring domains and incoming links.",
    payment: "Uses backlink-provider credits or API quota to retrieve referring domains for each primary website. Providers that support individual backlink details receive an additional request for those links.",
  },
  monitor_brand_mentions: {
    stage: "measure", title: "Brand mentions", description: "Find mentions of your brand and competitors.",
    payment: "Connected paid sources may charge credits or usage fees to search for brand names, aliases and competitors. Public sources such as Hacker News and Bluesky do not themselves consume paid provider credits.",
  },
  build_growth_plan: { stage: "plan", title: "Rebuild growth plan", description: "Prioritize actions using the latest saved data." },
  measure_outcomes: { stage: "plan", title: "Re-measure action results", description: "Compare action results against first-party data." },
  snapshot_scorecard: { stage: "plan", title: "Scorecard snapshot", description: "Save today’s scores to track progress over time." },
};

interface WorkflowStageProps {
  stage: typeof stages[number]; index: number; jobs: CatalogItem[];
  checked: (job: CatalogItem) => boolean; disabled: boolean;
  onChange: (task: string, value: boolean) => void;
}

function WorkflowStage({ stage, index, jobs, checked, disabled, onChange }: WorkflowStageProps) {
  const Icon = stage.icon;
  return <li className="relative min-w-0">
    {index > 0 && <>
      <ArrowRight aria-hidden="true" className="absolute -left-6 top-2 hidden h-4 w-4 text-slate-400 lg:block" />
      <ArrowDown aria-hidden="true" className="absolute -top-7 left-2 h-4 w-4 text-slate-400 lg:hidden" />
    </>}
    <div className="relative z-10 mb-4">
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border bg-white text-primary dark:bg-slate-900"><Icon aria-hidden="true" className="h-4 w-4" /></span>
        <h3 className="text-sm font-semibold"><span className="sr-only">Stage {index + 1}: </span>{stage.title}</h3>
      </div>
    </div>
    <ul className="ml-4 space-y-3 border-l border-slate-300 pl-4 dark:border-slate-700">
      {jobs.map((job) => {
        const info = details[job.task_type];
        const title = info?.title ?? job.label;
        const id = `workflow-${job.task_type}`;
        const description = `${info?.description ?? job.label}${job.scope === "domain" ? " Runs for each primary website." : ""}`;
        return <li key={job.task_type} className="relative h-16 before:absolute before:-left-[17px] before:top-6 before:w-4 before:border-t before:border-slate-300 dark:before:border-slate-700">
          <div className={cn("relative flex h-full items-center rounded-lg border bg-white shadow-sm transition-colors dark:bg-slate-900",
            checked(job) ? "border-primary/50 ring-1 ring-primary/10" : "border-border hover:border-slate-400")}>
            <label title={description} className={cn("min-w-0 flex-1 cursor-pointer p-3", disabled && "pointer-events-none opacity-60")}>
              <span className="flex items-start gap-2">
                <input type="checkbox" aria-describedby={`${id}-description`} className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                  checked={checked(job)} disabled={disabled} onChange={(event) => onChange(job.task_type, event.target.checked)} />
                <span className="text-sm font-medium leading-5">{title}</span>
              </span>
              <span id={`${id}-description`} className="sr-only">{description}</span>
              <span className="sr-only">{job.cost === "paid" ? " (Paid)" : " (Free)"}</span>
            </label>
              {job.cost === "paid" && <InfoHint hover className="mr-3 shrink-0" label={`Cost details for ${title}`} width="w-72"
                tone="rounded-full text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                icon={<span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium dark:bg-slate-800">Paid <span aria-hidden="true">ⓘ</span></span>}>
                <span className="mb-1 block font-semibold text-foreground">What this job pays for</span>
                {info?.payment ?? "May consume credits, API quota or AI tokens from the connected provider."}
                <span className="mt-2 block">Actual charges depend on your provider and plan.</span>
              </InfoHint>}
          </div>
        </li>;
      })}
      {!jobs.length && <li className="py-3 text-xs text-muted-foreground">No available jobs in this stage.</li>}
    </ul>
  </li>;
}

export function JobWorkflow({ items, checked, onChange, disabled }: {
  items: CatalogItem[]; checked: (job: CatalogItem) => boolean;
  onChange: (task: string, value: boolean) => void; disabled: boolean;
}) {
  return <div role="region" aria-label="Job workflow" className="p-1">
    <ol className="grid gap-10 lg:grid-cols-4 lg:gap-8">
      {stages.map((stage, index) => <WorkflowStage key={stage.key} stage={stage} index={index}
        jobs={items.filter((job) => (details[job.task_type]?.stage ?? "collect") === stage.key)}
        checked={checked} onChange={onChange} disabled={disabled} />)}
    </ol>
  </div>;
}
