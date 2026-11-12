import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import { api } from "@/lib/api";
import { useProjectId } from "@/hooks/useProject";
import { useWorkerActivity } from "@/hooks/useJobs";
import { useProjectAccess } from "@/hooks/useProjectAccess";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { JobWorkflow, type CatalogItem } from "@/components/job-workflow";

function JobPicker({ pid, runDisabled, jobsRunning, onDone }: { pid: string; runDisabled: boolean; jobsRunning: boolean; onDone: () => void }) {
  const qc = useQueryClient();
  // Only store explicit choices. A background catalog refresh must not undo the user's selection.
  const [choices, setChoices] = useState<Record<string, boolean>>({});
  const { data: catalog, isPending, isError, refetch } = useQuery({
    queryKey: ["job-catalog", pid],
    queryFn: () => api.get<CatalogItem[]>(`/projects/${pid}/jobs/catalog`),
    retry: false,
  });
  const run = useMutation({
    mutationFn: (task_types: string[]) => api.post(`/projects/${pid}/jobs/run-selected`, { task_types }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs", pid] }); onDone(); },
  });
  const items = catalog ?? [];
  const checked = (job: CatalogItem) => choices[job.task_type] ?? (job.default && job.cost === "free");
  const selected = items.filter(checked);
  const paidCount = selected.filter((job) => job.cost === "paid").length;
  const select = (mode: "all" | "free" | "none") => setChoices(Object.fromEntries(
    items.map((job) => [job.task_type, mode === "all" || (mode === "free" && job.cost === "free")]),
  ));

  return <>
    <hr className="my-4 shrink-0 border-t" />
    <div className="min-h-0 max-h-[55vh] overflow-y-auto">
      {isPending ? <p role="status" className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading available jobs…</p>
        : isError ? <div role="alert" className="py-8 text-center text-sm"><p>Could not load available jobs.</p><Button className="mt-3" variant="outline" onClick={() => refetch()}>Try again</Button></div>
        : items.length ? <JobWorkflow items={items} checked={checked} disabled={run.isPending}
          onChange={(task, value) => setChoices((current) => ({ ...current, [task]: value }))} />
        : <p className="py-12 text-center text-sm text-muted-foreground">No runnable jobs. Add a website or connect providers under Integrations.</p>}
    </div>
    <hr className="my-4 shrink-0 border-t" />
    {run.isError && <p role="alert" className="mt-3 shrink-0 text-sm text-destructive">Could not start jobs. {run.error.message}</p>}
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex shrink-0 gap-1">
          <Button variant="ghost" size="sm" disabled={!items.length || run.isPending} onClick={() => select("free")}>Free only</Button>
          <Button variant="ghost" size="sm" disabled={!items.length || run.isPending} onClick={() => select("all")}>Select all</Button>
          <Button variant="ghost" size="sm" disabled={!items.length || run.isPending} onClick={() => select("none")}>Clear all</Button>
        </div>
        <div aria-live="polite" className="text-sm">
          <span className="font-medium">{selected.length} selected</span>
          <span className="text-muted-foreground"> · {paidCount} paid</span>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" onClick={onDone}>Cancel</Button>
        <Button onClick={() => run.mutate(selected.map((job) => job.task_type))} disabled={runDisabled || !selected.length || run.isPending || isError}>
          {jobsRunning || run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {jobsRunning ? "Running..." : run.isPending ? "Starting…" : `Run ${selected.length} job${selected.length === 1 ? "" : "s"}`}
        </Button>
      </div>
    </div>
  </>;
}

/** A fresh picker on each open keeps paid jobs opt-in, including after a previous run. */
export function RunJobsButton() {
  const pid = useProjectId();
  const { canEdit } = useProjectAccess();
  const [open, setOpen] = useState(false);
  const activity = useWorkerActivity(canEdit);
  const activeCount = activity.data?.active ?? 0;
  if (!canEdit) return null;
  return <Dialog open={open} onOpenChange={(nextOpen) => { setOpen(nextOpen); if (nextOpen) void activity.refetch(); }}>
    <DialogTrigger asChild><Button size="sm" variant="ghost" className="bg-transparent dark:bg-transparent" aria-live="polite"><Play aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />{activeCount > 0 ? `Running (${activeCount})` : "Run"}</Button></DialogTrigger>
    <DialogContent className="flex w-[calc(100%-1.5rem)] max-w-6xl flex-col overflow-hidden p-4 sm:p-6" bodyClassName="mt-0 flex min-h-0 flex-col" title="Run jobs"
      description="Select jobs to run." inlineDescription>
      {open && <JobPicker pid={pid} jobsRunning={activeCount > 0} runDisabled={activeCount > 0 || activity.isPending || activity.isError} onDone={() => setOpen(false)} />}
    </DialogContent>
  </Dialog>;
}
