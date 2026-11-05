import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bell } from "lucide-react";
import { api } from "@/lib/api";
import { useAppStore } from "@/store/app";
import { cn } from "@/lib/utils";
import { TimeAgo } from "@/components/ui/time";

interface Notif { id: string; kind: string; severity: string; title: string; body: string | null; link: string | null; created_at: string; read_at: string | null }
interface Feed { unread: number; items: Notif[] }

const SEV: Record<string, string> = {
  info: "border-l-sky-400", success: "border-l-emerald-400", warning: "border-l-amber-400", critical: "border-l-red-500",
};

/**
 * `placement` decides which way the panel opens vertically — it sits at the bottom of the sidebar and at the top on mobile.
 * `align` anchors the panel horizontally: "left" (default) extends rightward, "right" extends leftward so a bell near the
 * right edge of the screen (e.g. the mobile top bar) doesn't overflow off-window.
 */
export function NotificationBell({ placement = "down", align = "left" }: { placement?: "up" | "down"; align?: "left" | "right" } = {}) {
  const user = useAppStore((s) => s.user);
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const { data } = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<Feed>("/notifications?limit=30"), enabled: !!user, refetchInterval: 60000 });
  const readAll = useMutation({ mutationFn: () => api.post("/notifications/read-all"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const readOne = useMutation({ mutationFn: (id: string) => api.post(`/notifications/${id}/read`), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  useEffect(() => {
    if (!open) return;
    const closeOnFocusOutside = (event: FocusEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("focusin", closeOnFocusOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("focusin", closeOnFocusOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);
  if (!user) return null;
  const unread = data?.unread ?? 0;
  return (
    <div ref={root} className="relative">
      <button className="relative rounded-md p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800" title="Notifications" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}>
        <Bell className="h-4 w-4" />
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div role="dialog" aria-label="Notifications" className={cn("absolute z-50 w-80 max-w-[calc(100vw-2rem)] max-h-[70vh] overflow-auto rounded-lg border bg-white dark:bg-slate-900 shadow-lg",
            align === "right" ? "right-0" : "left-0",
            placement === "up" ? "bottom-full mb-2" : "top-full mt-2")}>
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-sm font-medium">Notifications</span>
              {unread > 0 && <button className="text-xs text-primary hover:underline" onClick={() => readAll.mutate()}>Mark all read</button>}
            </div>
            {!data?.items.length ? (
              <div className="px-3 py-6 text-center text-sm text-muted-foreground">Nothing yet. Weekly summaries and alerts show up here.</div>
            ) : data.items.map((n) => {
              const inner = (
                <div className={cn("border-l-2 px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/60", SEV[n.severity] ?? SEV.info, !n.read_at && "bg-slate-50/60 dark:bg-slate-800/30")}>
                  <div className="flex items-start justify-between gap-2">
                    <span className={cn("text-sm", !n.read_at && "font-medium")}>{n.title}</span>
                    {!n.read_at && <button className="shrink-0 text-[10px] text-muted-foreground hover:text-foreground" onClick={(e) => { e.preventDefault(); readOne.mutate(n.id); }}>mark read</button>}
                  </div>
                  {n.body && <div className="mt-0.5 text-xs text-muted-foreground line-clamp-3 whitespace-pre-line">{n.body}</div>}
                  <div className="mt-1 text-[10px] text-muted-foreground"><TimeAgo value={n.created_at} /></div>
                </div>
              );
              return n.link
                ? <Link key={n.id} to={n.link} onClick={() => { setOpen(false); if (!n.read_at) readOne.mutate(n.id); }}>{inner}</Link>
                : <div key={n.id}>{inner}</div>;
            })}
          </div>
        </>
      )}
    </div>
  );
}
