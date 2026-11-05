import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface CurrentUser { id: string; email: string; name: string | null; role: string; must_change_password: boolean }

interface AppState {
  token: string | null;
  user: CurrentUser | null;
  projectId: string | null;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
  setToken: (t: string | null) => void;
  setUser: (u: CurrentUser | null) => void;
  setProjectId: (id: string | null) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      projectId: null,
      theme: typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light",
      setTheme: (theme) => set({ theme }),
      setToken: (token) => set({ token, ...(token ? {} : { user: null }) }),
      setUser: (user) => set({ user }),
      setProjectId: (projectId) => set({ projectId }),
    }),
    { name: "growos-app" },
  ),
);
