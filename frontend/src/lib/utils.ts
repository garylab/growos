import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const fmtInt = (n: number | null | undefined) => (n == null ? "—" : new Intl.NumberFormat().format(Math.round(n)));
export const fmtPct = (n: number | null | undefined, digits = 1) => (n == null ? "—" : `${(n * 100).toFixed(digits)}%`);
export const fmtNum = (n: number | null | undefined, digits = 1) => (n == null ? "—" : n.toFixed(digits));
export const delta = (now?: number | null, before?: number | null) =>
  now == null || before == null || before === 0 ? null : (now - before) / before;
