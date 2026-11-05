import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api, type Job } from "@/lib/api";
import { useJobs } from "@/hooks/useJobs";
import { JobsTable } from "@/components/JobsPanel";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { EmptyState, Loading, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

const STATUSES = ["queued", "running", "succeeded", "failed", "cancelled"];
const JOB_COLUMNS: CsvColumn<Job>[] = [
  { key: "task", label: "Task", value: (row) => row.task_type },
  { key: "status", label: "Status", value: (row) => row.status },
  { key: "progress", label: "Progress", value: (row) => row.progress },
  { key: "message", label: "Progress message", value: (row) => row.progress_message },
  { key: "trigger", label: "Triggered by", value: (row) => row.triggered_by },
  { key: "created", label: "Created", value: (row) => row.created_at },
  { key: "error", label: "Error", value: (row) => row.error },
  { key: "result", label: "Result", value: (row) => row.result ? JSON.stringify(row.result) : "" },
];

/** Every background job for the project, in one place. Each page used to carry its own filtered copy of this. */
export function JobsPage() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const { data: tasks } = useQuery({ queryKey: ["tasks"], queryFn: () => api.get<Record<string, string>>("/tasks"), staleTime: Infinity });
  const { data: jobs, isLoading } = useJobs({ limit: 200 });

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (jobs ?? []).filter((j) => {
      if (type && j.task_type !== type) return false;
      if (status && j.status !== status) return false;
      if (!needle) return true;
      // Search the task name, its description, who asked for it and whatever it last reported.
      return [j.task_type, tasks?.[j.task_type], j.triggered_by, j.progress_message, j.error]
        .some((f) => f?.toLowerCase().includes(needle));
    });
  }, [jobs, tasks, q, type, status]);

  const paged = usePaged(filtered);
  const used = useMemo(() => [...new Set((jobs ?? []).map((j) => j.task_type))].sort(), [jobs]);
  const filtering = !!(q || type || status);

  return (
    <div>
      <PageHeader title="Jobs" info="Every background job this project has run: crawls, syncs, AI sampling, content writing and plan rebuilds. Running jobs refresh automatically." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input className="w-64" placeholder="Search name, trigger or error…" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-64" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All types</option>
          {used.map((t) => <option key={t} value={t} title={tasks?.[t]}>{t}</option>)}
        </Select>
        <Select className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        {filtering && <Button size="sm" variant="outline" onClick={() => { setQ(""); setType(""); setStatus(""); }}><X className="h-3 w-3" /> Clear</Button>}
        <span className="text-xs text-muted-foreground">{filtered.length} of {jobs?.length ?? 0}</span>
        <div className="ml-auto"><CsvExportButton filename="jobs.csv" rows={filtered} columns={JOB_COLUMNS} /></div>
      </div>
      {isLoading ? <Loading />
        : !jobs?.length ? <EmptyState title="No jobs yet">Jobs appear here as soon as you run a crawl, a sync or an AI visibility run.</EmptyState>
        : !filtered.length ? <EmptyState title="Nothing matches those filters" />
        : <><JobsTable jobs={paged.items as Job[]} /><Pagination state={paged} label="jobs" /></>}
    </div>
  );
}
