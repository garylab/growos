# Project: AI Customer Acquisition Intelligence Platform

Act as a senior software architect, full-stack engineer, AI engineer, and DevOps engineer.

Your task is to design and build a working first version of an AI-powered Customer Acquisition Intelligence Platform.

This is not a generic SEO dashboard or a collection of open-source tools.

The product's primary objective is:

**Help businesses acquire more customers and increase revenue by improving their organic search visibility, AI search visibility, brand presence, and competitive positioning.**

The product should continuously:

Monitor → Analyze → Identify Opportunities → Recommend Actions → Measure Results.

## 1. Product Scope

Build the following four core modules.

### A. SEO Intelligence

Monitor and analyze a business website.

Capabilities:
- Website crawling and sitemap discovery.
- Technical SEO auditing.
- Broken links and redirect detection.
- Title, meta description, canonical and heading analysis.
- Duplicate content and missing metadata detection.
- Internal link analysis.
- Page-level SEO scores and issues.
- Google Search Console integration.
- Search impressions, clicks, CTR and average position.
- Keyword and landing-page performance.
- Historical snapshots and change detection.

Integrations:
- SiteOne Crawler: primary crawling and audit engine.
- Google Lighthouse: page performance and technical checks.
- Google Search Console API: first-party search performance.
- Chrome UX Report API: optional field performance data.

Do not unnecessarily rebuild functionality already provided by these tools.

### B. GEO / AI Search Visibility

Monitor how brands and competitors appear in AI-generated answers.

Initial AI providers:
- OpenAI API.
- Google Gemini API.
- Perplexity API (optional, through an adapter).

Capabilities:
- Create and manage a collection of search prompts.
- Organize prompts by intent, topic, language and country.
- Run prompts against multiple AI providers.
- Extract brand and competitor mentions.
- Detect recommendation positions where meaningful.
- Extract cited URLs and domains.
- Identify which websites and sources influence AI answers.
- Track brand visibility over time.
- Compare competitors' visibility.
- Track sentiment and answer context.
- Detect changes in AI-generated answers.

Important:
- Run repeated samples for each prompt.
- Store model, model version, provider, locale, timestamp and request configuration.
- Distinguish grounded answers from non-grounded answers.
- Do not treat one AI response as a definitive ranking.
- Do not claim that API responses exactly reproduce consumer ChatGPT, Gemini or Perplexity experiences.
- Make the measurement methodology transparent.

### C. Brand & Competitor Intelligence

Monitor brand mentions and competitor activity.

Potential integrations:
- Harken.
- OpenMagpie.
- Reddit API.
- Hacker News API.
- YouTube Data API.
- RSS / Atom feeds.
- Bluesky API.
- Selected Mastodon instances.

Capabilities:
- Brand mention monitoring.
- Competitor mention monitoring.
- Topic and sentiment classification.
- Relevant discussion discovery.
- Potential customer intent detection.
- Competitor website and pricing-page change detection.
- Source URL and evidence tracking.

Do not implement unauthorized scraping of social platforms.

Start with RSS, Hacker News and one validated monitoring integration. Keep all other sources modular.

### D. Growth Opportunity Intelligence

This is the most important proprietary module.

The system should combine data from SEO, GEO, brand monitoring, competitor intelligence and analytics to identify actionable growth opportunities.

Examples:
- High impressions but low CTR.
- Pages ranking near the top of page two.
- Important keywords not covered by existing pages.
- Competitors appearing in AI answers while the tracked brand is absent.
- AI answers citing third-party websites instead of the brand's own website.
- Important pages with technical SEO problems.
- Competitors gaining visibility for relevant topics.
- Customer discussions indicating unmet needs.
- Landing pages receiving traffic but generating few conversions.

Every opportunity must contain:
- Title.
- Description.
- Supporting evidence.
- Source data references.
- Potential business impact.
- Confidence level.
- Estimated implementation effort.
- Priority score.
- Recommended next action.
- Status and history.

