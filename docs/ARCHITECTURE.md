# Architecture

## Services (docker-compose.yml)

```
            ┌──────────────┐  :8888 (only published port)
 browser ──▶│ web (Caddy)  │── static React build + /api reverse proxy
            └──────┬───────┘
                   ▼
            ┌──────────────┐        ┌──────────────┐
            │ api (FastAPI)│◀──────▶│ db (Postgres)│◀──┐
            └──────────────┘        └──────────────┘   │
                                                       │ SELECT … FOR UPDATE SKIP LOCKED
            ┌──────────────┐                           │
            │ worker       │───────────────────────────┘
            │ queue loop + │── SiteOne binary, provider APIs, SSRF-safe fetcher
            │ APScheduler  │── /data/artifacts (raw payloads, persistent volume)
            └──────────────┘
 migrate (one-shot): alembic upgrade head, api/worker wait for it
```

* `api` and `worker` share one image (`backend/Dockerfile`, Debian trixie + Python 3.12 + SiteOne 2.5.1).
* `web` is a multi-stage build: Node builds the Vite bundle, Caddy serves it and proxies `/api/*` to `api:8000`.

## Backend layout

```
backend/app
├── core/          config (env), db, logging (structlog, redaction), secrets (Fernet), safe_http (SSRF guard), artifacts, ratelimit
├── models/        SQLAlchemy 2 entities (see Data model)
├── schemas/       Pydantic I/O models
├── api/routes/    projects, integrations, jobs, seo, geo, brand, opportunities, actions, overview, health
├── adapters/      provider adapters (health_check / collect / normalize / estimate_usage / get_capabilities)
│   ├── crawling/siteone.py
│   ├── performance/{pagespeed,crux}.py
│   ├── search_performance/gsc.py
│   ├── ai/{openai,gemini,openai_compat}.py   (+ Perplexity, Ollama subclasses)
│   ├── brand/{rss,hackernews,bluesky}.py
│   ├── analytics/ga4.py                        (GA4 Data API runReport)
│   └── google_auth.py                          (shared service-account / OAuth token logic)
├── queue/         TaskQueue interface + PostgresTaskQueue
├── tasks/         job handlers: crawl_domain, measure_performance, sync_search_console, run_ai_visibility,
│                  monitor_brand_mentions, watch_competitor_pages, generate_opportunities, ai_analysis, sync_analytics
│                  sync_analytics, build_growth_plan
├── services/      providers (connection → adapter), text_analysis (mentions/sentiment/intent), outcomes
└── intelligence/  scoring (transparent model), rules (evidence rules), engine (upsert + history), tools + analyst (AI tool calling),
                   playbook (user-facing Growth Plan checklist: setup / fix-once / recurring routines)
backend/worker/main.py   queue consumer threads + APScheduler (schedules, stale-job reaper)
```

## Data separation and provenance

| Layer | Tables |
|---|---|
| 1. Raw external data | `raw_artifacts` (file on the artifacts volume: crawler JSON, API responses, fetched HTML) |
| 2. Normalized business data | `crawl_runs`, `page_snapshots`, `audit_findings`, `performance_observations`, `search_observations`, `ai_answer_observations`, `ai_answer_mentions`, `brand_mentions`, `competitor_observations`, `analytics_events` |
| 3. AI-generated analysis | `ai_analysis` job results + transcript artifacts; opportunities with `origin='ai'` |
| 4. Growth opportunities | `plan_items` (the single checklist: setup / business / fix / routine, with evidence, score breakdown and history) |
| 5. User actions | `action_records` (linked to the plan item they came from) |
| 6. Outcome measurements | `outcome_measurements` (Search Console clicks/impressions/CTR/position, GA4 sessions/conversions/revenue, AI mention rate) |
| Config | `projects`, `domains`, `competitors`, `keywords`, `prompt_definitions`, `provider_connections`, `provider_usage`, `schedules` |
| Accounts | `users`, `project_members`, `user_sessions` (opaque tokens stored hashed), `oauth_states` |
| Content | `content_drafts` (article / social post / video script, with assets and provenance) |
| Jobs | `collection_jobs`, `job_logs` |

Every normalized record references its artifact and job, stores provider key, locale, model/version (where applicable) and a
measurement type. Observations are append-only; Search Console rows are keyed per day (re-sync refreshes the same day because
Google finalizes data late). Nothing is overwritten across runs: crawl runs, AI runs and competitor observations are snapshots.

## Provider adapters

`ProviderAdapter` (`adapters/base.py`) defines `health_check()`, `collect()`, `normalize()`, `estimate_usage()`,
`get_capabilities()` plus declarative `credential_fields` / `config_fields` used to render the Integrations UI. Adapters are
registered in `adapters/registry.py`; business logic resolves them through `services/providers.get_adapter()` which looks up a
project-scoped connection, then a global one, then falls back to connection-less adapters (bundled crawler, public APIs).
A missing provider raises `ProviderNotConfigured` (HTTP 409 / failed job) — never mock data.

## Background jobs

`TaskQueue` (`queue/base.py`) abstracts enqueue/claim/heartbeat/log/complete/fail/cancel/retry/reap. The Postgres implementation
claims with `FOR UPDATE SKIP LOCKED`. Jobs carry status, progress + message, attempts/max_attempts with exponential backoff,
cancellation flag (checked at every progress update), error, result, execution logs and an idempotency key (active duplicate
enqueues return the existing job). APScheduler in the worker only enqueues due `schedules` and reaps jobs without heartbeat.

## Opportunity engine

`intelligence/rules.py` holds deterministic rules that read normalized data and return drafts with evidence references;
`intelligence/scoring.py` computes `priority = impact × confidence × effort_factor` and stores the breakdown;
`intelligence/engine.py` upserts by `dedupe_key`, keeps status, counts sightings and writes history.
The AI analyst (`intelligence/analyst.py`) uses one model with tool calling over `intelligence/tools.py`; `create_growth_opportunity`
rejects evidence whose record ids do not exist.

## Frontend

Vite + React 18 + TypeScript, Tailwind + shadcn-style components, React Router, TanStack Query (polling for jobs), Zustand
(token + selected project, persisted), Recharts. Pages map 1:1 to the main navigation. The API client sends `X-Auth-Token`.
