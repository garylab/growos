import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input, PasswordInput } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAppStore, type CurrentUser } from "@/store/app";
import { ErrorBox } from "@/components/ui/misc";

interface Meta { auth_mode: "users" | "token"; users_exist: boolean; google_login_enabled?: boolean }

const GOOGLE_ERRORS: Record<string, string> = {
  no_account: "No GrowOS account matches that Google email. Ask an administrator to add you under Team first.",
  unverified: "That Google account has no verified email address.",
  mismatch: "That Google account is already linked to a different user.",
  expired: "The sign-in request expired. Please try again.",
  access_denied: "Google sign-in was cancelled.",
  google: "Could not complete sign-in with Google. Please try again.",
};

export function Login({ googleError }: { googleError?: string | null } = {}) {
  const { data: meta } = useQuery({ queryKey: ["meta"], queryFn: async () => (await fetch("/api/meta")).json() as Promise<Meta> });
  const setToken = useAppStore((s) => s.setToken);
  const setUser = useAppStore((s) => s.setUser);
  const [form, setForm] = useState({ email: "", password: "", token: "" });
  const [error, setError] = useState<string | null>(googleError ? (GOOGLE_ERRORS[googleError] || "Google sign-in failed.") : null);
  const [busy, setBusy] = useState(false);
  const tokenMode = meta?.auth_mode === "token";
  const googleEnabled = !tokenMode && meta?.google_login_enabled;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (tokenMode) {
        const res = await fetch("/api/projects", { headers: { "X-Auth-Token": form.token } });
        if (!res.ok) throw new Error("That access token was not accepted");
        setToken(form.token);
      } else {
        const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: form.email, password: form.password }) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.detail || "Incorrect email or password");
        setToken(data.token);
        setUser(data.user as CurrentUser);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>GrowOS</CardTitle>
          <CardDescription>{tokenMode ? "No user accounts exist yet. Sign in with the access token, then create the first administrator under Team." : "Sign in with your email and password."}</CardDescription>
        </CardHeader>
        <CardContent>
          {googleEnabled && (
            <div className="mb-4 space-y-3">
              <a href="/api/auth/google/login" className="flex w-full items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700">
                <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.76c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"/><path fill="#FBBC05" d="M5.84 14.09a6.6 6.6 0 0 1 0-4.18V7.07H2.18a11 11 0 0 0 0 9.86l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"/></svg>
                Sign in with Google
              </a>
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <span className="h-px flex-1 bg-gray-200 dark:bg-gray-700" />or<span className="h-px flex-1 bg-gray-200 dark:bg-gray-700" />
              </div>
            </div>
          )}
          <form className="space-y-3" onSubmit={submit}>
            {tokenMode ? (
              <Field label="Access token"><PasswordInput autoFocus value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} /></Field>
            ) : (
              <>
                <Field label="Email"><Input type="email" autoComplete="username" autoFocus required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
                <Field label="Password"><PasswordInput autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
              </>
            )}
            <ErrorBox error={error} />
            <Button className="w-full" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

/** Forced password change after an admin sets a temporary one. */
export function ChangePassword() {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const setUser = useAppStore((s) => s.setUser);
  const setToken = useAppStore((s) => s.setToken);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.new_password !== form.confirm) return setError("The two passwords do not match");
    try {
      await api.post("/auth/password", { current_password: form.current_password, new_password: form.new_password });
      setUser(null);
      setToken(null); // all sessions are revoked on password change — sign in again
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader><CardTitle>Choose a new password</CardTitle><CardDescription>Your account was created with a temporary password.</CardDescription></CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={submit}>
            <Field label="Current password"><PasswordInput autoComplete="current-password" required value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></Field>
            <Field label="New password" help="At least 8 characters."><PasswordInput autoComplete="new-password" required minLength={8} value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></Field>
            <Field label="Repeat new password"><PasswordInput autoComplete="new-password" required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></Field>
            <ErrorBox error={error} />
            <Button className="w-full" type="submit">Save and sign in again</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