Use a transparent scoring model.

Do not generate generic AI advice without supporting evidence.

The AI should explain why an opportunity exists and what evidence supports the recommendation.

## 2. Technology Stack

Use the following stack unless the existing repository has a strong technical reason to differ.

Frontend:
- React.
- TypeScript.
- Vite.
- Tailwind CSS.
- shadcn/ui.
- React Router.
- TanStack Query.
- Zustand.
- Recharts.

Backend:
- Python.
- FastAPI.
- SQLAlchemy 2.
- Alembic.
- PostgreSQL.

Background processing:
- Independent Python Worker.
- PostgreSQL-backed task queue initially.
- APScheduler for recurring scheduling only.
- Abstract the queue behind a TaskQueue interface.

Infrastructure:
- Docker Compose.
- Caddy for reverse proxy and HTTPS where required.
- Local persistent storage for raw artifacts.
- Structured logging.
- OpenTelemetry instrumentation where useful.

Testing:
- pytest.
- Playwright.
- Integration tests for external providers.
- Mock providers only in tests.

## 3. Architecture Principles

The system must be modular and provider-independent.

Create provider adapters for:
- Crawling.
- Search performance.
- SERP and keyword data.
- AI model providers.
- Brand monitoring.
- Website analytics.

A provider should be replaceable without rewriting the business logic.

Suggested adapter interface:

- health_check()
- collect()
- normalize()
- estimate_usage()
- get_capabilities()

Separate:
1. Raw external data.
2. Normalized business data.
3. AI-generated analysis.
4. Growth opportunities.
5. User actions.
6. Outcome measurements.

Preserve data provenance.

For every collected record, store relevant information such as:
- Provider.
- Source ID.
- Collection timestamp.
- Locale.
- Country.
- Language.
- Model/version where applicable.
- Raw payload reference.
- Normalized data.
- Confidence or measurement type.

Never confuse estimated third-party metrics with first-party observed metrics.

## 4. Data Model

Design a normalized PostgreSQL schema.

At minimum, consider:

- Project
- Domain
- ProviderConnection
- CollectionJob
- RawArtifact
- PageSnapshot
- AuditFinding
- SearchObservation
- Keyword
- PromptDefinition
- AIAnswerObservation
- BrandMention
- CompetitorObservation
- AnalyticsEvent
- GrowthOpportunity
- ActionRecord
- OutcomeMeasurement
- ProviderUsage

Support historical records instead of overwriting previous observations.

All background jobs should support:
- Status.
- Progress.
- Retry.
- Cancellation.
- Error messages.
- Execution logs.
- Idempotency.

## 5. AI Architecture

Start with one central AI analysis service using tool calling.

Do not introduce a complex multi-agent framework in the first version.

Support:
- OpenAI-compatible APIs.
- OpenAI API.
- Gemini API.
- Ollama or other local models where practical.

The AI should have access to normalized application data through controlled tools.

Examples:
- get_seo_findings()
- get_search_performance()
- get_ai_visibility()
- get_brand_mentions()
- get_competitor_changes()
- create_growth_opportunity()
- update_action_status()

AI-generated conclusions must reference actual records and evidence.

Do not invent data when integrations have not been configured.

## 6. User Experience

Build a clean, professional B2B SaaS-style interface.

Main navigation:

1. Overview
2. SEO Intelligence
3. AI Search Visibility
4. Brand Intelligence
5. Competitors
6. Growth Opportunities
7. Actions & Results
8. Integrations
9. Settings

Overview should answer:

- How visible is my brand?
- How am I performing in traditional search?
- How visible am I in AI search?
- Which competitors are gaining visibility?
- What are my biggest acquisition opportunities?
- What should I do next?
- Are previous optimization actions producing results?

Prioritize useful information over decorative charts.

Every metric should have a clear definition and data source.

## 7. Deployment

The initial product is local-first and On-Prem-ready.

Provide a complete Docker Compose deployment containing:

