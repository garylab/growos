# GrowOS — AI Customer Acquisition Intelligence Platform

GrowOS helps a business acquire more customers by improving **organic search visibility**, **AI search visibility**,
**brand presence** and **competitive positioning**. It continuously runs the loop
**Monitor → Analyze → Identify Opportunities → Recommend Actions → Measure Results**.

Local-first and on-prem ready: one `docker compose up`, your own API keys, no cloud backend.

## What is in the box

**Sign in.** On first start GrowOS creates an administrator from `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`. The admin
adds people under **Team** (email + temporary password), chooses which projects each person can see, and assigns
checklist items to them. Members only see the projects they belong to; viewers are read-only. `APP_AUTH_TOKEN` keeps
working for scripts and automation.

**Start on the Growth Plan page.** It turns everything collected below into one checklist: *Business basics* (closed-loop
self-check, company email, logo, trust pages, directory listings, Google Business Profile), *Fix once* (website and content fixes, with the exact pages listed) and *Keep doing* (weekly article, video, community replies, backlink outreach, monthly
competitor review) — each with concrete suggestions taken from your own data: article topics from your Search Console
queries, video scripts, threads to join, sites AI assistants cite that you should be mentioned on. Fixed items disappear
automatically once the next audit confirms them; routines come back when they are due again.

| Module | What it does | Engines / sources |
|---|---|---|
| SEO Intelligence | Crawl + technical/SEO audit, page scores, broken links, redirects, duplicate metadata, historical snapshots and change detection; Lighthouse lab + CrUX field performance; first-party search performance | SiteOne Crawler (bundled), PageSpeed Insights (Lighthouse), Chrome UX Report API, Google Search Console API |
| AI Search Visibility (GEO) | Prompt collections by intent/topic/locale, repeated sampling per provider, brand/competitor mention extraction, positions, cited sources, grounded vs non-grounded, trends over runs | OpenAI (Responses API + web search), Google Gemini (+ Google Search grounding), Perplexity, any OpenAI-compatible API, Ollama |
| Brand & Competitor Intelligence | Brand/competitor mentions with sentiment, topics and customer-intent detection; competitor pricing/feature page change detection | Hacker News (Algolia API), Bluesky public API, RSS/Atom feeds, SSRF-safe page fetcher |
| Growth Opportunity Intelligence | Evidence-backed opportunities from all modules with a transparent score (impact × confidence × effort factor), status + history, an AI analyst with tool calling that can only cite real records | Rule engine + one central AI analysis service |
| Content studio | Writes the article, social post or short-video script for a checklist topic, grounded in your own search and competitor data. Returns captions (SRT), shot list, hashtags and metadata | Your configured AI provider — pick Ollama to keep generation fully open source and local |
| Brand scorecard | Three 0–100 indices — Brand Influence 品牌影响力, Brand Competitiveness 品牌竞争力, Monetization Readiness 变现能力 — plus an annualised revenue model and indicative valuation range. Every component shows its raw value, source and formula; an index with less than half its data is withheld rather than guessed | All collected data |
| Autonomy | New projects seed daily/weekly schedules and crawl on first domain, so collection runs without anyone remembering to click. Weekly digest and failure alerts push to members (in-app always, email when SMTP is set) | APScheduler + SMTP |
| Team | Accounts, per-project membership (owner/editor/viewer) and checklist assignment | — |
| Actions & Results | Optimization actions, before/after outcome measurement from Search Console, analytics and AI visibility, first-party website analytics (sessions, conversions, revenue per landing page) | Google Analytics 4 Data API, CSV import |

Everything collected keeps its provenance: provider, model/version, locale, request config, timestamp, raw artifact on disk,
normalized record and measurement type (first-party / observed / lab / field / estimated).

## Quick start

Requirements: Docker Engine 24+ with Compose v2. Nothing else — the SiteOne crawler is bundled in the worker image.

