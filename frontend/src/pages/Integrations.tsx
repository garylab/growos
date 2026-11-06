import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Connection, type ProviderMeta } from "@/lib/api";
import { useProjectId } from "@/hooks/useProject";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ErrorBox, InfoHint, Loading, PageHeader, Spinner } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Field, Input, PasswordInput, Select, Textarea } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { TimeAgo } from "@/components/ui/time";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

interface Providers { categories: Record<string, string>; providers: ProviderMeta[]; planned: PlannedMeta[] }
interface PlannedMeta { vendor?: string; key: string; category: string; display_name: string; status: string; note: string }
/** A vendor and everything it can do here — the unit the page is organised around. */
interface VendorGroup { vendor: string; vendor_url: string; providers: ProviderMeta[]; planned: PlannedMeta[]; features: string[] }
interface GoogleStatus { configured: boolean; redirect_uri: string; client_id: string; api_key_configured: boolean }
const GOOGLE = ["google_search_console", "google_analytics_4"];
const RECOMMENDED = new Set([...GOOGLE, "openai"]);
interface TestResult { ok: boolean; message: string }
const cleanProviderName = (name: string) => name === "Any OpenAI-compatible API" ? "OpenAI-compatible API" : name;

export function IntegrationsPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const { data: providers, isLoading } = useQuery({ queryKey: ["providers"], queryFn: () => api.get<Providers>("/integrations/providers") });
  const { data: connections } = useQuery({ queryKey: ["connections", pid], queryFn: () => api.get<Connection[]>(`/integrations/connections?project_id=${pid}`) });
  const [editing, setEditing] = useState<{ provider: ProviderMeta; conn?: Connection } | null>(null);
  const del = useMutation({ mutationFn: (id: string) => api.delete(`/integrations/connections/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["connections", pid] }) });
  const { data: google } = useQuery({ queryKey: ["google-status"], queryFn: () => api.get<GoogleStatus>("/integrations/google/status") });
  const [params] = useSearchParams();
  const connect = useMutation({ mutationFn: (key: string) => api.get<{ auth_url: string }>(`/integrations/google/connect?provider_key=${key}&project_id=${pid}`), onSuccess: (r) => { window.location.href = r.auth_url; } });
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (v: string) => setExpanded((prev) => { const next = new Set(prev); next.has(v) ? next.delete(v) : next.add(v); return next; });
  if (isLoading || !providers) return <Loading />;
  // One row per vendor. A vendor sells across categories — one SerpApi key covers six providers in four of them —
  // so grouping by category showed the same vendor repeatedly with nothing to connect the rows.
  const groups = groupByVendor(providers);
  const shown = groups.filter((g) => !query || `${g.vendor} ${g.features.join(" ")} ${g.providers.map((p) => p.display_name).join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  const columns: CsvColumn<VendorGroup>[] = [
    { key: "vendor", label: "Provider", value: (r) => r.vendor }, { key: "capabilities", label: "Capabilities", value: (r) => r.features.join(", ") },
    { key: "services", label: "Services", value: (r) => r.providers.map((p) => p.display_name).join(", ") },
    { key: "planned", label: "Planned services", value: (r) => r.planned.map((p) => p.display_name).join(", ") }, { key: "docs", label: "Documentation", value: (r) => r.vendor_url },
  ];
  return (
    <div>
      <PageHeader title="Integrations" info="Bring your own API keys. Credentials are encrypted at rest and never returned by the API. A provider without a valid connection is reported as not configured." />
      <ErrorBox error={del.error || connect.error} />
      {params.get("connected") && <div className="mb-4 rounded-md border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-200">Connected {params.get("connected")?.replace(/_/g, " ")}.{params.get("matched") ? ` Property auto-filled for ${params.get("matched")} website(s).` : ""}</div>}
      {params.get("error") && <div className="mb-4 rounded-md border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 px-3 py-2 text-sm text-red-800 dark:text-red-200">Google connection was not completed: {params.get("error")}</div>}
      {google && !google.configured && (
        <Card className="mb-6 border-amber-200 dark:border-amber-900 bg-amber-50/40 dark:bg-amber-950/30"><CardHeader><CardTitle info="Google only issues tokens to a registered OAuth client, so create one once for this deployment. After that, Search Console and Analytics connect with a single click.">One-time setup for “Connect with Google”</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <ol className="list-decimal pl-5 space-y-1">
              <li>Google Cloud Console → APIs &amp; Services → enable <b>Search Console API</b>, <b>Google Analytics Data API</b> and <b>Google Analytics Admin API</b>.</li>
              <li>OAuth consent screen → add your Google account as a test user (or publish for your Workspace).</li>
              <li>Credentials → Create OAuth client ID → Web application → authorized redirect URI: <code className="rounded bg-white dark:bg-slate-900 border px-1">{google.redirect_uri}</code></li>
              <li>Put the client ID and secret in <code>.env</code> as <code>GOOGLE_OAUTH_CLIENT_ID</code> / <code>GOOGLE_OAUTH_CLIENT_SECRET</code> and restart (<code>docker compose up -d</code>).</li>
            </ol>
            <p className="text-muted-foreground">No OAuth? Paste a service-account JSON on the provider below instead.</p>
          </CardContent></Card>
      )}
      <div className="mb-3 flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter providers…" value={query} onSearch={setQuery} /><div className="ml-auto"><CsvExportButton filename="integrations.csv" rows={shown} columns={columns} /></div></div>
      <Table className="table-fixed min-w-[64rem]">
        <THead><TR>
          <TH className="w-[28%]">Provider</TH><TH className="w-[34%]">Can do</TH>
          <TH className="w-[16%]">Status</TH><TH className="w-[22%]" />
        </TR></THead>
        <TBody>
          {shown.map((g) => (
            <VendorRows key={g.vendor} group={g} connections={connections ?? []} categories={providers.categories}
                        google={google} open={expanded.has(g.vendor)} onToggle={() => toggle(g.vendor)}
                        del={del} connect={connect} onEdit={setEditing} />
          ))}
          {!shown.length && <TR><TD colSpan={4} className="py-6 text-center text-sm text-muted-foreground">No providers match “{query}”.</TD></TR>}
        </TBody>
      </Table>
      <Dialog open={!!editing} onOpenChange={(v) => !v && setEditing(null)}>{editing && <DialogContent title={editing.conn ? `Edit ${cleanProviderName(editing.conn.display_name)}` : `Add ${cleanProviderName(editing.provider.display_name)}`} description={editing.provider.description}><ConnectionForm provider={editing.provider} conn={editing.conn} pid={pid} onDone={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["connections", pid] }); }} /></DialogContent>}</Dialog>
    </div>
  );
}

