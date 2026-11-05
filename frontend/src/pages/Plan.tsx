import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, Bot, Briefcase, Check, ChevronDown, ChevronRight, Clock, ExternalLink, FileText, Globe, Link2, Megaphone, MessagesSquare, Minus, Plug, Sparkles, Square, SquareCheck, Target, Undo2, Users, Video } from "lucide-react";
import { api, type ContentDraft, type Job, type Writer } from "@/lib/api";
import { useProjectId } from "@/hooks/useProject";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Select, Textarea } from "@/components/ui/input";
import { useAppStore } from "@/store/app";
import { PenLine, Sparkles as SparkIcon } from "lucide-react";
import { EmptyState, ErrorBox, InfoHint, Loading, PageHeader } from "@/components/ui/misc";
import { cn, fmtPct } from "@/lib/utils";
import { TimeAgo } from "@/components/ui/time";

export interface PlanItem {
  id: string; key: string; section: "setup" | "fix" | "routine"; cadence: string; category: string; title: string; why: string;
  steps: string[]; suggestions: Record<string, any>; evidence: any[]; impact: number; effort: number; priority: number;
  status: string; completions: { at: string; note: string | null }[]; next_due_at: string | null; last_done_at: string | null;
  resolved_at: string | null; source: string; note: string | null; due: boolean;
  assignee_id: string | null; assignee: { id: string; email: string; name: string | null } | null; due_date: string | null;
  confidence: number; score_breakdown: Record<string, any>; origin: string; target_urls: string[]; target_keywords: string[];
  history: { at: string; event: string; actor?: string; from?: number; to?: number }[];
}
interface Plan { summary: { open_fixes: number; setup_open: number; business_open: number; fix_open: number; routines_due: number; routines_total: number; done_total: number; last_generated_at: string | null; total: number }; setup: PlanItem[]; business: PlanItem[]; fix: PlanItem[]; routine: PlanItem[]; members: { id: string; email: string; name: string | null }[] }

const CATEGORY_LABEL: Record<string, string> = {
  website: "Website", content: "Content", video: "Video", community: "Community", backlinks: "Backlinks & mentions",
  conversion: "Turn visitors into customers", competitors: "Competitors", ai_visibility: "AI assistants", brand: "Brand",
  business: "Business basics", setup: "Setup",
};
const CADENCE_LABEL: Record<string, string> = { daily: "Every day", weekly: "Every week", monthly: "Every month", once: "One time" };
const CATEGORY_ICON: Record<string, { icon: typeof Globe; color: string }> = {
  website: { icon: Globe, color: "text-sky-600 bg-sky-100 dark:bg-sky-900/40 dark:text-sky-300" },
  content: { icon: FileText, color: "text-violet-600 bg-violet-100 dark:bg-violet-900/40 dark:text-violet-300" },
  video: { icon: Video, color: "text-rose-600 bg-rose-100 dark:bg-rose-900/40 dark:text-rose-300" },
  community: { icon: MessagesSquare, color: "text-teal-600 bg-teal-100 dark:bg-teal-900/40 dark:text-teal-300" },
  backlinks: { icon: Link2, color: "text-amber-600 bg-amber-100 dark:bg-amber-900/40 dark:text-amber-300" },
  conversion: { icon: Target, color: "text-emerald-600 bg-emerald-100 dark:bg-emerald-900/40 dark:text-emerald-300" },
  competitors: { icon: Users, color: "text-orange-600 bg-orange-100 dark:bg-orange-900/40 dark:text-orange-300" },
  ai_visibility: { icon: Bot, color: "text-indigo-600 bg-indigo-100 dark:bg-indigo-900/40 dark:text-indigo-300" },
  brand: { icon: Megaphone, color: "text-pink-600 bg-pink-100 dark:bg-pink-900/40 dark:text-pink-300" },
  business: { icon: Briefcase, color: "text-slate-600 bg-slate-100 dark:bg-slate-800 dark:text-slate-300" },
  setup: { icon: Plug, color: "text-blue-600 bg-blue-100 dark:bg-blue-900/40 dark:text-blue-300" },
};
function CategoryIcon({ category }: { category: string }) {
  const c = CATEGORY_ICON[category] ?? CATEGORY_ICON.business;
  const I = c.icon;
  return <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md", c.color)} title={CATEGORY_LABEL[category] ?? category}><I className="h-4 w-4" /></span>;
}


/** In-app destinations referenced in "how to do it" steps, e.g. "SEO Performance → Run crawl & audit".
 *  Tabs are URL-addressable, so each reference can point at the exact tab. */
