import { useQuery } from "@tanstack/react-query";
import { api, type Competitor, type Domain, type Project } from "@/lib/api";
import { useAppStore } from "@/store/app";

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
}

export function useProjectId(): string {
  const id = useAppStore((s) => s.projectId);
  return id ?? "";
}

export function useProject() {
  const id = useProjectId();
  return useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/projects/${id}`), enabled: !!id });
}

export function useDomains() {
  const id = useProjectId();
  return useQuery({ queryKey: ["domains", id], queryFn: () => api.get<Domain[]>(`/projects/${id}/domains`), enabled: !!id });
}

export function useCompetitors() {
  const id = useProjectId();
  return useQuery({ queryKey: ["competitors", id], queryFn: () => api.get<Competitor[]>(`/projects/${id}/competitors`), enabled: !!id });
}
