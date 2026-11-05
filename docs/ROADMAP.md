# Roadmap, phase status and limitations

## Status by phase (first delivery — internal alpha)

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture, directory structure, data model, integration plan | ✅ docs/ARCHITECTURE.md |
| 1 | Frontend + backend foundation, PostgreSQL schema & migrations, projects/domains, provider configuration, job system, Compose deployment, overview | ✅ |
| 2 | SEO: SiteOne crawl & audit, Lighthouse (PSI) + CrUX, Google Search Console, historical snapshots & change detection | ✅ (GSC/PSI need user keys) |
| 3 | GEO: OpenAI + Gemini (+ Perplexity, OpenAI-compatible, Ollama), prompt management, repeated sampling, mentions, citations, run comparison | ✅ (needs user keys) |
| 4 | Growth opportunity engine: 12 evidence rules, transparent scoring, status + history, AI analyst with tool calling | ✅ |
| 5 | Brand monitoring (RSS, Hacker News, Bluesky), competitor page change detection, Google Analytics 4 sync + CSV import, outcome measurement | ✅ partial — see limitations |

## Verified in this environment

* Full stack starts with `docker compose up -d --build`; only port 8888 is published.
* Real crawl of a public site through the bundled SiteOne binary → page snapshots, findings, scores, second crawl + compare.
* Rule engine, brand monitoring (Hacker News) and competitor page watch jobs run end-to-end through the queue.
* Missing providers fail loudly (`ProviderNotConfigured`) instead of substituting data.
* 48 backend unit tests (SSRF guard, mention extraction, scoring, SiteOne normalization, AI payload normalization, secrets).

## Not verified here (requires customer-owned credentials)

OpenAI, Gemini, Perplexity, Google Search Console, Google Analytics 4, PageSpeed/CrUX with API key, Bing Webmaster Tools. The adapters follow the
current public API contracts and have normalization tests on representative payloads; the first real run should be checked under Jobs → Logs. For
Bing, run the connection's health check first: it lists the exact site URLs the account has verified, which is the string `bing_site_url` must match.

## Known limitations

* **Bluesky**: some networks block `public.api.bsky.app` (HTTP 403). The adapter falls back to `api.bsky.app` and supports an
  app-password login for authenticated access; configure it under Integrations if both public endpoints are blocked.
* **Google Analytics 4** imports landing-page × source/medium daily aggregates only (no user-level or funnel data); GA4 thresholding may withhold small rows. Revenue requires e-commerce/purchase events in GA4.
* **Reddit / YouTube / Mastodon / Harken / OpenMagpie** are not implemented (modular slots in the registry). Reddit requires an
  approved API application; we do not scrape social platforms.
* **Local Lighthouse CLI** is not bundled (no Chrome in the image); PageSpeed Insights runs Lighthouse remotely.
* **Sentiment/intent** are lexicon/keyword heuristics (labelled as such). An AI-classified pass is a natural next step.
* **Authentication** is a single shared token; multi-user accounts/roles are out of scope for the alpha. Put Cloudflare
  Access in front when tunnelling.
* **OAuth** state is stored in the `oauth_states` table (15-minute expiry, single use), so API restarts or multiple API
  replicas do not break the Google consent flow.
* **OpenTelemetry** is not wired yet (structured JSON logs are).
* Playwright smoke test exists but is not run in CI.

## Growth Plan (added 2026-11-02)

The landing page is now a single prioritised checklist built from all collected data (`app/intelligence/playbook.py`):

* **Setup** — what to connect next so the rest gets more specific.
* **Business basics** — a guided closed-loop self-check (attract → decide → buy → deliver → onboard → support →
  after-sales → feedback) backed by detected page coverage, plus company-email-on-own-domain, logo, favicon,
  Organization.logo, directory/review-site listings, email capture and Google Business Profile.
* **Coverage & discoverability rules** (from crawl × Search Console): pages that earn nothing, staging/preview hosts
  leaking into Google, pages Google knows that the site never links to, missing hreflang on multilingual sites,
  keyword cannibalization, branded-search defense, missing competitor comparison pages, and missing analytics/conversion
  tracking. Each rule states its own limits — e.g. when a crawl stopped at its URL cap it says so instead of claiming
  pages are unreachable.
* **Fix once** — website/content/conversion fixes with the affected pages listed, verified as resolved by the next crawl
  (items disappear automatically; they reopen if the problem returns).
* **Keep doing** — weekly article (topics from Search Console page-2 queries and AI prompts where the brand is absent,
  with outlines), weekly video (script beats), weekly community replies (real threads + search phrases), weekly backlink
  outreach (domains AI assistants actually cite + template), monthly competitor review and content refresh, daily mention replies.

Page-level signals (canonical, robots, JSON-LD, Open Graph, chat/phone/email links, email domains, logo, favicon, social profiles) are fetched for up to
8 key pages per crawl through the SSRF-safe client and parsed with selectolax — SiteOne's extra-column xpath only sees the
document body, so head-level facts cannot come from the crawler.

## AI referral traffic (added 2026-11-02)

