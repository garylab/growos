import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      default: "border-transparent bg-primary text-primary-foreground",
      secondary: "border-transparent bg-secondary text-secondary-foreground",
      outline: "text-foreground",
      success: "border-transparent bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200",
      warning: "border-transparent bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
      danger: "border-transparent bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200",
      info: "border-transparent bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200",
      muted: "border-transparent bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...props }: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, "success" | "warning" | "danger" | "info" | "muted"> = {
    succeeded: "success", healthy: "success", done: "success", running: "info", in_progress: "info", queued: "warning", planned: "warning",
    unverified: "warning", open: "info", failed: "danger", error: "danger", cancelled: "muted", dismissed: "muted", disabled: "muted",
    critical: "danger", warning: "warning", positive: "success", negative: "danger", neutral: "muted",
  };
  return <Badge variant={map[status] ?? "muted"}>{status.replace(/_/g, " ")}</Badge>;
}
