import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Keyword } from "@/lib/api";
import { useProject } from "@/hooks/useProject";
import { useEnqueue } from "@/hooks/useJobs";
import { Button } from "@/components/ui/button";
import { CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Select, Textarea } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";
import { fmtInt, fmtNum } from "@/lib/utils";

interface KeywordMetrics {
  available: boolean; provider?: string; observed_on?: string; reason?: string; connected_provider?: string | null;
  totals?: { keywords: number; total_volume: number; avg_difficulty: number | null; unpriced: number };
  keywords?: { id: string; text: string; importance: number; search_volume: number | null; difficulty: number | null; cpc: number | null; intent: string | null; volume_change: number | null }[];
}

export function TargetKeywordsTab({ pid }: { pid: string }) {
  const qc = useQueryClient();
  const { data: project } = useProject();
  const { data: keywords } = useQuery({ queryKey: ["keywords", pid], queryFn: () => api.get<Keyword[]>(`/projects/${pid}/keywords`) });
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ text: "", importance: 3 });
  const add = useMutation({
    mutationFn: () => api.post(`/projects/${pid}/keywords`, form.text.split("\n").map((text) => text.trim()).filter(Boolean)
      .map((text) => ({ text, importance: form.importance, country: project?.default_country, language: project?.default_language }))),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["keywords", pid] }); setForm({ text: "", importance: 3 }); setAddOpen(false); },
  });
  const remove = useMutation({ mutationFn: (id: string) => api.delete(`/projects/${pid}/keywords/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["keywords", pid] }) });
  const promote = useMutation({ mutationFn: (id: string) => api.patch(`/projects/${pid}/keywords/${id}`, { is_target: true, importance: 3 }), onSuccess: () => qc.invalidateQueries({ queryKey: ["keywords", pid] }) });
  const enqueue = useEnqueue();
  const targets = (keywords ?? []).filter((keyword) => keyword.is_target);
  const candidates = (keywords ?? []).filter((keyword) => !keyword.is_target);
  return (
    <div className="grid items-stretch gap-6 lg:grid-cols-2">
      <section className="flex h-full min-w-0 flex-col">
        <div className="mb-3 flex items-center justify-between gap-3">
        <CardTitle info="Keywords you want to be found for. Volume, difficulty and CPC come from the connected keyword provider and are estimates, not measurements. Only target keywords are priced and rank-checked.">Target</CardTitle>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setAddOpen(true)}>Add</Button>
        </div>
        </div>
        <div className="flex flex-1 flex-col space-y-3">
        <KeywordTable pid={pid} keywords={targets} onDelete={(id) => remove.mutate(id)} />
        </div>
      </section>
      <section className="flex h-full min-w-0 flex-col">
        <div className="mb-3 flex items-center justify-between gap-3">
        <CardTitle info="Ideas found through keyword discovery. They are not tracked or priced until promoted.">Inspiration</CardTitle>
        <Button size="sm" variant="outline" onClick={() => enqueue.mutate({ task_type: "discover_keywords", params: {} })} disabled={enqueue.isPending} title="Expand your target keywords into ideas using Google autocomplete, People Also Ask and Trends.">Discover keywords</Button>
        </div>
        <div className="flex-1">
        {candidates.length ? <CandidateTable keywords={candidates} onPromote={(id) => promote.mutate(id)} onDelete={(id) => remove.mutate(id)} busy={promote.isPending} /> : <p className="text-sm text-muted-foreground">No keyword inspiration yet.</p>}
        </div>
      </section>
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent title="Add target keywords" description="Add one keyword per line and choose their priority." className="max-w-lg">
          <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
            <Textarea rows={5} autoFocus placeholder="One keyword per line" value={form.text} onChange={(event) => setForm({ ...form, text: event.target.value })} />
            <div className="flex items-center justify-between gap-3">
              <Select className="w-40" value={form.importance} onChange={(event) => setForm({ ...form, importance: Number(event.target.value) })}>{[1, 2, 3, 4, 5].map((importance) => <option key={importance} value={importance}>Priority {importance}</option>)}</Select>
              <Button type="submit" disabled={add.isPending || !form.text.trim()}>Add keywords</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CandidateTable({ keywords, onPromote, onDelete, busy }: { keywords: Keyword[]; onPromote: (id: string) => void; onDelete: (id: string) => void; busy: boolean }) {
  const [filter, setFilter] = useState("");
  const rows = keywords.filter((row) => !filter || `${row.text} ${row.source ?? ""} ${(row.tags ?? []).join(" ")}`.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows, 25);
  const columns: CsvColumn<Keyword>[] = [
    { key: "keyword", label: "Keyword", value: (row) => row.text }, { key: "source", label: "Found via", value: (row) => row.source },
    { key: "tags", label: "Tags", value: (row) => (row.tags ?? []).join(", ") }, { key: "country", label: "Country", value: (row) => row.country },
    { key: "language", label: "Language", value: (row) => row.language },
  ];
  return <>
    <div className="mb-3 flex gap-2"><SearchBox className="w-56 max-w-full" placeholder="Filter inspiration…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="keyword-inspiration.csv" rows={rows} columns={columns} /></div></div>
    <Table><THead><TR><TH>Keyword</TH><TH>Found via</TH><TH>From seed</TH><TH /></TR></THead><TBody>{paged.items.map((keyword) => <TR key={keyword.id}>
      <TD className="text-sm">{keyword.text}</TD><TD className="text-xs text-muted-foreground">{(keyword.source ?? "").replace(/^serpapi:/, "").replace(/\+/g, " + ")}</TD>
      <TD className="text-xs text-muted-foreground">{(keyword.tags ?? []).find((tag) => tag.startsWith("seed:"))?.slice(5) ?? "—"}</TD>
      <TD className="text-right whitespace-nowrap"><Button size="sm" variant="outline" disabled={busy} onClick={() => onPromote(keyword.id)}>Make target</Button><Button size="sm" variant="ghost" onClick={() => onDelete(keyword.id)}>Discard</Button></TD>
    </TR>)}</TBody></Table><Pagination state={paged} label="candidates" />
  </>;
}

function KeywordTable({ pid, keywords, onDelete }: { pid: string; keywords: Keyword[]; onDelete: (id: string) => void }) {
  const [filter, setFilter] = useState("");
  const { data } = useQuery({ queryKey: ["keyword-metrics", pid], queryFn: () => api.get<KeywordMetrics>(`/projects/${pid}/seo/keyword-metrics`), enabled: !!pid });
  const priced = new Map((data?.keywords ?? []).map((keyword) => [keyword.id, keyword]));
  const rows = keywords.map((keyword) => ({ ...keyword, m: priced.get(keyword.id) })).filter((row) => !filter || `${row.text} ${row.m?.intent ?? ""} ${row.country} ${row.language}`.toLowerCase().includes(filter.toLowerCase()));
  const paged = usePaged(rows, 25);
  const columns: CsvColumn<(typeof rows)[number]>[] = [
    { key: "keyword", label: "Keyword", value: (row) => row.text }, { key: "volume", label: "Volume", value: (row) => row.m?.search_volume },
    { key: "difficulty", label: "Difficulty", value: (row) => row.m?.difficulty }, { key: "cpc", label: "CPC", value: (row) => row.m?.cpc },
    { key: "intent", label: "Intent", value: (row) => row.m?.intent }, { key: "priority", label: "Priority", value: (row) => row.importance },
  ];
  if (!keywords.length) return <p className="text-sm text-muted-foreground">No target keywords yet.</p>;
  return <>
    {data?.available ? <p className="text-xs text-muted-foreground">{data.provider} · {data.observed_on} · {fmtInt(data.totals!.total_volume)} searches/mo across {data.totals!.keywords} priced keyword(s){data.totals!.unpriced > 0 && ` · ${data.totals!.unpriced} not priced yet`}</p>
      : !data?.connected_provider && <p className="text-xs text-muted-foreground">Connect a provider under Integrations → Keyword & SERP data to see volume, difficulty and CPC.</p>}
    <div className="mb-3 flex gap-2"><SearchBox className="w-56 max-w-full" placeholder="Filter keywords…" value={filter} onSearch={setFilter} /><div className="ml-auto"><CsvExportButton filename="target-keywords.csv" rows={rows} columns={columns} /></div></div>
    <Table><THead><TR><TH>Keyword</TH><TH className="text-right">Volume</TH><TH className="text-right">Difficulty</TH><TH className="text-right">CPC</TH><TH>Intent</TH><TH className="text-right">Priority</TH><TH /></TR></THead><TBody>{paged.items.map((keyword) => <TR key={keyword.id}>
      <TD className="text-sm">{keyword.text}<div className="text-xs text-muted-foreground">{keyword.language}-{keyword.country}</div></TD>
      <TD className="text-right tabular-nums">{keyword.m?.search_volume != null ? fmtInt(keyword.m.search_volume) : <span className="text-xs text-muted-foreground">—</span>}{!!keyword.m?.volume_change && <div className={`text-xs ${keyword.m.volume_change > 0 ? "text-emerald-600" : "text-red-600"}`}>{keyword.m.volume_change > 0 ? "+" : ""}{fmtInt(keyword.m.volume_change)}</div>}</TD>
      <TD className="text-right tabular-nums">{keyword.m?.difficulty != null ? fmtNum(keyword.m.difficulty, 0) : <span className="text-xs text-muted-foreground">—</span>}</TD>
      <TD className="text-right tabular-nums text-xs">{keyword.m?.cpc != null ? `$${keyword.m.cpc.toFixed(2)}` : <span className="text-muted-foreground">—</span>}</TD>
      <TD className="text-xs text-muted-foreground">{keyword.m?.intent ?? "—"}</TD><TD className="text-right text-xs text-muted-foreground">{keyword.importance}/5</TD>
      <TD className="text-right"><Button size="sm" variant="ghost" onClick={() => onDelete(keyword.id)}>Remove</Button></TD>
    </TR>)}</TBody></Table><Pagination state={paged} label="keywords" />
  </>;
}
