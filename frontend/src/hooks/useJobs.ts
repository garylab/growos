import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Job } from "@/lib/api";
import { useProjectId } from "./useProject";

export function useWorkerActivity(enabled: boolean) {
  const id = useProjectId();
  return useQuery({
    queryKey: ["jobs", id, "activity"],
    queryFn: () => api.get<{ active: number }>(`/projects/${id}/jobs/activity`),
    enabled: !!id && enabled,
    refetchInterval: (q) => q.state.data?.active ? 3000 : 15000,
  });
}

export function useJobs(opts?: { task_type?: string; limit?: number }) {
  const id = useProjectId();
  const qs = new URLSearchParams();
  if (opts?.task_type) qs.set("task_type", opts.task_type);
  qs.set("limit", String(opts?.limit ?? 30));
  return useQuery({
    queryKey: ["jobs", id, opts?.task_type ?? "all", opts?.limit ?? 30],
    queryFn: () => api.get<Job[]>(`/projects/${id}/jobs?${qs}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running") ? 3000 : 15000),
  });
}

export function useEnqueue() {
  const id = useProjectId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { task_type: string; params?: Record<string, unknown>; priority?: number }) => api.post<Job>(`/projects/${id}/jobs`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs", id] }),
  });
}

export function useJobActions() {
  const qc = useQueryClient();
  const cancel = useMutation({ mutationFn: (jobId: string) => api.post<Job>(`/jobs/${jobId}/cancel`), onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }) });
  const retry = useMutation({ mutationFn: (jobId: string) => api.post<Job>(`/jobs/${jobId}/retry`), onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }) });
  return { cancel, retry };
}
