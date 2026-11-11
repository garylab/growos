import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { api } from "@/lib/api";
import { useProjectId } from "@/hooks/useProject";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";

interface CatalogItem { task_type: string; label: string; cost: "free" | "paid"; scope: string; default: boolean }

/** The single place to trigger background jobs. Lives on Overview; replaces the per-page Re-run buttons.
 *  Free jobs are preselected; paid ones (credits / AI tokens) start off so a click never spends by surprise. */
export function RunJobsButton() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const { data: catalog } = useQuery({
    queryKey: ["job-catalog", pid],
    queryFn: () => api.get<CatalogItem[]>(`/projects/${pid}/jobs/catalog`),
    enabled: open,
  });
  useEffect(() => {
    if (catalog) setSel(Object.fromEntries(catalog.map((j) => [j.task_type, j.default])));
  }, [catalog]);
  const run = useMutation({
    mutationFn: (task_types: string[]) => api.post(`/projects/${pid}/jobs/run-selected`, { task_types }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs", pid] }); setOpen(false); },
  });
  const items = catalog ?? [];
  const free = items.filter((j) => j.cost === "free");
  const paid = items.filter((j) => j.cost === "paid");
  const selected = Object.entries(sel).filter(([, v]) => v).map(([k]) => k);
  const setAll = (v: boolean) => setSel(Object.fromEntries(items.map((j) => [j.task_type, v])));
  const row = (j: CatalogItem) => (
    <label key={j.task_type} className="flex items-center gap-2 py-1.5 text-sm cursor-pointer">
      <input type="checkbox" className="h-4 w-4" checked={!!sel[j.task_type]}
             onChange={(e) => setSel((s) => ({ ...s, [j.task_type]: e.target.checked }))} />
      <span>{j.label}</span>
    </label>
  );
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button><Play className="h-4 w-4" /> Run jobs</Button></DialogTrigger>
      <DialogContent title="Run jobs"
        description="Pick what to refresh. Free jobs use no provider credits; paid jobs consume API credits or AI tokens.">
        <div className="mb-2 flex gap-3 text-xs">
          <button className="text-primary underline" onClick={() => setAll(true)}>Select all</button>
          <button className="text-primary underline" onClick={() => setAll(false)}>Clear all</button>
        </div>
        <div className="max-h-[50vh] overflow-y-auto pr-1">
          <div className="mb-1 mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Free</div>
          {free.map(row)}
          {paid.length > 0 && (
            <>
              <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Paid — uses credits / AI tokens</div>
              {paid.map(row)}
            </>
          )}
          {!items.length && <p className="py-4 text-sm text-muted-foreground">No runnable jobs — connect providers under Integrations first.</p>}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={() => run.mutate(selected)} disabled={!selected.length || run.isPending}>
            Run {selected.length} job{selected.length === 1 ? "" : "s"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