const APP_PAGES: { label: string; route: (step: string) => string }[] = [
  { label: "GEO AI Visibility", route: (s) => (/prompt/i.test(s) ? "/ai-visibility/prompts" : "/ai-visibility/visibility") },
  { label: "Growth Opportunities", route: () => "/opportunities/opportunities" },
  { label: "Actions & Results", route: () => "/actions" },
  { label: "Brand Monitoring", route: () => "/brand/mentions" },
  { label: "Brand Intelligence", route: () => "/brand/mentions" },
  { label: "SEO Performance", route: (s) => (/search console|search performance|property|sync/i.test(s) ? "/seo/search-performance"
      : /lighthouse|page performance|core web vitals/i.test(s) ? "/seo/page-performance" : "/seo/audit-and-pages") },
  { label: "SEO Intelligence", route: (s) => (/search console|search performance|property|sync/i.test(s) ? "/seo/search-performance"
      : /lighthouse|page performance|core web vitals/i.test(s) ? "/seo/page-performance" : "/seo/audit-and-pages") },
  { label: "Integrations", route: () => "/integrations" },
  { label: "Competitors", route: (s) => (/change/i.test(s) ? "/competitors/page-changes" : "/competitors/competitors") },
  { label: "Settings", route: () => "/settings" },
];
const BARE_LINKS: Record<string, string> = {
  "business.google.com": "https://business.google.com",
  "opengraph.xyz": "https://www.opengraph.xyz",
  "search.google.com": "https://search.google.com/test/rich-results",
};
const URL_RE = new RegExp(`(https?://[^\\s)]+|${Object.keys(BARE_LINKS).join("|").replace(/\./g, "\\.")})`, "g");

/** Renders a step with its in-app destinations and any URLs as real links. */
function StepText({ text }: { text: string }) {
  const nodes: React.ReactNode[] = [];
  let key = 0;

  const pushWithAppLinks = (chunk: string) => {
    // Accept a page name only where it is used as a destination: "Page → …", at the start of the step,
    // or after a preposition ("under Settings"). Never inside ordinary prose.
    type Hit = { start: number; end: number; label: string; to: string };
    const hits: Hit[] = [];
    for (const page of APP_PAGES) {
      const re = new RegExp(`(^|\\b(?:under|from|in|on|at|to|via|open|see|the)\\s+)(${page.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})(\\s*(?:→|->)|\\b)`, "gi");
      for (const m of chunk.matchAll(re)) {
        const at = (m.index ?? 0) + (m[1]?.length ?? 0);
        const isDestination = Boolean(m[3]?.trim()) || (m[1] ?? "").length > 0 || at === 0;
        if (isDestination) hits.push({ start: at, end: at + m[2].length, label: m[2], to: page.route(text) });
      }
    }
    hits.sort((a, b) => a.start - b.start);
    let cursor = 0;
    for (const hit of hits) {
      if (hit.start < cursor) continue; // skip overlapping matches
      if (hit.start > cursor) nodes.push(<span key={key++}>{chunk.slice(cursor, hit.start)}</span>);
      nodes.push(<Link key={key++} to={hit.to} className="text-primary font-medium hover:underline">{hit.label}</Link>);
      cursor = hit.end;
    }
    if (cursor < chunk.length) nodes.push(<span key={key++}>{chunk.slice(cursor)}</span>);
  };

  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const at = m.index ?? 0;
    if (at > last) pushWithAppLinks(text.slice(last, at));
    const raw = m[0];
    nodes.push(<a key={key++} href={BARE_LINKS[raw] ?? raw} target="_blank" rel="noreferrer" className="text-primary hover:underline break-all">{raw}</a>);
    last = at + raw.length;
  }
  if (last < text.length) pushWithAppLinks(text.slice(last));
  return <>{nodes}</>;
}