function groupByVendor(providers: Providers): VendorGroup[] {
  const by = new Map<string, VendorGroup>();
  const get = (vendor: string, url = "") => {
    if (!by.has(vendor)) by.set(vendor, { vendor, vendor_url: url, providers: [], planned: [], features: [] });
    const g = by.get(vendor)!;
    if (url && !g.vendor_url) g.vendor_url = url;
    return g;
  };
  for (const p of providers.providers) get(cleanProviderName(p.vendor), p.vendor_url).providers.push(p);
  for (const p of providers.planned) get(cleanProviderName(p.vendor || p.display_name)).planned.push(p);
  for (const g of by.values()) g.features = [...new Set(g.providers.flatMap((p) => p.features))].sort();
  // Vendors that do more come first — they are the ones where one key unlocks several things.
  return [...by.values()].sort((a, b) => b.providers.length - a.providers.length || a.vendor.localeCompare(b.vendor));
}

const label = (f: string) => f.replace(/_/g, " ");

const escapeRe = (v: string) => v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * A provider's name with its vendor removed, for rows sitting under that vendor's heading.
 *
 * "SerpApi (Bing positions)" under a row already labelled SerpApi says the vendor twice; the useful half is what
 * this particular provider does. Only applied where the vendor genuinely repeats — a vendor with one provider
 * keeps its full name, because there the row carries the whole identity and trimming it would lose more than it
 * saves ("Reddit API" becoming "API"). Falls back to the full name whenever stripping leaves nothing meaningful.
 */
