import * as React from "react";
import { InfoHint } from "./info-hint";
import { cn } from "@/lib/utils";

export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("rounded-lg border bg-card text-card-foreground shadow-sm", className)} {...p} />
);
export const CardHeader = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col space-y-1 p-5 pb-3", className)} {...p} />
);
export const CardTitle = ({ className, info, children, ...p }: React.HTMLAttributes<HTMLHeadingElement> & { info?: React.ReactNode }) => (
  <h3 className={cn("text-base font-semibold leading-none tracking-tight", info && "flex items-center gap-1.5", className)} {...p}>
    {children}{info && <InfoHint width="w-72">{info}</InfoHint>}
  </h3>
);
export const CardDescription = ({ className, ...p }: React.HTMLAttributes<HTMLParagraphElement>) => (
  <p className={cn("text-sm text-muted-foreground", className)} {...p} />
);
export const CardContent = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("p-5 pt-0", className)} {...p} />
);