export function PlanPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["plan", pid], queryFn: () => api.get<Plan>(`/projects/${pid}/plan`), enabled: !!pid, refetchInterval: 20000 });
  const generate = useMutation({ mutationFn: () => api.post<Job>(`/projects/${pid}/plan/generate`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); setTimeout(() => qc.invalidateQueries({ queryKey: ["plan", pid] }), 6000); } });
  const [showDone, setShowDone] = useState(false);
  const [mineOnly, setMineOnly] = useState(false);
  const me = useAppStore((st) => st.user);
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const s = data.summary;
  const mine = (i: PlanItem) => !mineOnly || (me?.id ? i.assignee_id === me.id : false);
  const openSetup = data.setup.filter((i) => (showDone || i.status === "todo" || i.status === "in_progress") && mine(i));
  const openFix = data.fix.filter((i) => (showDone || i.status === "todo" || i.status === "in_progress") && mine(i));
  const openBusiness = (data.business ?? []).filter((i) => (showDone || i.status === "todo" || i.status === "in_progress") && mine(i));
  const routines = data.routine.filter((i) => (showDone || i.status !== "skipped") && mine(i));
  const empty = !data.setup.length && !data.fix.length && !data.routine.length && !(data.business ?? []).length;
  const cards = [
    { show: s.setup_open > 0, label: "Start here", value: s.setup_open, hint: "Connect your data so the rest of the plan gets specific", onSelect: () => jumpTo("setup") },
    { show: (data.business ?? []).length > 0, label: "Business basics", value: s.business_open ?? 0, hint: "Trust and customer-journey checks", onSelect: () => jumpTo("business") },
    { show: data.fix.length > 0 || s.setup_open === 0, label: "To fix once", value: s.fix_open ?? Math.max(0, s.open_fixes - s.setup_open - (s.business_open ?? 0)), hint: "Website and content fixes waiting", onSelect: () => jumpTo("fix") },
    { show: true, label: "Due now", value: s.routines_due, hint: `${s.routines_total ?? data.routine.length} recurring habit(s) in total`, onSelect: () => jumpTo("routine") },
    // Completed items live inside their own sections, so this reveals them rather than scrolling somewhere.
    { show: true, label: "Completed", value: s.done_total, hint: "Items finished and routines logged. Opens them in the lists below.", onSelect: () => setShowDone((v) => !v) },
  ].filter((c) => c.show);

  return (
    <div>
      <PageHeader
        title="Your growth plan"
        info="Everything to do to get found more often and turn that into sales. Fix the one-time items, then keep the weekly habits going."
        actions={<>
          {me && <label className="flex items-center gap-1 text-xs text-muted-foreground"><input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} /> only mine</label>}
          <label className="flex items-center gap-1 text-xs text-muted-foreground"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> show completed</label>
          <Button onClick={() => generate.mutate()} disabled={generate.isPending}><Sparkles className="h-4 w-4" /> {generate.isPending ? "Working…" : "Refresh plan"}</Button>
        </>}
      />
      <ErrorBox error={generate.error} />
      {generate.isSuccess && <div className="mb-4 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">Rebuilding your plan…</div>}

      <div className={cn("grid grid-cols-2 gap-3 mb-6", STAT_COLS[cards.length] ?? "lg:grid-cols-5")}>
        {cards.map((c) => <Stat key={c.label} label={c.label} value={c.value} hint={c.hint} onSelect={c.onSelect} />)}
      </div>

      {empty ? (
        <EmptyState title="No plan yet">Click <b>Refresh plan</b>, or run a website audit first under <Link className="text-primary underline" to="/seo">SEO Performance</Link>.</EmptyState>
      ) : (
        <div className="space-y-8">
          {openSetup.length > 0 && <Section id="setup" title="Start here" description="Each one makes the rest of the plan more specific. Takes a few minutes." items={openSetup} pid={pid} members={data.members} />}
          {openBusiness.length > 0 && <Section id="business" title="Business basics" description="Trust and the customer journey. Buyers, Google and AI assistants all look for these before recommending you." items={openBusiness} pid={pid} members={data.members} />}
          {openFix.length > 0 && <Section id="fix" title="Fix once" description="Do these once and they stay fixed. The list shrinks automatically when the next audit confirms the fix." items={openFix} pid={pid} members={data.members} />}
          {routines.length > 0 && <Section id="routine" title="Keep doing" description="The habits that compound. Tick one off each time you do it; it comes back when it is due again." items={routines} pid={pid} members={data.members} routine />}
        </div>
      )}
      {s.last_generated_at && <p className="mt-8 text-xs text-muted-foreground">Plan last rebuilt <TimeAgo value={s.last_generated_at} />.</p>}
    </div>
  );
}

const STAT_COLS: Record<number, string> = { 1: "lg:grid-cols-1", 2: "lg:grid-cols-2", 3: "lg:grid-cols-3", 4: "lg:grid-cols-4", 5: "lg:grid-cols-5" };

const jumpTo = (section: string) => document.getElementById(`plan-${section}`)?.scrollIntoView({ behavior: "smooth", block: "start" });

function Stat({ label, value, hint, onSelect }: { label: string; value: number; hint: string; onSelect: () => void }) {
  return (
    <Card className="cursor-pointer transition-colors hover:border-primary/50 hover:bg-slate-50 dark:hover:bg-slate-800/50" onClick={onSelect}>
      <CardContent className="pt-5">
        <div className="text-xs font-medium text-muted-foreground flex items-center gap-1">{label}<InfoHint>{hint}</InfoHint></div>
        <div className="mt-1 text-3xl font-semibold tabular-nums">{value}</div>
      </CardContent>
    </Card>
  );
}

function Section({ id, title, description, items, pid, members, routine }: { id: string; title: string; description: string; items: PlanItem[]; pid: string; members: { id: string; email: string; name: string | null }[]; routine?: boolean }) {
  return (
    <section id={`plan-${id}`} className="scroll-mt-6">
      <h2 className="text-lg font-semibold flex items-center gap-1.5 mb-3">{title}<InfoHint width="w-72">{description}</InfoHint></h2>
      <div className="space-y-2">{items.map((i) => <Item key={i.id} item={i} pid={pid} members={members} routine={routine} />)}</div>
    </section>
  );
}