- Frontend.
- Backend API.
- Worker.
- PostgreSQL.
- Caddy where needed.

Requirements:
- One-command startup.
- Persistent database and artifact storage.
- Environment-based configuration.
- API key management.
- Database migrations.
- Health checks.
- Backup and restore documentation.
- No unnecessary public ports.
- No secrets committed to Git.

The application must work locally without requiring a cloud-hosted backend.

External APIs should be configurable. Support customer-owned API keys.

## 8. Security

Pay particular attention to crawler security.

Prevent:
- SSRF.
- Localhost access.
- Private IP access.
- Cloud metadata access.
- DNS rebinding.
- Redirect-based SSRF bypass.
- Access to internal services.

Also implement:
- Secret encryption or secure secret references.
- OAuth token protection.
- Input validation.
- Rate limiting where appropriate.
- Secure logging without credentials or sensitive payloads.

## 9. Development Strategy

Do not attempt to implement everything at once.

Work in the following phases.

### Phase 0 — Repository inspection and architecture

First inspect the existing repository.

Do not overwrite or replace existing working code without understanding it.

Produce:
- Architecture proposal.
- Directory structure.
- Database design.
- Integration plan.
- Implementation roadmap.
- Identified risks.

Then proceed with implementation unless a genuinely blocking decision requires clarification.

### Phase 1 — Functional foundation

Implement:
- Frontend and backend foundation.
- PostgreSQL schema and migrations.
- Project and domain management.
- Provider configuration.
- Background job system.
- Docker Compose deployment.
- Basic overview dashboard.

The application must start and work end-to-end.

### Phase 2 — SEO Intelligence

Integrate:
- SiteOne.
- Lighthouse.
- Google Search Console.

Implement actual crawling, auditing, data ingestion and historical records.

### Phase 3 — GEO Intelligence

Integrate:
- OpenAI API.
- Gemini API.

Implement prompt management, repeated sampling, answer analysis, brand mentions, competitor mentions and citation extraction.

### Phase 4 — Growth Opportunity Engine

Combine SEO and GEO data.

Generate evidence-backed opportunities with transparent scoring, recommended actions and status tracking.

### Phase 5 — Brand Intelligence and Measurement

Add validated brand monitoring integrations.

Connect website analytics and track traffic, leads and conversion-related outcomes.

## 10. Engineering Rules

- Write production-oriented code, not throwaway demos.
- Do not build fake integrations.
- Do not use hardcoded sample data in production views.
- Do not silently substitute mock data when an API key is missing.
- Clearly show integration status and missing configuration.
- Avoid unnecessary dependencies.
- Pin important dependency versions.
- Respect open-source licenses and third-party API terms.
- Use adapters instead of tightly coupling providers.
- Write tests for important business logic.
- Document setup and configuration.
- Keep the system easy to maintain and extend.

Do not deploy multiple overlapping open-source products simply because they exist.

Reuse mature tools for commodity functionality. Build our own unified data model, intelligence layer, opportunity engine and measurement workflow.

## 11. First Delivery Requirements

The first delivery should be a working internal alpha, not a collection of UI mockups.

I should be able to:

1. Start the application using Docker Compose.
2. Create a project and add my website.
3. Configure API credentials.
4. Run an actual website crawl.
5. View real SEO audit results.
6. Connect Google Search Console.
7. Run AI visibility prompts through OpenAI and Gemini.
8. View brand and competitor mentions in the collected answers.
9. Generate growth opportunities supported by real evidence.
10. Create and track optimization actions.
11. Compare historical observations.

Use Hirelala and MockReal as initial test websites, but do not hardcode their domains into the application.

At the end of each phase:
- Run tests.
- Fix failures.
- Update documentation.
- Report completed functionality.
- Report incomplete integrations and limitations.
- Provide exact commands to run and verify the application.

Start by inspecting the repository and producing the implementation plan. Then implement Phase 1 and continue in small, verifiable increments.
