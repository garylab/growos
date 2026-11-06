import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Member, type User } from "@/lib/api";
import { useProjectId } from "@/hooks/useProject";
import { useAppStore } from "@/store/app";
import { Button } from "@/components/ui/button";
import { CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Field, Input, PasswordInput, Select } from "@/components/ui/input";
import { SearchBox } from "@/components/ui/search-box";
import { EmptyState, ErrorBox, Loading, PageHeader } from "@/components/ui/misc";
import { Pagination, usePaged } from "@/components/ui/pagination";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { TimeAgo } from "@/components/ui/time";
import { CsvExportButton, type CsvColumn } from "@/components/ui/csv-export";

interface AccountRow extends User { member?: Member }
const USER_COLUMNS: CsvColumn<AccountRow>[] = [
  { key: "name", label: "Name", value: (r) => r.name }, { key: "email", label: "Email", value: (r) => r.email },
  { key: "role", label: "Role", value: (r) => r.member?.role ?? "not on this project" }, { key: "active", label: "Active", value: (r) => r.is_active },
  { key: "last_login", label: "Last signed in", value: (r) => r.last_login_at },
];

/** Project access is assigned separately for the project currently being viewed. */
const ROLES = [
  { value: "owner", label: "Owner — can manage this project's members" },
  { value: "editor", label: "Editor — can run and change things" },
  { value: "viewer", label: "Viewer — read only" },
];
const ROLE_HELP = "This role applies only to the current project. Add the person separately from each project's Team page.";

