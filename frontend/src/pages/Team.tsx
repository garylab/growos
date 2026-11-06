import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Member, type Project, type User } from "@/lib/api";
import { useProjectId, useProjects } from "@/hooks/useProject";
import { useAppStore } from "@/store/app";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Field, Input, PasswordInput, Select } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { EmptyState, ErrorBox, Loading, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { TimeAgo } from "@/components/ui/time";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

const MEMBER_COLUMNS: CsvColumn<Member>[] = [
  { key: "name", label: "Name", value: (r) => r.name }, { key: "email", label: "Email", value: (r) => r.email },
  { key: "role", label: "Role", value: (r) => r.effective_role }, { key: "active", label: "Active", value: (r) => r.is_active },
  { key: "added", label: "Added", value: (r) => r.added_at },
];
const USER_COLUMNS: CsvColumn<User>[] = [
  { key: "name", label: "Name", value: (r) => r.name }, { key: "email", label: "Email", value: (r) => r.email },
  { key: "role", label: "Account role", value: (r) => r.role }, { key: "active", label: "Active", value: (r) => r.is_active },
  { key: "last_login", label: "Last signed in", value: (r) => r.last_login_at },
];

/** The one role ladder. "admin" is account-wide; the rest apply to the project being viewed. */
const ROLES = [
  { value: "admin", label: "Admin — every project, manages accounts" },
  { value: "owner", label: "Owner — can manage this project's members" },
  { value: "editor", label: "Editor — can run and change things" },
  { value: "viewer", label: "Viewer — read only" },
];
const ROLE_HELP = "Admin is account-wide: every project, plus account management. Owner, editor and viewer apply to this project only.";

export function TeamPage() {
  const pid = useProjectId();
  const me = useAppStore((s) => s.user);
  const qc = useQueryClient();
  const { data: projects } = useProjects();
  const isAdmin = me?.role === "admin" || me == null; // system-token sessions have no user record
  const { data: users, error: usersError } = useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/users"), enabled: isAdmin, retry: false });
  const { data: members, isLoading } = useQuery({ queryKey: ["members", pid], queryFn: () => api.get<Member[]>(`/projects/${pid}/members`), enabled: !!pid });
  const [adding, setAdding] = useState(false);
  const [memberFilter, setMemberFilter] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const addMember = useMutation({
    mutationFn: (b: { user_id: string; role: string }) => api.post<Member>(`/projects/${pid}/members`, b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members", pid] }),
  });
  const setRole = useMutation({
    mutationFn: (b: { user_id: string; role: string }) => api.put<Member>(`/projects/${pid}/members/${b.user_id}/role`, { role: b.role }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["members", pid] }); qc.invalidateQueries({ queryKey: ["users"] }); },
  });
  const removeMember = useMutation({
    mutationFn: (userId: string) => api.delete(`/projects/${pid}/members/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members", pid] }),
  });
  const memberRows = (members ?? []).filter((row) => !memberFilter || `${row.name ?? ""} ${row.email} ${row.effective_role}`.toLowerCase().includes(memberFilter.toLowerCase()));
  const userRows = (users ?? []).filter((row) => !userFilter || `${row.name ?? ""} ${row.email} ${row.role}`.toLowerCase().includes(userFilter.toLowerCase()));
  const pagedMembers = usePaged(memberRows);
  const pagedUsers = usePaged(userRows);
  if (isLoading) return <Loading />;
  const notMembers = (users ?? []).filter((u) => !(members ?? []).some((m) => m.user_id === u.id));
  return (
    <div>
      <PageHeader title="Team"
        actions={isAdmin ? <Button onClick={() => setAdding(true)}>Add person</Button> : undefined} />
      <div className="space-y-6">
        <Card>
          <CardHeader><CardTitle info={ROLE_HELP}>Members of this project</CardTitle></CardHeader>
          <CardContent>
            <div className="mb-3 flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter members…" value={memberFilter} onSearch={setMemberFilter} /><div className="ml-auto"><CsvExportButton filename="project-members.csv" rows={memberRows} columns={MEMBER_COLUMNS} /></div></div>
            {!members?.length ? <EmptyState title="No members yet">{isAdmin ? "Add a person to share this project with them." : "Ask an administrator to add people."}</EmptyState> : (
              <Table>
                <THead><TR><TH>Person</TH><TH>Role</TH><TH>Added</TH><TH /></TR></THead>
                <TBody>{pagedMembers.items.map((m) => {
                  const isMe = me?.id === m.user_id;
                  return (
                  <TR key={m.user_id}>
                    <TD><div className="font-medium">{m.name || m.email}{isMe && <span className="text-xs text-muted-foreground"> (you)</span>}</div><div className="text-xs text-muted-foreground">{m.email}</div></TD>
                    <TD>{isAdmin && !isMe ? (
                      <Select className="w-64" value={m.effective_role} onChange={(e) => setRole.mutate({ user_id: m.user_id, role: e.target.value })}>
                        {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </Select>) : <Badge variant={m.effective_role === "admin" ? "info" : "muted"}>{m.effective_role}</Badge>}
                      {!m.is_active && <Badge variant="danger" className="ml-1">disabled</Badge>}
                    </TD>
                    <TD className="text-xs text-muted-foreground"><TimeAgo value={m.added_at} /></TD>
                    <TD className="text-right">{isAdmin && !isMe && <Button size="sm" variant="ghost" onClick={() => removeMember.mutate(m.user_id)}>Remove</Button>}</TD>
                  </TR>);
                })}
                </TBody>
              </Table>
            )}
            <Pagination state={pagedMembers} label="members" />
            <ErrorBox error={addMember.error || removeMember.error || setRole.error} />
            {isAdmin && notMembers.length > 0 && (
              <div className="mt-3 flex gap-2 items-end">
                <Field label="Add an existing account to this project">
                  <Select className="w-72" id="add-existing" defaultValue="">
                    <option value="">choose a person…</option>
                    {notMembers.map((u) => <option key={u.id} value={u.id}>{u.name ? `${u.name} (${u.email})` : u.email}</option>)}
                  </Select>
                </Field>
                <Button size="sm" variant="outline" onClick={() => {
                  const el = document.getElementById("add-existing") as HTMLSelectElement | null;
                  if (el?.value) addMember.mutate({ user_id: el.value, role: "editor" });
                }}>Add to project</Button>
              </div>
            )}
          </CardContent>
        </Card>

        {isAdmin && (
          <Card>
            <CardHeader><CardTitle info="Everyone who can sign in. Roles are set per project in the table above; admin is account-wide.">All accounts</CardTitle></CardHeader>
            <CardContent>
              <div className="mb-3 flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter accounts…" value={userFilter} onSearch={setUserFilter} /><div className="ml-auto"><CsvExportButton filename="accounts.csv" rows={userRows} columns={USER_COLUMNS} /></div></div>
              {usersError ? <ErrorBox error={usersError} /> : !users?.length ? <EmptyState title="No accounts yet">Add the first person to replace token sign-in.</EmptyState> : (
                <Table>
                  <THead><TR><TH>Person</TH><TH>Role</TH><TH>Status</TH><TH>Last signed in</TH><TH /></TR></THead>
                  <TBody>{pagedUsers.items.map((u) => <UserRow key={u.id} user={u} isMe={me?.id === u.id} member={(members ?? []).find((m) => m.user_id === u.id)} />)}</TBody>
                </Table>
              )}
              <Pagination state={pagedUsers} label="accounts" />
            </CardContent>
          </Card>
        )}
      </div>
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent title="Add a person" description="Creates an account and optionally adds them to projects.">
          <NewUserForm projects={projects ?? []} currentProjectId={pid} onDone={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["users"] }); qc.invalidateQueries({ queryKey: ["members", pid] }); }} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function UserRow({ user, isMe, member }: { user: User; isMe: boolean; member?: Member }) {
  const qc = useQueryClient();
  const [pw, setPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const update = useMutation({ mutationFn: (b: Record<string, unknown>) => api.patch<User>(`/users/${user.id}`, b), onSuccess: () => { refresh(); setPw(""); setShowPw(false); } });
  const del = useMutation({ mutationFn: () => api.delete(`/users/${user.id}`), onSuccess: refresh });
  return (
    <TR>
      <TD><div className="font-medium">{user.name || user.email}{isMe && <span className="text-xs text-muted-foreground"> (you)</span>}</div><div className="text-xs text-muted-foreground">{user.email}</div></TD>
      <TD>{user.role === "admin" ? <Badge variant="info">admin</Badge>
        : member ? <Badge variant="muted">{member.role}</Badge>
        : <span className="text-xs text-muted-foreground">not on this project</span>}</TD>
      <TD><StatusBadge status={user.is_active ? "healthy" : "disabled"} />{user.must_change_password && <Badge variant="warning" className="ml-1">must change password</Badge>}</TD>
      <TD className="text-xs text-muted-foreground"><TimeAgo value={user.last_login_at} fallback="never" /></TD>
      <TD className="text-right whitespace-nowrap">
        {showPw ? (
          <span className="inline-flex gap-1 items-center">
            <Input className="w-44 h-8" type="text" placeholder="new password (8+)" value={pw} onChange={(e) => setPw(e.target.value)} />
            <Button size="sm" disabled={pw.length < 8} onClick={() => update.mutate({ password: pw, must_change_password: true })}>Set</Button>
            <Button size="sm" variant="ghost" onClick={() => { setShowPw(false); setPw(""); }}>Cancel</Button>
          </span>
        ) : (
          <>
            <Button size="sm" variant="ghost" onClick={() => setShowPw(true)}>Reset password</Button>
            {!isMe && <Button size="sm" variant="ghost" onClick={() => update.mutate({ role: user.role === "admin" ? "member" : "admin" })}>{user.role === "admin" ? "Remove admin" : "Make admin"}</Button>}
            {!isMe && <Button size="sm" variant="ghost" onClick={() => update.mutate({ is_active: !user.is_active })}>{user.is_active ? "Disable" : "Enable"}</Button>}
            {!isMe && <Button size="sm" variant="ghost" onClick={() => { if (confirm(`Delete ${user.email}?`)) del.mutate(); }}>Delete</Button>}
          </>
        )}
        <ErrorBox error={update.error || del.error} />
      </TD>
    </TR>
  );
}

function NewUserForm({ projects, currentProjectId, onDone }: { projects: Project[]; currentProjectId: string; onDone: () => void }) {
  const [form, setForm] = useState({ email: "", password: "", name: "", role: "editor", must_change_password: true });
  const [selected, setSelected] = useState<string[]>(currentProjectId ? [currentProjectId] : []);
  const create = useMutation({ mutationFn: () => api.post<User>("/users", { ...form, project_ids: selected }), onSuccess: onDone });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <Field label="Email"><Input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
      <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label="Temporary password" help="At least 8 characters. They will be asked to change it at first sign-in.">
        <PasswordInput required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      </Field>
      <Field label="Role" help={ROLE_HELP}>
        <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</Select>
      </Field>
      <Field label="Projects they can see">
        <div className="space-y-1 max-h-40 overflow-auto rounded border p-2">
          {projects.map((p) => (
            <label key={p.id} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={selected.includes(p.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, p.id] : selected.filter((x) => x !== p.id))} />
              {p.name}
            </label>
          ))}
        </div>
      </Field>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.must_change_password} onChange={(e) => setForm({ ...form, must_change_password: e.target.checked })} /> Ask them to change the password at first sign-in</label>
      <ErrorBox error={create.error} />
      <Button type="submit" disabled={create.isPending}>Create account</Button>
    </form>
  );
}