function shortName(name: string, vendor: string, siblings: number): string {
  const v = (vendor ?? "").trim();
  if (!v || siblings < 2) return name;
  // Trailing attribution: "YouTube search (SerpApi)" / "TikTok Discover (SerpApi)".
  let out = name.replace(new RegExp(`\\s*\\(${escapeRe(v)}\\)\\s*$`, "i"), "").trim();
  if (out.toLowerCase().startsWith(v.toLowerCase())) {
    // Leading vendor: "SerpApi Extract (…)" -> "Extract (…)", "SerpApi (Bing positions)" -> "Bing positions".
    const rest = out.slice(v.length).trim().replace(/^[-–—:·]\s*/, "");
    const unwrapped = /^\(.*\)$/.test(rest) ? rest.slice(1, -1).trim() : rest;
    if (unwrapped.length >= 3) out = unwrapped;
  }
  if (!out) return name;
  return /^[a-z]/.test(out) ? out.charAt(0).toUpperCase() + out.slice(1) : out;
}

/**
 * A vendor row, and its capabilities underneath when expanded.
 *
 * The vendor is the thing you have an account and a key for; the rows beneath it are the jobs that key can do,
 * each with its own connections because each is stored and billed separately. Collapsed, it answers "do I have
 * this set up"; expanded, it is the per-capability view the page used to show as unrelated rows.
 */