GA4 session source/medium is matched against known AI assistant referrers (ChatGPT, Perplexity, Gemini, Copilot,
Claude …) plus GA4's own `ai-assistant` medium, giving the downstream half of AI visibility: *AI Search Visibility →
AI traffic*. It is a lower bound, since assistants that strip the referrer cannot be counted. Analytics now also feeds
outcome measurement (`ga_sessions`, `ga_conversions`, `ga_conversion_rate`, `ga_revenue`) and the AI analyst
(`get_analytics` tool).

## Accounts, assignment and the content studio (added 2026-11-02)

* **Accounts**: `users` with PBKDF2-SHA256 passwords (stdlib, no extra dependency), opaque session tokens stored as
  hashes and revocable, first admin bootstrapped from `ADMIN_EMAIL`/`ADMIN_PASSWORD`. `APP_AUTH_TOKEN` remains a
  system principal for scripts.
* **Membership**: `project_members` with owner/editor/viewer. Admins see every project, members only theirs, viewers
  cannot mutate. Enforced in `get_project` / `get_editable_project`, so every project-scoped route inherits it.
* **Assignment**: checklist items carry `assignee_id` and `due_date`; admins and project owners assign anyone,
  everyone else can only claim items for themselves. Assignment survives plan regeneration.
* **Content studio**: `app/services/content_studio.py` turns a checklist topic into an article, social post or short
  video script using the project's AI provider, grounded in its Search Console query, competitors and AI-prompt data.
  Video output includes beats, a shot list and SRT captions. Rendering an actual MP4 is **not** bundled: ffmpeg pulls
  193 packages into the image, so the drafts document the open-source render path (ffmpeg/MoviePy + Piper or Coqui TTS)
  instead.

## Brand scorecard (added 2026-11-03)

`app/intelligence/scorecard.py` turns everything collected into three 0–100 indices and a revenue model.

| Index | What it answers | Main components (weights) |
|---|---|---|
| Brand Influence 品牌影响力 | Do people and machines already know this brand? | branded search demand .30, branded trend .15, AI mention rate .20, direct+AI visits .15, public mentions .10, brand assets .10 |
| Brand Competitiveness 品牌竞争力 | How strong is the position against the alternatives? | AI share of voice .25, non-branded clicks .25, site quality .15, content coverage .15, ranking quality .10, own-domain citations .10 |
| Monetization Readiness 变现能力 | Is this traffic set up to become revenue? | conversion rate .30, traffic scale .25, conversion setup .15, momentum .15, demand captured .15 |

Normalisation: `saturate(v, half)` for unbounded counts (capped below 100), linear ratio against a target for rates,
`50 ± 50 × change/0.5` for trends, and a linear map for average search position.

Honesty rules baked in: components with no data are excluded and weights renormalised; `coverage` is reported; an index
below 50% coverage publishes **no score** (only a clearly-labelled provisional value), so a single 100 on thin data can
never look like an A. The revenue model needs a user-supplied average order value, uses the measured conversion rate
when GA4 has key events (otherwise a stated assumption), and labels the valuation range as indicative only.

## One checklist (2026-11-03)

The rule engine existed twice: `rules.py` → `growth_opportunities` and `playbook.py` → `plan_items`, detecting the same
things (low CTR, striking distance, broken links) with separate thresholds. On a real project every opportunity was a
duplicate of a plan item. They are now merged onto `plan_items`:

* `rules.py`, `engine.py`, the opportunity routes/task and the `growth_opportunities` / `opportunity_history` tables are gone.
* Detections that only existed there — keyword gap, AI citing third parties, competitor gaining AI share, low-converting
  landing pages — were ported into `playbook._opportunity_rules`.
* Plan items gained `confidence`, `score_breakdown`, `origin`, `target_urls`, `target_keywords` and `history`, so the
  full priority audit (`impact × confidence × effort_factor`) and evidence trail live on the item the user works from.
* The AI analyst writes through `add_plan_item` into the same checklist; its items are tagged `origin="ai"` and are never
  auto-resolved by the rule engine.
* `action_records.plan_item_id` replaces `opportunity_id`, and **Track the result** on a checklist item creates the
  action with its target pages and keywords pre-filled — closing the Monitor → Act → Measure loop that was open before.

## Runs itself now (2026-11-03)

The product no longer depends on someone clicking buttons:

* **Default schedules** are seeded when a project is created and when its first primary domain is added
  (`app/services/onboarding.py`): Search Console + analytics daily, crawl + Lighthouse + competitor watch + AI
  visibility + plan rebuild weekly, mentions daily. First runs are staggered.
* **Instant first value**: adding a primary domain enqueues a crawl immediately (no external setup needed).
* **Notifications** (`notifications` table): weekly digest per project (Mondays 08:00 UTC) and failure alerts for
  autonomous jobs, shown in-app via a bell and emailed when SMTP is configured. Email sending is queued and retried
  by the worker; with no SMTP it degrades to in-app only.
* **Cost guardrail**: a per-project monthly AI-token budget (`app/services/usage.py`), enforced before every AI task
  and surfaced with a usage breakdown under Settings. 0 means unlimited.
