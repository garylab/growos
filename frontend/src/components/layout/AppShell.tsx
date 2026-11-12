import { Fragment, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, Home, LogOut, Menu, Moon, Sun, X } from "lucide-react";
import { NAV, firstTab, sectionTab, tabHref, type NavItem } from "@/lib/nav";
import { api } from "@/lib/api";
import { useProjects } from "@/hooks/useProject";
import { useAppStore } from "@/store/app";
import { RunJobsButton } from "@/components/run-jobs";
import { cn } from "@/lib/utils";
import { Select } from "../ui/input";
import { NotificationBell } from "../NotificationBell";
import { UserMenu } from "../UserMenu";

const ROW = "flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-800";
const ACTIVE = "bg-slate-100 dark:bg-slate-800 font-medium text-primary";

/** One menu entry. Sections with sub-pages fold open in place; clicking anywhere on the row folds them. */
function NavEntry({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const current = sectionTab(pathname, item);
  const inSection = current !== null;
  const [open, setOpen] = useState(inSection);
  useEffect(() => { if (inSection) setOpen(true); }, [inSection]);

  const tabs = item.tabs;
  if (!tabs?.length) {
    return (
      <NavLink to={item.to} end={item.end} onClick={onNavigate} className={({ isActive }) => cn(ROW, isActive && ACTIVE)}>
        <item.icon className="h-4 w-4 shrink-0" /> <span className="truncate">{item.label}</span>
      </NavLink>
    );
  }
  // Opening a section you are not in takes you to its first sub-page; otherwise the row only folds and unfolds.
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !inSection) {
      navigate(tabHref(item, firstTab(item)));
      onNavigate();
    }
  };
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={toggle} className={cn(ROW, "w-full pr-1.5 text-left", inSection && ACTIVE)}>
        <item.icon className="h-4 w-4 shrink-0" /> <span className="min-w-0 flex-1 truncate">{item.label}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", !open && "-rotate-90")} />
      </button>
      {open && (
        <div className="mt-0.5 ml-5 space-y-0.5 border-l pl-2">
          {tabs.filter((t) => !t.hidden).map((t) => (
            <Link key={t.id} to={tabHref(item, t)} onClick={onNavigate}
              className={cn("block truncate rounded-md px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800",
                current === t.id ? "font-medium text-primary" : "text-muted-foreground")}>
              {t.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function AppShell() {
  const { data: projects } = useProjects();
  const projectId = useAppStore((s) => s.projectId);
  const setProjectId = useAppStore((s) => s.setProjectId);
  const setToken = useAppStore((s) => s.setToken);
  const signOut = async () => { try { await api.post("/auth/logout"); } catch { /* session may already be gone */ } setToken(null); };
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);

  // The shell owns the viewport and only the main column scrolls. Previously the document scrolled with the
  // sidebar stuck to the top at `h-screen`: any mismatch between 100vh and the real viewport — a browser toolbar,
  // a horizontal scrollbar, zoom — left the sidebar ending short of the bottom of the window with a strip of page
  // showing underneath. Nothing can scroll out from under it now, because nothing outside the main column scrolls.
  return (
    <div className="flex h-dvh overflow-hidden">
      {/* Backdrop for the mobile drawer */}
      {navOpen && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" aria-hidden onClick={() => setNavOpen(false)} />}
      <aside
        className={cn(
          "w-64 shrink-0 border-r bg-white dark:bg-slate-900 flex flex-col h-full",
          "fixed inset-y-0 left-0 z-40 transition-transform duration-200 lg:static lg:translate-x-0 lg:w-60",
          navOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-start gap-2 px-3 py-4">
          <Link to="/" title="Home" aria-label="Back to brands" onClick={() => setNavOpen(false)} className="rounded-md py-1.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><Home className="h-5 w-5" /></Link>
          <Link to="/" title="Home" onClick={() => setNavOpen(false)} className="rounded py-0.5 text-lg font-bold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">GrowOS</Link>
          <div className="ml-auto">
            <RunJobsButton />
          </div>
          <button className="ml-auto py-1.5 lg:hidden text-muted-foreground hover:text-foreground" aria-label="Close menu" onClick={() => setNavOpen(false)}><X className="h-5 w-5" /></button>
        </div>
        <div className="px-3 pt-3 pb-5 border-b">
          <Select className="w-full" value={projectId ?? ""} onChange={(e) => { if (e.target.value === "__new") navigate("/setup"); else setProjectId(e.target.value); }}>
            {projects?.map((p) => <option key={p.id} value={p.id}>{p.brand_name || p.name}</option>)}
            <option value="__new">+ New brand…</option>
          </Select>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
          {NAV.map((item) => (
            <Fragment key={item.to}>
              {item.dividerBefore && <hr className="!my-2 border-t" />}
              <NavEntry item={item} onNavigate={() => setNavOpen(false)} />
            </Fragment>
          ))}
        </nav>
        <div className="flex items-center gap-1 border-t px-2 py-2 text-muted-foreground">
          <UserMenu />
          <NotificationBell placement="up" />
          <button className="shrink-0 rounded p-1.5 hover:bg-slate-100 hover:text-foreground dark:hover:bg-slate-800" title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} aria-label="Toggle dark mode" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</button>
          <button className="shrink-0 rounded p-1.5 hover:bg-slate-100 hover:text-foreground dark:hover:bg-slate-800" title="Sign out" aria-label="Sign out" onClick={signOut}><LogOut className="h-4 w-4" /></button>
        </div>
      </aside>
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* Mobile top bar with the menu toggle (the sidebar is off-canvas below lg). It sits outside the scrolling
            area, so it stays put without needing to be sticky. */}
        <header className="lg:hidden z-20 flex shrink-0 items-center gap-3 border-b bg-white dark:bg-slate-900 px-4 py-3">
          <button aria-label="Open menu" className="text-muted-foreground hover:text-foreground" onClick={() => setNavOpen(true)}><Menu className="h-5 w-5" /></button>
          <span className="font-bold tracking-tight">GrowOS</span>
          <div className="ml-auto"><NotificationBell align="right" /></div>
        </header>
        <main className="flex-1 min-w-0 overflow-y-auto">
          <div className="w-full max-w-[1500px] p-4 sm:p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