function VendorRows({ group, connections, categories, google, open, onToggle, del, connect, onEdit }: {
  group: VendorGroup; connections: Connection[]; categories: Record<string, string>; google?: GoogleStatus;
  open: boolean; onToggle: () => void; del: any; connect: any;
  onEdit: (v: { provider: ProviderMeta; conn?: Connection }) => void;
}) {
  const [showAllFeatures, setShowAllFeatures] = useState(false);
  const keys = new Set(group.providers.map((p) => p.key));
  const mine = connections.filter((c) => keys.has(c.provider_key));
  const connected = new Set(mine.map((c) => c.provider_key));
  const needsKey = group.providers.filter((p) => p.requires_connection);
  const bundled = group.providers.length - needsKey.length;
  const broken = mine.some((c) => c.is_enabled && c.status === "error");
  const envVars = [...new Set(group.providers.flatMap((p) => Object.values(p.env_credentials ?? {})))];
  return (
    <Fragment>
      <TR className="cursor-pointer" onClick={onToggle}>
        <TD className="align-top">
          <div className="flex items-center gap-1.5 font-medium">
            {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
            <span className="break-words">{group.vendor}</span>
            {group.providers.some((provider) => RECOMMENDED.has(provider.key)) && <span className="text-red-600" title="Recommended">*</span>}
            {group.providers.length > 1 && <span className="text-xs font-normal text-muted-foreground">({group.providers.length})</span>}
          </div>
        </TD>
        <TD className="align-top">
          <div className="flex flex-wrap gap-1">
            {(showAllFeatures ? group.features : group.features.slice(0, 3)).map((f) => <Badge key={f} variant="muted" className="max-w-full break-words">{label(f)}</Badge>)}
            {group.features.length > 3 && <button type="button" className="px-1 text-xs text-primary hover:underline" onClick={(event) => { event.stopPropagation(); setShowAllFeatures((value) => !value); }}>{showAllFeatures ? "Show less" : `+${group.features.length - 3} more`}</button>}
            {!group.features.length && <span className="text-xs text-muted-foreground">—</span>}
          </div>
        </TD>
        <TD className="align-top">
          {broken ? <Badge variant="danger">needs attention</Badge>
            : needsKey.length === 0 ? <Badge variant="success">bundled</Badge>
            : connected.size === 0 ? (envVars.length
                ? <Badge variant="warning">key ready · not connected</Badge>
                : <Badge variant="muted">not set up</Badge>)
            : <Badge variant={connected.size === needsKey.length ? "success" : "warning"}>
                {connected.size} of {needsKey.length} connected{bundled ? ` · ${bundled} bundled` : ""}
              </Badge>}
          {!!envVars.length && (
            <div className="mt-1 flex items-start gap-1 text-xs text-muted-foreground">
              <span className="break-words">key in {envVars.join(", ")}</span>
              <InfoHint className="mt-0.5 shrink-0" width="w-80">
                This deployment supplies the key from its environment, so you never type it here. A connection is
                still needed for each capability you want to use — that is where its own settings live (which AI
                surface, which SERP engine) and it is what the collection jobs look for. Click Add and Save; leave
                the key field blank.
              </InfoHint>
            </div>
          )}
        </TD>
        <TD className="align-top text-right text-xs text-muted-foreground">
          {open ? "" : group.planned.length ? `${group.planned.length} planned` : ""}
        </TD>
      </TR>
      {open && group.providers.map((p) => {
        const conns = connections.filter((c) => c.provider_key === p.key);
        return (
          <TR key={p.key} className="bg-slate-50/60 dark:bg-slate-800/30">
            <TD className="align-top pl-10">
              <div className="flex items-start gap-1.5 text-sm font-medium">
                <span className="break-words">{shortName(p.display_name, group.vendor, group.providers.length)}</span>
                {RECOMMENDED.has(p.key) && <span className="text-red-600" title="Recommended">*</span>}
                <InfoHint className="mt-0.5 shrink-0" width="w-80">
                  <span className="block font-medium text-foreground">{categories[p.category] ?? p.category}</span>
                  <span className="mt-1.5 block">{p.description}</span>
                  {!!p.features?.length && <span className="mt-1.5 block">Provides: {p.features.map(label).join(" · ")}</span>}
                  {p.docs_url && <> <a className="text-primary underline" href={p.docs_url} target="_blank" rel="noreferrer">Docs</a></>}
                </InfoHint>
              </div>
            </TD>
            <TD className="align-top">
              {conns.length ? <div className="space-y-2">{conns.map((c) => (
                <div key={c.id} className="text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{cleanProviderName(c.display_name)}{c.project_id ? "" : " (global)"}</span>
                    <StatusBadge status={c.is_enabled ? c.status : "disabled"} />
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <Button size="sm" variant="ghost" onClick={() => onEdit({ provider: p, conn: c })}>Edit</Button>
                    {GOOGLE.includes(p.key) && <GoogleConnect conn={c} />}
                    <Button size="sm" variant="ghost" onClick={() => del.mutate(c.id)}>Remove</Button>
                  </div>
                </div>))}</div>
                : <span className="text-xs text-muted-foreground">{p.requires_connection ? "no connection yet" : "no key needed"}</span>}
            </TD>
            <TD className="align-top"><ProviderStatus provider={p} conns={conns} google={google} /></TD>
            <TD className="align-top">
              <div className="flex flex-wrap items-center justify-end gap-1">
              {GOOGLE.includes(p.key) && !conns.length && <Button size="sm" onClick={() => connect.mutate(p.key)} disabled={connect.isPending || !google?.configured} title={google?.configured ? "Opens Google consent and returns here" : "Configure GOOGLE_OAUTH_CLIENT_ID first (see above)"}>Connect with Google</Button>}
              <Button size="sm" variant={p.requires_connection && !GOOGLE.includes(p.key) ? "default" : "ghost"} onClick={() => onEdit({ provider: p })}>{p.requires_connection ? (GOOGLE.includes(p.key) ? "Advanced" : "Add") : "Configure"}</Button>
              </div>
            </TD>
          </TR>
        );
      })}
      {open && group.planned.map((p) => (
        <TR key={p.key} className="bg-slate-50/60 dark:bg-slate-800/30 opacity-60">
          <TD className="align-top pl-10">
            <div className="flex items-start gap-1.5 text-sm font-medium">
              <span className="break-words">{shortName(p.display_name, group.vendor, group.providers.length + group.planned.length)}</span>
              <InfoHint className="mt-0.5 shrink-0" width="w-80"><span className="block font-medium text-foreground">{categories[p.category] ?? p.category}</span><span className="mt-1.5 block">{p.note || "Not implemented in this version."}</span></InfoHint>
            </div>
          </TD>
          <TD /><TD className="align-top"><Badge variant="muted">planned</Badge></TD><TD />
        </TR>
      ))}
    </Fragment>
  );
}

/** One word on whether this provider is usable right now, and why. */
function ProviderStatus({ provider: p, conns, google }: { provider: ProviderMeta; conns: Connection[]; google?: GoogleStatus }) {
  if (["pagespeed_insights", "crux"].includes(p.key)) {
    return google?.api_key_configured
      ? <Badge variant="success">GOOGLE_API_KEY set</Badge>
      : <Badge variant={p.key === "crux" ? "danger" : "warning"}>{p.key === "crux" ? "needs GOOGLE_API_KEY" : "keyless: shared quota"}</Badge>;
  }
  if (!p.requires_connection) return <Badge variant="success">bundled</Badge>;
  const envVars = [...new Set(Object.values(p.env_credentials ?? {}))];
  if (!conns.length) {
    // "Key present, nothing collecting yet" is not the same as "nothing set up", and it needs a different action.
    return envVars.length
      ? <Badge variant="warning">key ready · add a connection</Badge>
      : <Badge variant="muted">not set up</Badge>;
  }
  const worst = conns.find((c) => !c.is_enabled) ?? conns.find((c) => c.status !== "healthy") ?? conns[0];
  return <StatusBadge status={worst.is_enabled ? worst.status : "disabled"} />;
}

function ConnectionDiagnostics({ conn, result, pending }: { conn?: Connection; result?: TestResult; pending?: boolean }) {
  const creds = Object.entries(conn?.credential_preview ?? {}).filter(([, value]) => value);
  const config = Object.entries(conn?.config ?? {}).filter(([key]) => key !== "feeds");
  const detail = result?.message || conn?.last_error;
  const bad = result ? !result.ok : !!conn?.last_error;
  const tone = result?.ok ? "text-emerald-700 dark:text-emerald-300" : bad ? "text-red-700 dark:text-red-300" : "text-muted-foreground";
  return (
    <div className="space-y-2 rounded-md bg-slate-50 p-3 text-xs dark:bg-slate-800/60">
      <div className="font-medium">Connection log</div>
      {pending ? <div className="flex items-center gap-2 text-muted-foreground"><Spinner className="h-3.5 w-3.5" /> Testing connection…</div> : detail ? (
        <div><div className={cn("font-medium", tone)}>{result ? (result.ok ? "Test passed" : "Test failed") : "Last error"}</div><div className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] leading-snug">{detail}</div></div>
      ) : <div className="text-muted-foreground">No test result yet.</div>}
      {conn && <>
        <div><span className="font-medium">Credentials:</span> <span className="break-words font-mono text-[11px] text-muted-foreground">{creds.map(([key, value]) => `${key}: ${value}`).join(" · ") || "none"}</span></div>
        {!!config.length && <div><span className="font-medium">Config:</span> <span className="break-words font-mono text-[11px] text-muted-foreground">{config.map(([key, value]) => `${key}=${String(value)}`).join(" · ")}</span></div>}
        {conn.last_checked_at && <div className="text-muted-foreground">Checked <TimeAgo value={conn.last_checked_at} />.</div>}
      </>}
    </div>
  );
}