* **Backups**: `scripts/backup.sh` dumps the database, the artifacts volume and `.env`, with retention; cron-ready.

## Scorecard v2 (2026-11-03)

* **Overall is a geometric mean (weakest-link)**, not an average: a weak dimension pulls the whole score down because
  the dimensions multiply in reality (no awareness x great conversion = no revenue); a genuinely zero dimension makes the overall 0. The response names the weakest link.
* **No AI double-counting**: AI model-knowledge is scored only once, as share of voice in Brand Competitiveness. Brand
  Influence dropped its AI mention-rate component and reweighted (branded demand/trend, direct+AI traffic, mentions, assets).
* **Traffic scale removed from Monetization**: that index is now pure readiness/efficiency (conversion rate, conversion
  setup, momentum, demand captured). Scale is an input to the other two indices and is handled by the multiplicative overall.
* **Provider-agnostic conversion-event item**: when analytics has traffic but zero conversions, the plan adds "Define a
  conversion event so results can be measured in money" (GA4 key event, Umami/Plausible/Matomo goal, or a server-side event).
* **Scope stated**: the card measures acquisition only; retention/LTV is explicitly out of scope.
* **Trend lines**: daily `scorecard_snapshots` drive per-index deltas, sparklines and a full history chart.

## Next increments

1. Optional video render service (separate ffmpeg image invoked over a shared volume) so Shorts can be produced end to end.
2. GA4 attribution to actions: per-landing-page conversion deltas as outcome measurements.
2. Surface AI-referral landing pages in the Growth Plan as content to keep current.
3. AI-based sentiment/intent classification of mentions and answers (through the analyst service).
3. Keyword import from Search Console into `keywords` and SERP/keyword-data adapter slot.
4. Per-user auth + API tokens; audit log.
5. OpenTelemetry traces for jobs and provider calls; usage/cost dashboard from `provider_usage`.
6. E-mail/Slack digests of new opportunities and competitor changes.

## Bing, AI crawler access and content extraction (added 2026-11-05)

Three integrations from `docs/integration-registry.csv`, chosen because each closed a gap the product already
implied but could not measure.

**Bing Webmaster Tools** (`bing_webmaster`, free, API key) is the second first-party search source, and the
measurable half of Copilot visibility since Copilot answers from Bing's index. Built against the JSON endpoint
only — the legacy SOAP/POX endpoints were retired 2026-08-31 and must not be added as a fallback.

It writes to its own `bing_search_observations` table rather than to `search_observations`, for two reasons worth
keeping in mind before anyone "simplifies" it: nothing that reads `search_observations` filters by provider, so a
second engine in that table would silently inflate every figure the product presents as Search Console data; and
Bing's shape differs — daily totals are per-date, but query and page figures are aggregates over Bing's own
rolling window with no country or device breakdown, so the rows are not interchangeable. The API reports the
aggregate window explicitly (`aggregate_window`) so an aggregate cannot be read as a daily figure. Google and
Bing are shown side by side and never summed. Synced daily, like Search Console.

**AI crawler access** (`app/services/ai_crawlers.py`) reads robots.txt during every crawl and reports which AI
crawlers it admits, stored on `crawl_runs.stats.ai_crawlers` and served at
`/seo/domains/{id}/ai-crawlers`. robots.txt is evaluated the way RFC 9309 says crawlers evaluate it — one group
per crawler chosen by longest user-agent prefix, longest path pattern wins, `Allow` breaks ties — and every
verdict carries the exact rule line it came from.

The distinction the feature turns on: blocking a *retrieval* crawler (OAI-SearchBot, Claude-SearchBot,
PerplexityBot …) removes the site from that assistant's citations and raises a plan item; blocking a *training*
crawler (GPTBot, CCBot, Google-Extended …) is a deliberate policy choice that costs no visibility and is reported
as context only, never as something to fix. An unreadable robots.txt (5xx, or a SPA catch-all returning HTML) is
the most severe case and has its own message, because crawlers read an unreachable robots.txt as "disallow
everything" while every page still loads fine in a browser. The card sits above the visibility numbers on AI
Search Visibility, since it is the first explanation for a brand absent from every answer.

Server-log parsing — the other half of registry row GEO-06 — is still not built, and crawler access is still not
equated with citation.

**Trafilatura** (`app/core/content_extract.py`) does main-content extraction behind a DOM fallback, so a page it
declines to parse falls back rather than coming back empty. Two callers:

* *Watched-page change detection* compared full page text, so cookie banners, testimonial carousels and
  related-post rails reported a change on most runs. It now compares main content only. Because the stored hash
  predates the new extractor, `changed` is decided by re-extracting the archived HTML and diffing, not by the
  hash — otherwise the first run after this change would have flagged every watched page.
* *RSS brand monitoring* read the feed `summary`, which publishers truncate, so a brand named in the third
  paragraph was never seen. Truncated items are now fetched and extracted, capped per run and switchable off.

Both still archive raw HTML as an artifact separately.