function Item({ item, pid, members, routine }: { item: PlanItem; pid: string; members: { id: string; email: string; name: string | null }[]; routine?: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["plan", pid] });
  const complete = useMutation({ mutationFn: () => api.post<PlanItem>(`/projects/${pid}/plan/items/${item.id}/complete`, { note: note || null }), onSuccess: () => { setNote(""); refresh(); } });
  const status = useMutation({ mutationFn: (st: string) => api.post<PlanItem>(`/projects/${pid}/plan/items/${item.id}/status`, { status: st }), onSuccess: refresh });
  const assign = useMutation({ mutationFn: (userId: string | null) => api.post<PlanItem>(`/projects/${pid}/plan/items/${item.id}/assign`, { user_id: userId }), onSuccess: refresh });
  const uncomplete = useMutation({ mutationFn: () => api.post<PlanItem>(`/projects/${pid}/plan/items/${item.id}/uncomplete`, {}), onSuccess: refresh });
  const { data: linked } = useQuery({ queryKey: ["linked-actions", pid], queryFn: () => api.get<Record<string, { action_id: string; status: string }>>(`/projects/${pid}/actions/linked`) });
  const tracked = linked?.[item.id];
  const track = useMutation({
    mutationFn: () => api.post<{ id: string }>(`/projects/${pid}/plan/items/${item.id}/track`, {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["linked-actions", pid] }); qc.invalidateQueries({ queryKey: ["actions", pid] }); refresh(); },
  });
  const writable = ["content", "video", "community", "backlinks", "ai_visibility", "brand"].includes(item.category);
  const done = item.status === "done";
  const sugg = item.suggestions || {};
  return (
    <Card className={cn(done && "opacity-60", item.due && routine && "border-primary/40")}>
      <CardContent className="pt-4">
        <div className="flex gap-3">
          {/* Status only — deliberately not a control, so a stray click cannot complete an item. */}
          <span className="mt-0.5 shrink-0 text-muted-foreground" title={done ? "Done" : "Not done yet"}>
            {done ? <SquareCheck className="h-5 w-5 text-emerald-600" /> : <Square className="h-5 w-5" />}
          </span>
          <CategoryIcon category={item.category} />
          <div className="min-w-0 flex-1">
            <button className="flex w-full items-start gap-1 text-left font-medium hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? <ChevronDown className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />}
              <span className="min-w-0">{item.title}</span>
            </button>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Badge variant="muted">{CATEGORY_LABEL[item.category] ?? item.category}</Badge>
              {routine && <Badge variant={item.due ? "info" : "outline"}>{CADENCE_LABEL[item.cadence]}</Badge>}
              {routine && item.last_done_at && <span className="text-xs text-muted-foreground">last done <TimeAgo value={item.last_done_at} /></span>}
              {routine && item.completions?.length > 0 && <span className="text-xs text-muted-foreground">· {item.completions.length}× done</span>}
              {item.resolved_at && <Badge variant="success">verified fixed</Badge>}
              {item.assignee && <Badge variant="info" title={item.assignee.email}>{item.assignee.name || item.assignee.email}</Badge>}
              {item.origin === "ai" && <Badge variant="info" title="Added by the AI analyst from your data">AI analyst</Badge>}
              {tracked && <Badge variant="success" title="A tracked result exists for this item">measuring</Badge>}
            </div>
            {open && (
              <div className="mt-3 space-y-3 text-sm">
                <p className="text-muted-foreground">{item.why}</p>
                {item.steps?.length > 0 && <ol className="list-decimal pl-5 space-y-1">{item.steps.map((st, n) => <li key={n}><StepText text={st} /></li>)}</ol>}
                <ScorePanel item={item} />
                <Suggestions s={sugg} />
                <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
                  <span className="text-muted-foreground">Assigned to</span>
                  <Select className="w-56 h-8" value={item.assignee_id ?? ""} onChange={(e) => assign.mutate(e.target.value || null)}>
                    <option value="">nobody yet</option>
                    {members.map((m) => <option key={m.id} value={m.id}>{m.name || m.email}</option>)}
                  </Select>
                  {members.length === 0 && <span className="text-muted-foreground">Add people under Team to assign work.</span>}
                  <ErrorBox error={assign.error} />
                </div>
                {writable && <ContentPanel pid={pid} item={item} />}
                <div className="flex flex-wrap items-end gap-2 pt-1">
                  <Textarea rows={1} className="min-h-[36px] flex-1 min-w-[16rem]" placeholder={routine ? "What did you do? (link, title…)" : "Note (optional)"} value={note} onChange={(e) => setNote(e.target.value)} />
                  {routine ? <Button size="sm" onClick={() => complete.mutate()} disabled={complete.isPending}>Mark done today</Button>
                   : done ? <Button size="sm" variant="outline" onClick={() => uncomplete.mutate()} disabled={uncomplete.isPending}><Undo2 className="h-3.5 w-3.5" /> Undo</Button>
                          : <Button size="sm" onClick={() => status.mutate("done")} disabled={status.isPending}>Mark done</Button>}
                  {routine && item.completions?.length > 0 && <Button size="sm" variant="outline" onClick={() => uncomplete.mutate()} disabled={uncomplete.isPending} title="Remove the most recent entry and restore the previous due date"><Undo2 className="h-3.5 w-3.5" /> Undo last</Button>}
                  {!routine && (tracked
                    ? <Link to="/actions" className="flex items-center gap-1 text-xs text-primary hover:underline self-center">See the measured result <ArrowRight className="h-3 w-3" /></Link>
                    : <Button size="sm" variant="outline" onClick={() => track.mutate()} disabled={track.isPending} title="Creates a tracked action so we can measure whether this worked">Track the result</Button>)}
                  {!done && <Button size="sm" variant="ghost" onClick={() => status.mutate("skipped")}>Not relevant</Button>}
                  <ErrorBox error={uncomplete.error} />
                </div>
                {routine && item.completions?.length > 0 && (
                  <div className="text-xs text-muted-foreground"><b>History:</b> {item.completions.slice(-5).reverse().map((c, n) => <div key={n}><TimeAgo value={c.at} />{c.note ? ` — ${c.note}` : ""}</div>)}</div>
                )}
              </div>
            )}
          </div>
          <div className="shrink-0 text-right">
            <div className="flex items-center justify-end gap-1 text-xs text-muted-foreground">
              impact
              <InfoHint width="w-72">How much this should move the needle, scored 0–100 from the evidence behind it. It is one of three inputs to the order of this list: priority = impact × confidence × effort factor. Open the item to see the full calculation and the evidence.</InfoHint>
            </div>
            <div className="text-lg font-semibold tabular-nums text-primary">{Math.round(item.impact)}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ScorePanel({ item }: { item: PlanItem }) {
  const b = item.score_breakdown || {};
  const ev = item.evidence || [];
  if (!ev.length && !b.formula) return null;
  return (
    <div className="rounded-md border bg-slate-50 dark:bg-slate-800/60 p-3 text-xs space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold uppercase tracking-wide text-muted-foreground">Why this ranks here</span>
        <span className="text-muted-foreground">
          priority <b className="text-foreground">{item.priority}</b> = impact {Math.round(item.impact)} × confidence {fmtPct(item.confidence, 0)} × effort factor {b.effort_factor ?? "—"}
          {b.effort_label ? ` (${b.effort_label})` : ""}
        </span>
      </div>
      {ev.length > 0 && (
        <div>
          <div className="font-medium mb-1">Evidence ({ev.length})</div>
          <ul className="space-y-1">{ev.map((e: any, i: number) => (
            <li key={i} className="rounded border bg-white dark:bg-slate-900 p-2">
              <div className="flex gap-2 items-center">
                <Badge variant={e.measurement_type === "first_party" ? "success" : "muted"}>{String(e.measurement_type || "observed").replace("_", " ")}</Badge>
                <span className="text-muted-foreground">{e.table} · {(e.record_ids || []).length} record(s)</span>
              </div>
              <div className="mt-1 break-words">{e.summary}</div>
            </li>))}</ul>
        </div>
      )}
      {(item.target_urls?.length > 0 || item.target_keywords?.length > 0) && (
        <div className="text-muted-foreground [overflow-wrap:anywhere]">Targets: {[...(item.target_urls || []), ...(item.target_keywords || []).map((k) => `“${k}”`)].slice(0, 8).join(", ")}</div>
      )}
      {item.history?.length > 0 && (
        <details><summary className="cursor-pointer text-muted-foreground">History</summary>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">{item.history.slice(-8).reverse().map((h, i) => (
            <li key={i}><TimeAgo value={h.at} /> · {h.event.replace(/_/g, " ")}{h.from != null ? ` ${h.from} → ${h.to}` : ""}{h.actor ? ` · ${h.actor}` : ""}</li>))}</ul>
        </details>
      )}
    </div>
  );
}

