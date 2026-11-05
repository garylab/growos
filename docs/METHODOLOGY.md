# AI search visibility — measurement methodology

**What we measure.** For each prompt in a project we call each configured AI provider's public API *N* times
(`samples_per_run`, default 3) and store every answer as a separate observation with: provider, model requested, model version
returned by the API, language/country instruction, temperature and tools, whether the provider used search grounding,
citations returned by the API, latency, token usage and the raw payload.

**Mention rate.** Share of samples (per prompt × provider, and aggregated) whose answer text contains the brand name or an alias
(case-insensitive, whole-word). Same for each competitor.

**Position.** Order of first appearance among tracked entities in the answer (1 = mentioned first). When the entity sits inside
a numbered or bulleted list we also record its list rank. These are *answer-structure* signals, not search rankings.

**Grounded vs non-grounded.** OpenAI `web_search`, Gemini Google Search grounding and Perplexity return citations; those
answers are flagged `grounded`. Non-grounded answers reflect model knowledge only. We compare like with like and show the
grounded count per prompt. "Own domain cited" is computed on grounded answers.

**Sentiment / intent.** Lexicon and keyword heuristics around the mention; labelled `lexicon` so users treat it as triage.

**Caveats, shown in the UI.**
* API responses do not reproduce the consumer ChatGPT, Gemini or Perplexity apps (different system prompts, tools, personalization).
* A single answer is not a ranking. Compare rates across repeated samples and across runs over time.
* Temperature and model updates change answers; model version is stored for every observation.
* Mention detection relies on names/aliases; add product names and common misspellings as aliases.
