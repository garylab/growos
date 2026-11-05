import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type Domain, type Project } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAppStore } from "@/store/app";
import { ErrorBox } from "@/components/ui/misc";

export function Setup() {
  const [form, setForm] = useState({ name: "", brand_name: "", brand_aliases: "", website: "", description: "", default_country: "US", default_language: "en" });
  const setProjectId = useAppStore((s) => s.setProjectId);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: async () => {
      const p = await api.post<Project>("/projects", {
        name: form.name, brand_name: form.brand_name || form.name, description: form.description || null,
        brand_aliases: form.brand_aliases.split(",").map((s) => s.trim()).filter(Boolean),
        default_country: form.default_country, default_language: form.default_language,
      });
      if (form.website.trim()) await api.post<Domain>(`/projects/${p.id}/domains`, { url: form.website.trim(), role: "primary" });
      return p;
    },
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); setProjectId(p.id); navigate("/"); },
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Create a project</CardTitle>
          <CardDescription>A project tracks one brand: its website, competitors, keywords and AI prompts.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <Field label="Project name"><Input required value={form.name} onChange={set("name")} placeholder="Acme" /></Field>
            <Field label="Brand name (as it appears in text)"><Input value={form.brand_name} onChange={set("brand_name")} placeholder="Acme Inc" /></Field>
            <Field label="Brand aliases (comma separated)" help="Other spellings or product names used to detect mentions."><Input value={form.brand_aliases} onChange={set("brand_aliases")} placeholder="acme.com, Acme Cloud" /></Field>
            <Field label="Website URL"><Input value={form.website} onChange={set("website")} placeholder="https://www.example.com" /></Field>
            <Field label="What does the business do? (used by the AI analyst)"><Textarea value={form.description} onChange={set("description")} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Default country"><Input value={form.default_country} onChange={set("default_country")} /></Field>
              <Field label="Default language"><Input value={form.default_language} onChange={set("default_language")} /></Field>
            </div>
            <ErrorBox error={create.error} />
            <Button type="submit" className="w-full" disabled={create.isPending}>Create project</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
