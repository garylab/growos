import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, RefreshCw } from "lucide-react";
import { Button } from "./button";
import { Dialog, DialogContent } from "./dialog";

export interface CsvColumn<T> { key: string; label: string; value: (row: T) => unknown }

function downloadCsv(filename: string, headers: string[], rows: unknown[][]) {
  const cell = (value: unknown) => {
    const raw = value == null ? "" : String(value);
    const safe = /^[=+@-]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  const csv = [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");
  const href = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

export function CsvExportButton<T>({ filename, rows, columns, defaultSelected, label = "Export CSV" }: {
  filename: string;
  rows: T[];
  columns: CsvColumn<T>[];
  defaultSelected?: string[];
  label?: string;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(defaultSelected ?? columns.map((column) => column.key)));
  const chosen = columns.filter((column) => selected.has(column.key));
  const toggle = (key: string) => setSelected((previous) => {
    const next = new Set(previous);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  const exportRows = () => {
    downloadCsv(filename, chosen.map((column) => column.label), rows.map((row) => chosen.map((column) => column.value(row))));
    setOpen(false);
  };
  const refresh = async () => {
    setRefreshing(true);
    try {
      await queryClient.refetchQueries({ type: "active" });
    } finally {
      setRefreshing(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-2">
      <Button size="sm" variant="outline" className="px-2" onClick={refresh} disabled={refreshing} aria-label="Refresh data" title="Refresh data">
        <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <Button size="icon" variant="outline" onClick={() => setOpen(true)} aria-label={label} title={label}>
          <Download className="h-4 w-4" />
        </Button>
        <DialogContent title="Export CSV" description={`${rows.length} matching row${rows.length === 1 ? "" : "s"}. Select the columns to include.`}>
          <div className="flex items-center justify-between gap-3 border-b pb-3">
            <span className="text-sm text-muted-foreground">{chosen.length} of {columns.length} columns selected</span>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set(columns.map((column) => column.key)))}>Select all</Button>
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {columns.map((column) => (
              <label key={column.key} className="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-accent">
                <input type="checkbox" checked={selected.has(column.key)} onChange={() => toggle(column.key)} />
                {column.label}
              </label>
            ))}
          </div>
          <div className="mt-4 flex justify-end">
            <Button size="sm" onClick={exportRows} disabled={!rows.length || !chosen.length}>Export {rows.length} rows</Button>
          </div>
        </DialogContent>
      </Dialog>
    </span>
  );
}