```bash
cp .env.example .env
# generate secrets
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" .env
sed -i "s/^APP_SECRET_KEY=.*/APP_SECRET_KEY=$(openssl rand -hex 32)/" .env
sed -i "s/^APP_AUTH_TOKEN=.*/APP_AUTH_TOKEN=$(openssl rand -hex 24)/" .env
# if you expose it through a tunnel, set the public URL (used for Google OAuth redirects)
# PUBLIC_BASE_URL=https://growos.example.com

docker compose up -d --build
```

Open <http://localhost:8888> (or your tunnel hostname) and sign in with the `APP_AUTH_TOKEN` value.
Only port **8888** is published (Caddy serves the UI and proxies `/api`). PostgreSQL and the API are internal.

### One-click "Connect with Google" (one-time setup)

Google only issues tokens to a registered OAuth client, so create one per deployment (about five minutes):

1. Google Cloud Console → *APIs & Services* → enable **Google Search Console API**, **Google Analytics Data API** and
   **Google Analytics Admin API**.
2. *OAuth consent screen* → add your Google account as a test user (or publish it for your Workspace).
3. *Credentials* → *Create OAuth client ID* → *Web application* → authorized redirect URI
   `<PUBLIC_BASE_URL>/api/integrations/google/oauth/callback` (for example `https://growos.example.com/api/integrations/google/oauth/callback`).
4. Put the client ID and secret into `.env` as `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`, then `docker compose up -d`.

Integrations then shows **Connect with Google** on Search Console and Analytics. Clicking it opens Google's consent page and
returns to GrowOS with the connection verified. Refresh tokens are stored encrypted; the client secret stays in `.env`.

### Cloudflare tunnel

Point the tunnel at `http://localhost:8888`. Keep `APP_AUTH_TOKEN` set (the UI/API require it) and consider Cloudflare Access
in front of the hostname. Set `PUBLIC_BASE_URL` to the public hostname so the Google OAuth redirect URI is correct.

### First run checklist

1. **Create a project** (brand name, aliases, website). Hirelala/MockReal or any site — nothing is hardcoded.
2. **Integrations** → add the providers you own keys for:
   * OpenAI and/or Gemini (AI visibility + AI analyst). Tick *Use this connection for the AI analyst* on one of them.
   * Google Search Console and Google Analytics 4: click **Connect with Google** (one-time prerequisite: a Google OAuth
     client in `.env`, see below). GrowOS auto-fills the Search Console property and GA4 property for your websites when
     they can be matched; otherwise set them under SEO → Search performance / Actions & Results → Website analytics.
     Alternative: paste a service-account JSON on the provider and grant that email access to the property.
   * Recommended: `GOOGLE_API_KEY` in `.env` for PageSpeed Insights / CrUX (the keyless PageSpeed quota is shared and frequently exhausted → HTTP 429). Optional: Perplexity, Ollama, RSS feeds.
   * Backlinks: connect **Apify → Semrush Backlinks**, paste an Apify API token (paid Apify plan), keep
     `worldwide`, 80 links, 60 domains and the $1/run cap initially. The token can instead be supplied once as
     `APIFY_API_TOKEN` in `.env`. Then use **SEO Performance → Backlinks → Sync backlinks**.
   * Bundled with no key: SiteOne crawler, PageSpeed Insights (no-key quota), Hacker News, Bluesky.
3. **SEO Intelligence** → *Run crawl & audit*, *Run Lighthouse*; set the Search Console property and *Sync Search Console*.
4. **AI Search Visibility** → add prompts (intent, topic, locale, samples per run) → *Run all active prompts*.
5. **Competitors** → add competitors (names, aliases, website, pricing URLs to watch) → *Check watched pages now*.
6. **Brand Intelligence** → *Collect mentions now*.
7. **Growth Opportunities** → *Generate (rules)*, then *Run AI analyst*.
8. **Growth Plan** → *Refresh plan*, then work top-down. Tick items off; routines log each time you do them. Use *Track the result* on an item to start measuring whether it worked.
9. **Results** → the actions you are tracking; *Measure outcomes* after a few weeks.
10. **Settings** → add recurring schedules (Search Console daily, crawl weekly, AI visibility weekly, mentions daily).

## Verify the deployment

