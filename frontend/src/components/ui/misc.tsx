import { ReactNode } from "react";
import { Info, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent } from "./card";
import { InfoHint } from "./info-hint";
import { cn, fmtPct } from "@/lib/utils";

export { InfoHint };

export function PageHeader({ title, info, actions }: { title: string; info?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
      <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">{title}{info && <InfoHint width="w-80">{info}</InfoHint>}</h1>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <Card className="border-dashed">
      <CardContent className="py-10 text-center">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500">{icon ?? <Info className="h-5 w-5" />}</div>
        <p className="font-medium">{title}</p>
        {children && <div className="text-sm text-muted-foreground mt-2 max-w-xl mx-auto">{children}</div>}
      </CardContent>
    </Card>
  );
}

export function Metric({ label, value, hint, change, source, className }: { label: string; value: ReactNode; hint?: string; change?: number | null; source?: string; className?: string }) {
  return (
    <Card className={className}>
      <CardContent className="pt-5">
        <div className="text-xs font-medium text-muted-foreground flex items-center gap-1">
          {label}
          {(hint || source) && <InfoHint>
            {hint && <span className="block">{hint}</span>}
            {source && <span className={cn("block", hint && "mt-1.5 border-t pt-1.5")}>{source}</span>}
          </InfoHint>}
        </div>
        <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
        {change != null && (
          <div className="mt-1 flex items-center gap-2 text-xs">
            <span className={cn("inline-flex items-center gap-0.5 font-medium", change > 0 ? "text-emerald-600" : change < 0 ? "text-red-600" : "text-muted-foreground")}>
              {change > 0 ? <TrendingUp className="h-3 w-3" /> : change < 0 ? <TrendingDown className="h-3 w-3" /> : <Minus className="h-3 w-3" />} {fmtPct(Math.abs(change), 0)}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="rounded-md border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">{msg}</div>;
}

export function Spinner({ className }: { className?: string }) {
  return <div className={cn("h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-primary", className)} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
      <Spinner /> {label}
    </div>
  );
}
