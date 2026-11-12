import { useQuery } from "@tanstack/react-query";
import { api, type Member } from "@/lib/api";
import { useAppStore } from "@/store/app";
import { useProjectId } from "./useProject";

export const ADMIN_PAGES = new Set(["/jobs", "/integrations", "/settings"]);

/** Brand permissions follow the current route, including when switching brands. */
export function useProjectAccess() {
  const id = useProjectId();
  const user = useAppStore((s) => s.user);
  const systemAdmin = !user || user.role === "admin";
  const members = useQuery({
    queryKey: ["members", id],
    queryFn: () => api.get<Member[]>(`/projects/${id}/members`),
    enabled: !!id && !systemAdmin,
  });
  const role = systemAdmin ? "owner" : members.data?.find((m) => m.user_id === user.id)?.role;
  return {
    canManage: !!id && role === "owner",
    canEdit: !!id && (role === "owner" || role === "editor"),
    isLoading: !!id && !systemAdmin && members.isPending,
  };
}
