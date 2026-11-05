import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAppStore, type CurrentUser } from "@/store/app";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, PasswordInput } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ErrorBox, Loading, PageHeader } from "@/components/ui/misc";
import { TimeAgo } from "@/components/ui/time";

interface Me { id: string; email: string; name: string | null; role: string; is_active: boolean; last_login_at: string | null; must_change_password: boolean; created_at: string }

export function ProfilePage() {
  const { data: me, isLoading, error } = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/auth/me") });
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!me) return null;
  return (
    <div>
      <PageHeader title="Your profile" info="Your account on this installation. Only an administrator can change your role, email or access to projects." />
      <div className="grid gap-4 lg:grid-cols-2">
        <AccountCard me={me} />
        <NameCard me={me} />
        <PasswordCard />
      </div>
    </div>
  );
}

function AccountCard({ me }: { me: Me }) {
  return (
    <Card>
      <CardHeader><CardTitle>Account</CardTitle></CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
          <dt className="text-muted-foreground">Email</dt>
          <dd className="truncate" title={me.email}>{me.email}</dd>
          <dt className="text-muted-foreground">Role</dt>
          <dd><Badge variant={me.role === "admin" ? "info" : "muted"}>{me.role === "admin" ? "admin" : "member"}</Badge></dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd>{me.is_active ? "Active" : <span className="text-red-600 dark:text-red-400">Disabled</span>}</dd>
          <dt className="text-muted-foreground">Last signed in</dt>
          <dd><TimeAgo value={me.last_login_at} fallback="never" /></dd>
          <dt className="text-muted-foreground">Member since</dt>
          <dd><TimeAgo value={me.created_at} /></dd>
        </dl>
      </CardContent>
    </Card>
  );
}

function NameCard({ me }: { me: Me }) {
  const qc = useQueryClient();
  const setUser = useAppStore((s) => s.setUser);
  const user = useAppStore((s) => s.user);
  const [name, setName] = useState(me.name ?? "");
  useEffect(() => { setName(me.name ?? ""); }, [me.name]);
  const save = useMutation({
    mutationFn: () => api.patch<CurrentUser>("/auth/me", { name }),
    onSuccess: (u) => {
      if (user) setUser({ ...user, name: u.name });   // the sidebar reads the store
      qc.invalidateQueries({ queryKey: ["me"] });     // ...this card reads the query
      qc.invalidateQueries({ queryKey: ["users"] });  // ...and Team lists every account
    },
  });
  return (
    <Card>
      <CardHeader><CardTitle info="Shown on assigned checklist items and in the team list. Leave it empty to be shown by email.">Display name</CardTitle></CardHeader>
      <CardContent>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder={me.email} /></Field>
          <ErrorBox error={save.error} />
          <div className="flex items-center gap-2">
            <Button type="submit" disabled={save.isPending || name === (me.name ?? "")}>Save</Button>
            {save.isSuccess && name === (me.name ?? "") && <span className="text-xs text-emerald-600 dark:text-emerald-400">Saved</span>}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function PasswordCard() {
  const setUser = useAppStore((s) => s.setUser);
  const setToken = useAppStore((s) => s.setToken);
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: async () => {
      if (form.new_password !== form.confirm) throw new Error("The two new passwords do not match");
      await api.post("/auth/password", { current_password: form.current_password, new_password: form.new_password });
    },
    // The API revokes every session on a password change, this one included — so sign out rather than 401 next call.
    onSuccess: () => { setUser(null); setToken(null); },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : String(e)),
  });
  return (
    <Card className="lg:col-span-2">
      <CardHeader><CardTitle info="Changing your password signs out every device, including this one.">Change password</CardTitle></CardHeader>
      <CardContent>
        <form className="grid gap-3 md:grid-cols-3" onSubmit={(e) => { e.preventDefault(); setError(null); change.mutate(); }}>
          <Field label="Current password"><PasswordInput autoComplete="current-password" required value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></Field>
          <Field label="New password" help="At least 8 characters."><PasswordInput autoComplete="new-password" required minLength={8} value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></Field>
          <Field label="Repeat new password"><PasswordInput autoComplete="new-password" required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></Field>
          <div className="md:col-span-3 space-y-2">
            <ErrorBox error={error} />
            <Button type="submit" disabled={change.isPending}>Save and sign in again</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