function ContentPanel({ pid, item }: { pid: string; item: PlanItem }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const topics: string[] = (item.suggestions?.topics ?? []).map((t: any) => t.topic)
    .concat((item.suggestions?.prompts ?? []).map((p: any) => (typeof p === "string" ? p : p.prompt)))
    .filter(Boolean);
  const [form, setForm] = useState({ kind: item.category === "video" ? "video_script" : "article", channel: item.category === "video" ? "youtube_short" : "blog", topic: topics[0] ?? item.title, notes: "", provider_key: "" });
  const { data: writers } = useQuery({ queryKey: ["writers", pid], queryFn: () => api.get<{ writers: Writer[]; kinds: string[]; channels: string[] }>(`/projects/${pid}/content/writers`), enabled: open });
  const { data: drafts } = useQuery({ queryKey: ["drafts", pid, item.id], queryFn: () => api.get<ContentDraft[]>(`/projects/${pid}/content?plan_item_id=${item.id}`), refetchInterval: (q) => (q.state.data?.length ? false : 5000) });
  const generate = useMutation({
    mutationFn: () => api.post<Job>(`/projects/${pid}/content/generate`, { ...form, plan_item_id: item.id, provider_key: form.provider_key || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); setTimeout(() => qc.invalidateQueries({ queryKey: ["drafts", pid, item.id] }), 8000); },
  });
  return (
    <div className="rounded-md border bg-slate-50 dark:bg-slate-800/60 p-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Write it with AI</div>
        <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}><PenLine className="h-3 w-3" /> {open ? "Hide" : "Draft something"}</Button>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="grid md:grid-cols-3 gap-2">
            <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value, channel: e.target.value === "video_script" ? "youtube_short" : e.target.value === "social_post" ? "linkedin" : "blog" })}>
              <option value="article">Article</option><option value="social_post">Social post</option><option value="video_script">Video script</option>
            </Select>
            <Select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
              {(writers?.channels ?? ["blog"]).map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
            </Select>
            <Select value={form.provider_key} onChange={(e) => setForm({ ...form, provider_key: e.target.value })}>
              <option value="">best available writer</option>
              {(writers?.writers ?? []).map((w) => <option key={w.provider_key} value={w.provider_key}>{w.display_name}{w.local ? " (local, open source)" : ""}{w.model ? ` · ${w.model}` : ""}</option>)}
            </Select>
          </div>
          {topics.length > 0 && (
            <Select value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value })}>
              {topics.map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
          )}
          <Textarea rows={2} placeholder="Anything specific to include? (optional)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          {writers && writers.writers.length === 0 && <p className="text-xs text-amber-700 dark:text-amber-300">No AI provider configured. Add one under Integrations.</p>}
          <Button size="sm" onClick={() => generate.mutate()} disabled={generate.isPending || !form.topic}><SparkIcon className="h-3 w-3" /> {generate.isPending ? "Writing…" : "Generate draft"}</Button>
          {generate.isSuccess && <span className="ml-2 text-xs text-muted-foreground">Writing…</span>}
          <ErrorBox error={generate.error} />
        </div>
      )}
      {(drafts ?? []).length > 0 && <div className="mt-3 space-y-2">{drafts!.map((d) => <DraftCard key={d.id} pid={pid} draft={d} itemId={item.id} />)}</div>}
    </div>
  );
}

