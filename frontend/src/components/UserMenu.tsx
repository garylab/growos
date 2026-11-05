import { NavLink } from "react-router-dom";
import { useAppStore } from "@/store/app";
import { cn } from "@/lib/utils";

/** The signed-in person, bottom-left. Links to their profile page. */
export function UserMenu() {
  const user = useAppStore((s) => s.user);
  if (!user) return null;
  const label = user.name || user.email;
  return (
    <NavLink
      to="/profile"
      title={`${label} — your profile`}
      className={({ isActive }) => cn(
        "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800",
        isActive && "bg-slate-100 dark:bg-slate-800",
      )}
    >
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-200 text-[11px] font-semibold uppercase text-slate-600 dark:bg-slate-700 dark:text-slate-200">
        {label.slice(0, 1)}
      </span>
      <span className="min-w-0 truncate text-xs font-medium">{label}</span>
    </NavLink>
  );
}
