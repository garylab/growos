import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { api, type Job, type JobLog } from "@/lib/api";
import { useJobActions, useJobs } from "@/hooks/useJobs";
import { Table, TBody, TD, TH, THead, TR } from "./ui/table";
import { StatusBadge } from "./ui/badge";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";
import { TimeAgo } from "@/components/ui/time";
import { EmptyState } from "./ui/misc";

/** Fetches and renders the project's jobs. Used for the small "recent jobs" card. */
export function JobsPanel({ task_type, limit = 15, compact = false }: { task_type?: string; limit?: number; compact?: boolean }) {
  const { data: jobs } = useJobs({ task_type, limit });
  if (!jobs?.length) return <EmptyState title="No jobs yet">Trigger a collection job to see progress and logs here.</EmptyState>;
  return <JobsTable jobs={jobs} compact={compact} />;
}

/** The table itself, over a list you already have — so the Jobs page can filter before rendering. */
export function JobsTable({ jobs, compact = false }: { jobs: Job[]; compact?: boolean }) {
  const { cancel, retry } = useJobActions();
  const [open, setOpen] = useState<Job | null>(null);
  return (
    <>
      <Table containerClassName="rounded-none border-0">
        <THead>
          <TR>
            <TH>Task</TH>
            <TH>Status</TH>
            <TH className="w-48">Progress</TH>
            {!compact && <TH>Created</TH>}
            <TH>Result / error</TH>
            <TH />
          </TR>
        </THead>
        <TBody>
          {jobs.map((j) => (
            <TR key={j.id}>
              <TD className="font-medium">{j.task_type}<div className="text-xs text-muted-foreground">{j.triggered_by} · attempt {j.attempts}/{j.max_attempts}</div></TD>
              <TD><StatusBadge status={j.status} /></TD>
              <TD>
                <div className="h-2 w-full rounded bg-slate-100 dark:bg-slate-800 overflow-hidden"><div className="h-2 bg-primary transition-all" style={{ width: `${j.progress}%` }} /></div>
                <div className="text-xs text-muted-foreground truncate max-w-[12rem]" title={j.progress_message ?? ""}>{j.progress_message ?? `${j.progress}%`}</div>
              </TD>
              {!compact && <TD className="text-xs text-muted-foreground whitespace-nowrap"><TimeAgo value={j.created_at} /></TD>}
              <TD className="text-xs max-w-md">
                {j.error ? <span className="text-red-700 dark:text-red-300">{j.error.slice(0, 200)}</span> : j.result ? <code className="text-muted-foreground">{JSON.stringify(j.result).slice(0, 160)}</code> : "—"}
              </TD>
              <TD className="whitespace-nowrap text-right">
                <Button size="sm" variant="ghost" onClick={() => setOpen(j)}>Logs</Button>
                {(j.status === "queued" || j.status === "running") && <Button size="sm" variant="ghost" onClick={() => cancel.mutate(j.id)}>Cancel</Button>}
                {(j.status === "failed" || j.status === "cancelled") && <Button size="sm" variant="ghost" onClick={() => retry.mutate(j.id)}>Retry</Button>}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        {open && <DialogContent title={`Job ${open.task_type}`} description={open.id}><JobLogs jobId={open.id} /></DialogContent>}
      </Dialog>
    </>
  );
}

function JobLogs({ jobId }: { jobId: string }) {
  const { data } = useQuery({ queryKey: ["job-logs", jobId], queryFn: () => api.get<JobLog[]>(`/jobs/${jobId}/logs`), refetchInterval: 3000 });
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const logText = (data ?? []).map((l) => `${new Date(l.ts).toLocaleTimeString()} [${l.level}] ${l.message}`).join("\n");
  const copyLogs = async () => {
    try {
      await navigator.clipboard.writeText(logText);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("failed");
    }
  };
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-2">
        {copyState === "failed" && <span className="text-xs text-red-600 dark:text-red-300">Could not copy</span>}
        <Button size="icon" variant="outline" onClick={copyLogs} disabled={!logText}
          className="h-8 w-8" aria-label={copyState === "copied" ? "Logs copied" : "Copy logs"}
          title={copyState === "copied" ? "Copied" : "Copy logs"}>
          {copyState === "copied" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </Button>
      </div>
      <pre className="max-h-96 overflow-auto rounded bg-slate-950 dark:bg-black p-3 text-xs text-slate-100">
        {logText || "No logs yet"}
      </pre>
    </div>
  );
}