```bash
docker compose ps                                     # db, api, worker, web healthy; migrate exited 0
curl -s http://localhost:8888/api/health              # {"status":"ok"}
curl -s http://localhost:8888/api/meta                # auth_required: true when APP_AUTH_TOKEN is set
TOKEN=$(grep ^APP_AUTH_TOKEN .env | cut -d= -f2)
curl -s -H "X-Auth-Token: $TOKEN" http://localhost:8888/api/health/worker   # worker_seen_recently after the first job
curl -s -H "X-Auth-Token: $TOKEN" http://localhost:8888/api/integrations/providers | head -c 400
docker compose logs -f worker                         # structured JSON logs, no credentials
```

API docs (OpenAPI): <http://localhost:8888/api/docs> (send the token as `X-Auth-Token`).

### Run the tests

```bash
# backend unit tests (no database needed) — runs inside the built image
docker compose build migrate
docker run --rm -v "$PWD/backend:/app" -w /app \
  -e APP_SECRET_KEY=test-secret-key-0123456789abcdef0123456789abcdef \
  -e DATABASE_URL=postgresql+psycopg://x:y@localhost/z \
  growos-backend python -m pytest -q -p no:cacheprovider

# queue integration tests against the running database
docker compose exec -e RUN_DB_TESTS=1 api python -m pytest -q -p no:cacheprovider tests/test_queue_integration.py

# frontend type check / build
cd frontend && npm ci && npm run typecheck && npm run build

# Playwright smoke test against a running stack
cd frontend && npx playwright install chromium && E2E_TOKEN=$TOKEN npm run test:e2e
```

## Configuration

All runtime configuration is environment-based (see `.env.example`). Provider API keys are **not** environment variables:
they are entered in the UI, encrypted with a key derived from `APP_SECRET_KEY` (PBKDF2 → Fernet) and stored in PostgreSQL.
The API only ever returns masked previews. Rotating `APP_SECRET_KEY` invalidates stored credentials (re-enter them).

| Variable | Purpose |
|---|---|
| `APP_SECRET_KEY` | Master key for credential encryption (≥ 32 random chars) |
| `APP_AUTH_TOKEN` | Shared access token for UI/API (empty = no auth; only for isolated LAN use) |
| `PUBLIC_BASE_URL` | Public URL, used for the Google OAuth redirect URI `…/api/integrations/google/oauth/callback` (register it on the OAuth client) |
| `WEB_PORT` | Host port for the UI (default 8888) |
| `WORKER_CONCURRENCY` | Parallel jobs per worker container |
| `CRAWL_MAX_URLS_DEFAULT`, `CRAWL_USER_AGENT` | Crawler defaults |

## Operations

* **Backups / restore**: see [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).
* **Architecture, data model, adapters**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
* **AI visibility measurement methodology and caveats**: [docs/METHODOLOGY.md](docs/METHODOLOGY.md).
* **Roadmap, phase status and known limitations**: [docs/ROADMAP.md](docs/ROADMAP.md).
* Migrations run automatically on start (`migrate` service). To create a new migration after changing models:
  `docker compose run --rm -v "$PWD/backend:/app" -u root migrate alembic revision --autogenerate -m "describe change"`.

## Security notes

* Outbound fetches of user-supplied URLs (crawl targets, feeds, watched pages) go through an SSRF guard: http/https only,
  DNS resolved up-front, every address must be public (no loopback/private/link-local/CGNAT/metadata/IPv4-mapped), the
  connection is pinned to the validated IP (DNS-rebinding safe), redirects are re-validated hop by hop, size/time capped.
* The SiteOne crawler only receives URLs that passed the same validation and is restricted to the target domain.
* No public ports except the UI; database credentials never leave the compose network; logs redact secrets.
* Rate limiting on mutating API calls; input validation via Pydantic.

## License notes

GrowOS bundles the [SiteOne Crawler](https://github.com/janreges/siteone-crawler) (MIT). Google, OpenAI, Perplexity, Bluesky
and Hacker News (Algolia) are accessed only through their official APIs with your own credentials and within their terms.
