import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { useAppStore } from "@/store/app";
import { ChangePassword, Login } from "@/pages/Login";
import { TeamPage } from "@/pages/Team";
import { Setup } from "@/pages/Setup";
import { Overview } from "@/pages/Overview";
import { PlanPage } from "@/pages/Plan";
import { SeoPage } from "@/pages/Seo";
import { AIVisibilityPage } from "@/pages/AIVisibility";
import { BrandPage } from "@/pages/Brand";
import { CompetitorsPage } from "@/pages/Competitors";
import { ActionsPage } from "@/pages/Actions";
import { IntegrationsPage } from "@/pages/Integrations";
import { SettingsPage } from "@/pages/Settings";
import { JobsPage } from "@/pages/Jobs";
import { ProfilePage } from "@/pages/Profile";
import { useProjects } from "@/hooks/useProject";
import { Loading } from "@/components/ui/misc";
import { useEffect, useState } from "react";

/** Reads the one-time token (or error) that the "Sign in with Google" callback leaves in the URL fragment. */
function useGoogleAuthRedirect() {
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!window.location.hash.startsWith("#gauth")) return;
    const params = new URLSearchParams(window.location.hash.slice(1));
    const token = params.get("gauth");
    const err = params.get("gauth_error");
    history.replaceState(null, "", window.location.pathname + window.location.search);
    if (token) {
      useAppStore.getState().setToken(token);
      fetch("/api/auth/me", { headers: { "X-Auth-Token": token } })
        .then((r) => (r.ok ? r.json() : null))
        .then((u) => u && useAppStore.getState().setUser(u))
        .catch(() => {});
    } else if (err) {
      setError(err);
    }
  }, []);
  return error;
}

export default function App() {
  const token = useAppStore((s) => s.token);
  const theme = useAppStore((s) => s.theme);
  useEffect(() => { document.documentElement.classList.toggle("dark", theme === "dark"); }, [theme]);
  const user = useAppStore((s) => s.user);
  const googleError = useGoogleAuthRedirect();
  const { data: meta, isLoading } = useQuery({ queryKey: ["meta"], queryFn: async () => (await fetch("/api/meta")).json() as Promise<{ auth_required: boolean }> });
  if (isLoading) return <Loading />;
  if (meta?.auth_required && !token) return <Login googleError={googleError} />;
  if (user?.must_change_password) return <ChangePassword />;
  return <Gate />;
}

function Gate() {
  const { data: projects, isLoading, error } = useProjects();
  const projectId = useAppStore((s) => s.projectId);
  const setProjectId = useAppStore((s) => s.setProjectId);
  useEffect(() => {
    if (projects && projects.length && (!projectId || !projects.some((p) => p.id === projectId))) setProjectId(projects[0].id);
  }, [projects, projectId, setProjectId]);
  if (isLoading) return <Loading />;
  if (error) return <div className="p-8 text-red-700 dark:text-red-300">Cannot reach the API: {(error as Error).message}</div>;
  if (!projects?.length) return <Routes><Route path="*" element={<Setup />} /></Routes>;
  return (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route element={<AppShell />}>
        {/* Overview is the home page. Keep the old URL as a redirect for existing bookmarks. */}
        <Route index element={<Overview />} />
        <Route path="/overview" element={<Navigate to="/" replace />} />
        <Route path="/plan" element={<PlanPage />} />
        <Route path="/scorecard" element={<Navigate to="/" replace />} />
        <Route path="/seo/:tab?/:view?" element={<SeoPage />} />
        <Route path="/geo/:tab?" element={<AIVisibilityPage />} />
        <Route path="/brand/:tab?" element={<BrandPage />} />
        <Route path="/competitors/:tab?" element={<CompetitorsPage />} />
        <Route path="/actions" element={<ActionsPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/integrations" element={<IntegrationsPage />} />
        <Route path="/team" element={<TeamPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