function DraftCard({ pid, draft, itemId }: { pid: string; draft: ContentDraft; itemId: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState(draft.body);
  const refresh = () => qc.invalidateQueries({ queryKey: ["drafts", pid, itemId] });
  const save = useMutation({ mutationFn: (b: Record<string, unknown>) => api.patch<ContentDraft>(`/projects/${pid}/content/${draft.id}`, b), onSuccess: refresh });
  const del = useMutation({ mutationFn: () => api.delete(`/projects/${pid}/content/${draft.id}`), onSuccess: refresh });
  const copy = (text: string) => navigator.clipboard?.writeText(text);
  const a = draft.assets || {};
  return (
    <div className="rounded border bg-white dark:bg-slate-900 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="muted">{draft.kind.replace("_", " ")}</Badge>
        <Badge variant="outline">{draft.channel.replace("_", " ")}</Badge>
        <button className="font-medium text-sm text-left hover:underline flex-1 min-w-0 truncate" onClick={() => setOpen(!open)}>{draft.title || draft.topic}</button>
        <span className="text-xs text-muted-foreground">{draft.model}</span>
        <StatusBadge status={draft.status} />
      </div>
      {open && (
        <div className="mt-2 space-y-2 text-xs">
          {draft.evidence?.length > 0 && <p className="text-muted-foreground">Why this topic: {draft.evidence.map((e) => e.summary).join(" · ")}</p>}
          <Textarea rows={10} className="font-mono text-xs" value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="flex flex-wrap gap-1">
            <Button size="sm" variant="outline" onClick={() => copy(body)}>Copy text</Button>
            <Button size="sm" variant="outline" onClick={() => save.mutate({ body })} disabled={body === draft.body}>Save edits</Button>
            {a.srt && <Button size="sm" variant="outline" onClick={() => copy(a.srt)}>Copy captions (SRT)</Button>}
            {draft.status !== "published" && <Button size="sm" variant="ghost" onClick={() => save.mutate({ status: "published" })}>Mark published</Button>}
            <Button size="sm" variant="ghost" onClick={() => del.mutate()}>Delete</Button>
          </div>
          {a.meta_description && <p><b>Meta description:</b> {a.meta_description}</p>}
          {a.key_takeaway && <p><b>Key takeaway:</b> {a.key_takeaway}</p>}
          {Array.isArray(a.posts) && a.posts.length > 1 && <div><b>Variants:</b>{a.posts.map((p: any, i: number) => <div key={i} className="mt-1 rounded bg-slate-50 dark:bg-slate-800/60 p-2"><div className="text-muted-foreground">{p.channel}</div>{p.text}</div>)}</div>}
          {Array.isArray(a.beats) && <div><b>Shot-by-shot:</b><ul className="list-disc pl-4">{a.beats.map((b: any, i: number) => <li key={i}><span className="text-muted-foreground">{b.t}</span> — say: {b.say} · show: {b.show}</li>)}</ul></div>}
          {Array.isArray(a.shot_list) && <p><b>Shots:</b> {a.shot_list.join(" · ")}</p>}
          {Array.isArray(a.hashtags) && <p><b>Hashtags:</b> {a.hashtags.join(" ")}</p>}
          {a.render_hint && <p className="text-muted-foreground">{a.render_hint}</p>}
          {a.warning && <p className="text-amber-700 dark:text-amber-300">{a.warning}</p>}
          <ErrorBox error={save.error || del.error} />
        </div>
      )}
    </div>
  );
}

/** A link that never widens its container: one line, ellipsis, full URL on hover. */
function PathLink({ url, showHost = false }: { url: string; showHost?: boolean }) {
  const shown = (showHost ? url : url.replace(/^https?:\/\/[^/]+/, "")) || "/";
  return (
    <a className="inline-block max-w-full truncate align-bottom text-primary hover:underline" href={url} target="_blank" rel="noreferrer" title={url}>
      {shown}
    </a>
  );
}

function Suggestions({ s }: { s: Record<string, any> }) {
  const blocks: JSX.Element[] = [];
  const panel = (title: string, body: JSX.Element, key: string) => (
    <div key={key} className="rounded-md border bg-slate-50 dark:bg-slate-800/60 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">{title}</div>{body}
    </div>
  );
  if (Array.isArray(s.topics) && s.topics.length) {
    blocks.push(panel("Pick a topic", <div className="space-y-3">{s.topics.map((t: any, i: number) => (
      <div key={i} className="border-l-2 border-primary/40 pl-3">
        <div className="font-medium">{t.topic}</div>
        <div className="text-xs text-muted-foreground">{t.source}: {t.reason}</div>
        {(t.outline || t.script) && <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">{(t.outline || t.script).map((o: string, n: number) => <li key={n}>{o}</li>)}</ul>}
        {t.page && <a className="text-xs text-primary hover:underline" href={t.page} target="_blank" rel="noreferrer">{t.page}</a>}
      </div>))}</div>, "topics"));
  }
  if (Array.isArray(s.queries) && s.queries.length) {
    blocks.push(panel("Searches to act on", <div className="overflow-auto"><table className="w-full text-xs"><thead className="text-muted-foreground"><tr><th className="text-left py-1">Search</th><th className="text-left">Page</th><th className="text-right">Impr.</th><th className="text-right">Pos.</th><th className="text-left pl-3">New title idea</th></tr></thead>
      <tbody>{s.queries.map((q: any, i: number) => <tr key={i} className="border-t"><td className="py-1 pr-2">{q.query}</td><td className="max-w-[14rem] truncate"><a className="text-primary hover:underline" href={q.page} target="_blank" rel="noreferrer">{q.page?.replace(/^https?:\/\/[^/]+/, "")}</a></td><td className="text-right tabular-nums">{q.impressions}</td><td className="text-right tabular-nums">{q.position}</td><td className="pl-3 text-muted-foreground">{q.title_placeholder ?? "—"}</td></tr>)}</tbody></table></div>, "queries"));
  }
  if (Array.isArray(s.prompts) && s.prompts.length) {
    blocks.push(panel("Questions where AI never mentions you", <div className="space-y-3">{s.prompts.map((p: any, i: number) => (
      <div key={i} className="border-l-2 border-amber-400 pl-3">
        <div className="font-medium">{p.prompt}</div>
        <div className="text-xs text-muted-foreground">{p.providers?.join(", ")}{p.competitors && Object.keys(p.competitors).length ? ` · recommends instead: ${Object.entries(p.competitors).map(([n, r]: any) => `${n} ${fmtPct(r, 0)}`).join(", ")}` : ""}</div>
        {p.outline && <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">{p.outline.map((o: string, n: number) => <li key={n}>{o}</li>)}</ul>}
      </div>))}</div>, "prompts"));
  }
  if (Array.isArray(s.pages) && s.pages.length) {
    blocks.push(panel(`Pages to change (${s.count ?? s.pages.length})`, <ul className="space-y-1 text-xs max-h-64 overflow-auto">{s.pages.map((p: any, i: number) => (
      <li key={i} className="flex gap-2 min-w-0"><PathLink url={String(p.url ?? p.page ?? "")} />
        <span className="text-muted-foreground truncate min-w-0">{p.detail ?? (p.score != null ? `score ${p.score}` : "")}{p.drop_pct ? ` — down ${p.drop_pct}% (${p.clicks_before} → ${p.clicks_now} clicks)` : ""}{p.audits ? ` — ${p.audits.join(", ")}` : ""}</span></li>))}</ul>, "pages"));
  }
  if (Array.isArray(s.threads) && s.threads.length) {
    blocks.push(panel("Conversations to join", <ul className="space-y-1 text-xs">{s.threads.map((t: any, i: number) => (
      <li key={i}><a className="text-primary hover:underline" href={t.url} target="_blank" rel="noreferrer">{t.title} <ExternalLink className="inline h-3 w-3" /></a> <span className="text-muted-foreground">· {t.source} · {String(t.intent).replace(/_/g, " ")}</span></li>))}</ul>, "threads"));
  }
  if (Array.isArray(s.search_phrases) && s.search_phrases.length) {
    blocks.push(panel("Or search these phrases", <div className="flex flex-wrap gap-1 text-xs">{s.search_phrases.map((p: string, i: number) => <code key={i} className="rounded border bg-white dark:bg-slate-900 px-1.5 py-0.5">{p}</code>)}</div>, "phrases"));
  }
  if (Array.isArray(s.ai_cited_domains) && s.ai_cited_domains.length) {
    blocks.push(panel("Sites AI assistants cite for your topics — get mentioned there", <ul className="space-y-1 text-xs">{s.ai_cited_domains.map((d: any, i: number) => (
      <li key={i}><b>{d.domain}</b> <span className="text-muted-foreground">· cited {d.cited}× · {d.why}</span>{d.example && <> · <a className="text-primary hover:underline" href={d.example} target="_blank" rel="noreferrer">example</a></>}</li>))}</ul>, "cited"));
  }
  if (Array.isArray(s.generic_targets) && s.generic_targets.length) {
    blocks.push(panel("Other places worth a link", <ul className="list-disc pl-4 space-y-1 text-xs">{s.generic_targets.map((t: any, i: number) => <li key={i}><b>{t.domain}</b> — <span className="text-muted-foreground">{t.why}</span></li>)}</ul>, "generic"));
  }
  if (Array.isArray(s.checks) && s.checks.length) {
    blocks.push(panel("Walk through these as a new customer", <ol className="space-y-1 text-xs list-none">{s.checks.map((c: any, i: number) => (
      <li key={i} className="flex gap-2"><span className="font-semibold shrink-0 w-24">{c.stage}</span><span>{c.question}</span></li>))}</ol>, "checks"));
  }
  if (Array.isArray(s.coverage) && s.coverage.length) {
    blocks.push(panel("What we found on your site", <ul className="space-y-1 text-xs">{s.coverage.map((c: any, i: number) => (
      <li key={i} className="flex gap-2 items-start min-w-0">
        <span className={cn("shrink-0", c.found ? "text-emerald-600" : "text-amber-600")}>{c.found ? <Check className="inline h-3.5 w-3.5" /> : <Minus className="inline h-3.5 w-3.5" />}</span>
        <span className="min-w-0"><b>{c.area}</b> <span className="text-muted-foreground">({c.stage})</span>{c.found && c.examples?.[0]
          ? <> · <PathLink url={String(c.examples[0])} /></>
          : <span className="text-muted-foreground"> · not found — {c.why}</span>}</span>
      </li>))}</ul>, "coverage"));
  }
  if (Array.isArray(s.missing) && s.missing.length) {
    blocks.push(panel("Pages to create", <ul className="space-y-1 text-xs">{s.missing.map((c: any, i: number) => (
      <li key={i}><b>{c.area}</b> <span className="text-muted-foreground">({c.stage}) — {c.why}</span></li>))}</ul>, "missing"));
  }
  if (Array.isArray(s.found) && s.found.length) {
    blocks.push(panel("Addresses found on your site", <div className="flex flex-wrap gap-1 text-xs">{s.found.map((e: string, i: number) => <code key={i} className="rounded border bg-white dark:bg-slate-900 px-1.5 py-0.5">{e}</code>)}</div>, "found"));
  }
  if (s.suggested) {
    blocks.push(panel("Suggested instead", <div className="flex flex-wrap gap-1 text-xs">{(Array.isArray(s.suggested) ? s.suggested : [s.suggested]).map((e: string, i: number) => <code key={i} className="rounded border bg-white dark:bg-slate-900 px-1.5 py-0.5">{e}</code>)}</div>, "suggested"));
  }
  if (s.detected) {
    blocks.push(panel("What we checked", <ul className="text-xs space-y-0.5">{Object.entries(s.detected).map(([k, v]: any) => (
      <li key={k}><span className={v ? "text-emerald-600" : "text-amber-600"}>{v ? <Check className="inline h-3.5 w-3.5" /> : <Minus className="inline h-3.5 w-3.5" />}</span> {k.replace(/_/g, " ")}{typeof v === "string" ? <span className="text-muted-foreground"> · {v}</span> : ""}</li>))}</ul>, "detected"));
  }
  if (s.outreach_template) blocks.push(panel("Outreach template", <p className="text-xs whitespace-pre-wrap text-muted-foreground">{s.outreach_template}</p>, "outreach"));
  if (Array.isArray(s.changes) && s.changes.length) {
    blocks.push(panel("Competitor changes detected", <ul className="space-y-1 text-xs">{s.changes.map((c: any, i: number) => (
      <li key={i} className="min-w-0"><b>{c.competitor ?? "Competitor"}</b> <PathLink url={String(c.url ?? "")} showHost /> <span className="text-muted-foreground">· <TimeAgo value={c.when} />{c.prices_added?.length ? ` · new prices: ${c.prices_added.join(", ")}` : ""}</span></li>))}</ul>, "changes"));
  }
  if (s.share_of_voice) {
    blocks.push(panel("Share of voice in AI answers", <ul className="text-xs space-y-0.5">{Object.entries(s.share_of_voice).map(([n, r]: any) => <li key={n} className={n === "you" ? "font-semibold" : ""}>{n === "you" ? "You" : n}: {fmtPct(r, 0)}</li>)}</ul>, "sov"));
  }
  if (Array.isArray(s.keywords) && s.keywords.length) blocks.push(panel("Suggested from your own search data", <div className="flex flex-wrap gap-1 text-xs">{s.keywords.map((k: string, i: number) => <code key={i} className="rounded border bg-white dark:bg-slate-900 px-1.5 py-0.5">{k}</code>)}</div>, "kw"));
  if (Array.isArray(s.prompts) && typeof s.prompts[0] === "string") blocks.push(panel("Prompts to add", <ul className="list-disc pl-4 text-xs">{s.prompts.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>, "pr"));
  if (s.page && !s.pages) blocks.push(panel("Page", <div className="text-xs"><PathLink url={String(s.page)} showHost /></div>, "page"));
  if (s.new_in_last_24h != null) blocks.push(panel("New mentions", <p className="text-xs">{s.new_in_last_24h} new in the last 24 hours — <Link className="text-primary hover:underline" to="/brand">open Brand Monitoring</Link></p>, "nm"));
  if (s.note) blocks.push(panel("Note", <p className="text-xs text-muted-foreground">{s.note}</p>, "note"));
  if (s.watched_pages_hint) blocks.push(panel("Tip", <p className="text-xs text-muted-foreground">{s.watched_pages_hint}</p>, "hint"));
  if (s.last_run) blocks.push(panel("Last run", <p className="text-xs text-muted-foreground flex items-center gap-1"><Clock className="h-3 w-3" /> <TimeAgo value={s.last_run.observed_at} fallback="never" /> · {s.last_run.samples ?? 0} samples · you appear in {fmtPct(s.last_run.brand_mention_rate, 0)}</p>, "lr"));
  return blocks.length ? <div className="space-y-2">{blocks}</div> : null;
}