/**
 * Whether a field applies, given what the rest of the form currently says.
 *
 * A provider that is a blank slate — a custom JSON endpoint — needs different fields depending on what it was
 * pointed at, and showing every field for every job would be one long form in which most boxes are irrelevant and
 * nothing marks which. Hidden fields keep their values: switching back restores what was typed.
 */
function visible(showIf: Record<string, unknown> | undefined, config: Record<string, unknown>): boolean {
  if (!showIf || !Object.keys(showIf).length) return true;
  return Object.entries(showIf).every(([key, want]) => {
    const current = String(config[key] ?? "");
    return Array.isArray(want) ? want.map(String).includes(current) : String(want) === current;
  });
}

function ConnectionForm({ provider, conn, pid, onDone }: { provider: ProviderMeta; conn?: Connection; pid: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [config, setConfig] = useState<Record<string, unknown>>(() => Object.fromEntries(provider.config_fields.map((f) => [f.key, conn?.config[f.key] ?? f.default])));
  const [scope, setScope] = useState<"project" | "global">(conn ? (conn.project_id ? "project" : "global") : "project");
  const [name, setName] = useState(cleanProviderName(conn?.display_name ?? provider.display_name));
  const save = useMutation({
    mutationFn: () => conn ? api.patch(`/integrations/connections/${conn.id}`, { display_name: name, credentials: creds, config, project_id: scope === "project" ? pid : null }) : api.post("/integrations/connections", { provider_key: provider.key, display_name: name, project_id: scope === "project" ? pid : null, credentials: creds, config }),
    onSuccess: onDone,
  });
  const test = useMutation({
    mutationFn: () => !provider.requires_connection && !conn
      ? api.post<TestResult>(`/integrations/providers/${provider.key}/check`)
      : api.post<TestResult>(`/integrations/providers/${provider.key}/test`, { connection_id: conn?.id ?? null, credentials: creds, config }),
    onSuccess: () => conn && qc.invalidateQueries({ queryKey: ["connections", pid] }),
  });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label="Display name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Scope" help="Project-scoped connections override global ones. Switching an existing connection moves it — credentials and config come along.">
        <Select value={scope} onChange={(e) => setScope(e.target.value as "project" | "global")}><option value="project">This project</option><option value="global">All projects</option></Select>
      </Field>
      {provider.credential_fields.map((f) => {
        // A credential the deployment supplies from the environment is not something to demand here: drop the
        // required marker and name the variable, so a blank field reads as deliberate rather than unfinished.
        const envVar = provider.env_credentials?.[f.key];
        const help = f.help
          + (envVar ? ` This server sets ${envVar}, so leaving this blank uses that key.` : "")
          + (conn?.credential_preview[f.key] ? ` Current: ${conn.credential_preview[f.key]} (leave blank to keep)` : "");
        return (
        <Field key={f.key} label={`${f.label}${f.required && !envVar ? " *" : ""}`} help={help}>
          {f.key.endsWith("_json") ? <Textarea rows={4} value={creds[f.key] ?? ""} onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })} /> : f.secret ? <PasswordInput autoComplete="off" value={creds[f.key] ?? ""} onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })} /> : <Input type="text" autoComplete="off" value={creds[f.key] ?? ""} onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })} />}
        </Field>);
      })}
      {provider.config_fields.filter((f) => visible(f.show_if, config)).map((f) => (
        <Field key={f.key} label={f.label} help={f.help}>
          {f.type === "boolean" ? <input type="checkbox" checked={!!config[f.key]} onChange={(e) => setConfig({ ...config, [f.key]: e.target.checked })} />
            : f.type === "select" ? <Select value={String(config[f.key] ?? "")} onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })}>{f.options.map((o) => <option key={o}>{o}</option>)}</Select>
            : f.type === "textarea" || f.key === "feeds" ? <Textarea rows={4} value={String(config[f.key] ?? "")} onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })} placeholder={f.key === "feeds" ? "https://news.google.com/rss/search?q=%22Your+Brand%22\nhttps://example.com/blog/feed" : undefined} />
            : <Input type={f.type === "number" ? "number" : "text"} step="any" value={String(config[f.key] ?? "")} onChange={(e) => setConfig({ ...config, [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value })} />}
        </Field>
      ))}
      <ConnectionDiagnostics conn={conn} result={test.data} pending={test.isPending} />
      <ErrorBox error={test.error} />
      <ErrorBox error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>{conn ? "Save" : "Add"}</Button>
        <Button type="button" variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>Test</Button>
      </div>
    </form>
  );
}

function GoogleConnect({ conn }: { conn: Connection }) {
  const start = useMutation({ mutationFn: () => api.get<{ auth_url: string; redirect_uri: string }>(`/integrations/connections/${conn.id}/google/oauth/start`), onSuccess: (r) => { window.location.href = r.auth_url; } });
  const connected = !!conn.credential_preview.refresh_token;
  return <Button size="sm" variant={connected ? "outline" : "default"} onClick={() => start.mutate()} title={connected ? "Re-run the Google consent flow (e.g. to grant access to more properties)" : "Opens Google consent and returns here"}>{connected ? "Reconnect" : "Connect with Google"}</Button>;
}