export function TeamPage() {
  const pid = useProjectId();
  const me = useAppStore((s) => s.user);
  const qc = useQueryClient();
  const isAdmin = me?.role === "admin" || me == null; // system-token sessions have no user record
  const { data: users, error: usersError } = useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/users"), enabled: isAdmin, retry: false });
  const { data: members, isLoading } = useQuery({ queryKey: ["members", pid], queryFn: () => api.get<Member[]>(`/projects/${pid}/members`), enabled: !!pid });
  const [adding, setAdding] = useState(false);
  const [userFilter, setUserFilter] = useState("");
  const setRole = useMutation({
    mutationFn: (b: { user_id: string; role: string }) => api.put<Member>(`/projects/${pid}/members/${b.user_id}/role`, { role: b.role }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["members", pid] }); qc.invalidateQueries({ queryKey: ["users"] }); },
  });
  const removeMember = useMutation({
    mutationFn: (userId: string) => api.delete(`/projects/${pid}/members/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members", pid] }),
  });
  const selfMember = (members ?? []).find((member) => member.user_id === me?.id);
  const canManageProject = isAdmin || selfMember?.effective_role === "owner";
  const accounts: AccountRow[] = isAdmin
    ? (users ?? []).map((user) => ({ ...user, member: (members ?? []).find((member) => member.user_id === user.id) }))
    : (members ?? []).map((member) => ({
        id: member.user_id, email: member.email, name: member.name, role: member.user_role,
        is_active: member.is_active, last_login_at: null, must_change_password: false,
        created_at: member.added_at, member,
      }));
  const userRows = accounts.filter((row) => !userFilter || `${row.name ?? ""} ${row.email} ${row.member?.role ?? ""}`.toLowerCase().includes(userFilter.toLowerCase()));
  const pagedUsers = usePaged(userRows);
  if (isLoading) return <Loading />;
  return (
    <div>
      <PageHeader title="Team"
        actions={isAdmin ? <Button onClick={() => setAdding(true)}>Add person</Button> : undefined} />
      <div>
          <section>
            <CardContent>
              <div className="mb-3 flex gap-2"><SearchBox className="w-[32rem]" placeholder="Filter accounts…" value={userFilter} onSearch={setUserFilter} /><div className="ml-auto"><CsvExportButton filename="accounts.csv" rows={userRows} columns={USER_COLUMNS} /></div></div>
              {usersError ? <ErrorBox error={usersError} /> : !accounts.length ? <EmptyState title="No accounts yet">Add the first person to replace token sign-in.</EmptyState> : (
                <Table>
                  <THead><TR><TH>Person</TH><TH>Role</TH><TH>Status</TH><TH>Last signed in</TH><TH /></TR></THead>
                  <TBody>{pagedUsers.items.map((u) => <UserRow key={u.id} user={u} isMe={me?.id === u.id} isAdmin={isAdmin} canManageProject={canManageProject}
                    onSetRole={(role) => setRole.mutate({ user_id: u.id, role })} onRemove={() => removeMember.mutate(u.id)} />)}</TBody>
                </Table>
              )}
              <Pagination state={pagedUsers} label="accounts" />
              <ErrorBox error={removeMember.error || setRole.error} />
            </CardContent>
          </section>
      </div>
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent title="Add a person" description="Creates an account and adds it only to this project.">
          <NewUserForm currentProjectId={pid} onDone={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["users"] }); qc.invalidateQueries({ queryKey: ["members", pid] }); }} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function UserRow({ user, isMe, isAdmin, canManageProject, onSetRole, onRemove }: {
  user: AccountRow; isMe: boolean; isAdmin: boolean; canManageProject: boolean;
  onSetRole: (role: string) => void; onRemove: () => void;
}) {
  const qc = useQueryClient();
  const [pw, setPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const update = useMutation({ mutationFn: (b: Record<string, unknown>) => api.patch<User>(`/users/${user.id}`, b), onSuccess: () => { refresh(); setPw(""); setShowPw(false); } });
  const del = useMutation({ mutationFn: () => api.delete(`/users/${user.id}`), onSuccess: refresh });
  return (
    <TR>
      <TD><div className="font-medium">{user.name || user.email}{isMe && <span className="text-xs text-muted-foreground"> (you)</span>}</div><div className="text-xs text-muted-foreground">{user.email}</div></TD>
      <TD>{canManageProject && !isMe ? (
        <Select className="w-72" value={user.member?.role ?? ""} onChange={(e) => e.target.value ? onSetRole(e.target.value) : onRemove()}>
          <option value="">Not on this project</option>
          {ROLES.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
        </Select>
      ) : <><Badge variant="muted">{user.member?.role ?? "not on this project"}</Badge>{user.role === "admin" && <Badge variant="info" className="ml-1">account admin</Badge>}</>}</TD>
      <TD><StatusBadge status={user.is_active ? "healthy" : "disabled"} />{user.must_change_password && <Badge variant="warning" className="ml-1">must change password</Badge>}</TD>
      <TD className="text-xs text-muted-foreground"><TimeAgo value={user.last_login_at} fallback="never" /></TD>
      <TD className="text-right whitespace-nowrap">
        {isAdmin && showPw ? (
          <span className="inline-flex gap-1 items-center">
            <Input className="w-44 h-8" type="text" placeholder="new password (8+)" value={pw} onChange={(e) => setPw(e.target.value)} />
            <Button size="sm" disabled={pw.length < 8} onClick={() => update.mutate({ password: pw, must_change_password: true })}>Set</Button>
            <Button size="sm" variant="ghost" onClick={() => { setShowPw(false); setPw(""); }}>Cancel</Button>
          </span>
        ) : isAdmin ? (
          <>
            <Button size="sm" variant="ghost" onClick={() => setShowPw(true)}>Reset password</Button>
            {!isMe && <Button size="sm" variant="ghost" onClick={() => update.mutate({ is_active: !user.is_active })}>{user.is_active ? "Disable" : "Enable"}</Button>}
            {!isMe && <Button size="sm" variant="ghost" onClick={() => { if (confirm(`Delete ${user.email}?`)) del.mutate(); }}>Delete</Button>}
          </>
        ) : null}
        <ErrorBox error={update.error || del.error} />
      </TD>
    </TR>
  );
}

function NewUserForm({ currentProjectId, onDone }: { currentProjectId: string; onDone: () => void }) {
  const [form, setForm] = useState({ email: "", password: "", name: "", role: "editor", must_change_password: true });
  const create = useMutation({ mutationFn: () => api.post<User>("/users", { ...form, project_ids: [currentProjectId] }), onSuccess: onDone });
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
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.must_change_password} onChange={(e) => setForm({ ...form, must_change_password: e.target.checked })} /> Ask them to change the password at first sign-in</label>
      <ErrorBox error={create.error} />
      <Button type="submit" disabled={create.isPending}>Create account</Button>
    </form>
  );
}
