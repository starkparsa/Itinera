<!-- See TEMPLATE.md for the format this file follows. -->
# 2026-08-25 — Real weather, MCP research, and making the LLM presentation-safe

**One session, four connected threads: re-enabled the paused agent step,
researched and adopted an MCP-for-future-tools policy, built real per-day
weather from scratch (including two live fabrication/coverage bugs found
and fixed after shipping), and made the app survive a live demo by
escaping Gemini's brutal free-tier daily cap.** Full rationale for every
decision below lives in `CLAUDE.md`'s decision log — this file is the
narrative + the learnings that don't belong in a living architecture doc.

## Changes shipped

- **Agent tool-calling step re-enabled** (`agent_service.
  AGENT_TOOL_CALLING_ENABLED = True`) — currency conversion only, weather
  stays removed (see CLAUDE.md). Verified live: real Frankfurter call,
  correct grounded summary, correctly skipped when no budget was
  mentioned.
- **MCP adopted as the standard for future tool integrations** (new
  architecture principle #8 in CLAUDE.md) — Google shipped official
  managed MCP servers for Calendar and Maps in 2026; `google-genai` has
  experimental native MCP support. Maps decision reversed (OSM stack →
  Google Maps MCP, knowingly re-accepting a Google Cloud billing
  requirement). New Calendar decision row (official MCP server). No code
  changed — this was a docs-only architecture decision.
- **Real per-day weather forecast, built from scratch**: `date_resolver.py`
  (real-Python date extraction, no LLM) + `weather_service.py`
  (Open-Meteo geocode + forecast, deliberately *not* a Gemini tool — it's
  never a model judgment call, so it costs zero LLM tokens). New
  `Trip.start_date`/`weather_json`/`weather_fetched_at` columns,
  `DayWeatherOut` schema, Streamlit per-day display. Cached per-trip
  (3h TTL).
- **Fahrenheit added** alongside Celsius everywhere weather shows up —
  real Python arithmetic (`_celsius_to_fahrenheit`), never left for the
  model to convert.
- **LLM reliability overhaul**: `gemini-3.6-flash` → `gemini-3.5-flash-lite`
  (separate, unexhausted free-tier quota bucket) + a new automatic **Groq
  fallback** (`groq_service.py`) that only triggers on Gemini's specific
  429/quota error, scoped to `llm_service.py`'s core paths. Both
  live-verified end-to-end, including forcing the real fallback path with
  a real Groq call.
- **Weather threaded into conversational Q&A** — previously only the
  currency `agent_context` reached `answer_question`; the real forecast
  never did. Now `routers/trips.py`'s question branch looks up and
  includes it on every question turn.

## Bugs found & fixed

1. **Q&A fabricated wrong temperatures.** Asked "what outfits would you
   suggest based on the weather" for a real 104–108°F Austin forecast →
   got "high 70s to low 80s." Root cause: the real per-day forecast was
   never passed to `answer_question` at all — only the (unrelated)
   currency `agent_context` was. Fixed by threading `Trip.weather_json`
   into the Q&A grounding via new `weather_service.summarize_for_prompt`.
   Re-verified live with the exact reported prompt. 5 regression tests.
2. **"N days from now" silently produced no weather.** `date_resolver.py`
   only matched "in N days," not "N days from now" — a very natural
   phrasing that got completely missed, so the feature never activated
   and the model correctly (but unhelpfully) said it had no data. Not a
   fabrication bug — the honesty guardrail worked — but a real coverage
   gap. Fixed with an additional regex pattern. 3 regression tests.
3. **Gemma 4's structured output leaks a markdown fence past
   `response_schema`.** Found while evaluating it as a Gemini replacement:
   `response.parsed` came back `None` even with `response_schema` set,
   because the model appended a trailing ` ``` ` after valid JSON. Also
   didn't reliably follow "write ONLY days N through M" (returned 1 day
   of 3 asked for). Rejected as a candidate; not a code bug since Gemma 4
   was never shipped, but worth recording so it isn't re-tried blind.
4. **`llama-3.3-70b-versatile` no longer exists on Groq**, discovered only
   once a real API key was available to test with (404, "does not exist
   or you do not have access to it"). Swapped to `openai/gpt-oss-120b`,
   confirmed present via `client.models.list()`.
5. **GPT-OSS on Groq burned its whole token budget on invisible reasoning**
   at the default `reasoning_effort` — a plain "say OK" prompt with
   `max_tokens=20` came back empty, and a 3-day itinerary chunk request
   only returned 1 day. Same failure shape as `gemini-3.6-flash`'s
   thinking-token problem, same fix: `reasoning_effort="low"`.

## Key learnings

- **Gemini's free tier is metered per *model*, not per account, and the
  RPD cap varies wildly by model.** `gemini-3.6-flash`: 20 requests/day
  (confirmed live via a real 429 — this account genuinely hit it during
  normal dev/testing, not unusual load). `gemini-3.5-flash-lite`: enough
  headroom to answer while `3.6-flash` was still dead. Never trust a
  specific RPD number from a blog post — this session found several
  contradicting each other by 10-50x on the exact same model. Check the
  account's own behavior (or AI Studio's live quota page) instead.
- **Model/endpoint churn is constant across every provider touched this
  session**, not just Gemini: `gemini-2.5-flash`, `gemini-2.5-flash-lite`,
  and `gemini-2.0-flash` all 404 for new users now; `llama-3.3-70b-versatile`
  is gone from Groq's catalog. Always verify a model string is live
  (`client.models.list()`, or just try it) before hardcoding it,
  regardless of provider — this isn't a Gemini-specific problem.
- **A model claiming structured-output support doesn't mean
  `response.parsed` will actually populate.** Gemma 4 produced genuinely
  valid JSON *plus* a trailing fence character the SDK's auto-parser
  didn't tolerate. Always test with the exact schema shapes the app
  actually uses (nested objects, not just a 2-field example) — a small
  schema can work while a realistic one silently fails.
- **Reasoning models (Gemini 3.6, GPT-OSS on Groq) need their thinking
  budget explicitly minimized**, or a small `max_tokens` value gets
  consumed entirely by invisible reasoning tokens before any visible
  output. `thinking_config.thinking_level=MINIMAL` for Gemini,
  `reasoning_effort="low"` for GPT-OSS. Watch for this specific failure
  signature: an empty/truncated response with no error, or a chunked
  request that silently returns fewer items than asked for.
- **Docker Desktop in this dev sandbox drops between idle periods** and
  needs a manual relaunch + a ~1-2 minute wait for the daemon to respond
  again — happened three separate times this session. Not an app problem;
  don't assume a `docker compose` failure here means the compose file or
  images are broken.
- **`Base.metadata.create_all()` only creates missing tables, never alters
  existing ones.** Adding columns to `Trip` this session required
  `docker compose down -v` to actually pick them up in the local MySQL
  volume (fine for dev; would need real Alembic migrations in production).
- **`python-dotenv`'s default `load_dotenv()` searches from the calling
  file's own location, not the current working directory.** A verification
  script living outside the repo (this session's scratchpad) needs
  `load_dotenv(find_dotenv(usecwd=True))` or it silently loads nothing and
  every env-dependent call fails in a confusing way.
- **A real fabrication bug can hide behind an otherwise-correct honesty
  guardrail.** The Austin outfit question didn't get an "I don't have
  that" — it got a specific, wrong, confident-sounding number. The
  guardrail (principle #7) only works if the real data actually *reaches*
  the prompt in the first place; a new data source (weather) added
  alongside an existing one (currency) needs to be explicitly wired into
  every consumer, not just the one it was built for.

## Open items / follow-ups

- **Maps MCP pricing/free-tier/auth mechanism still unverified** — Google's
  announcement didn't disclose them. Confirm before writing any code
  against it (build order item 4).
- **Weather-via-MCP evaluation (community server vs. build-our-own) is
  still open** — the plain `weather_service.py` approach shipped instead,
  since weather turned out to never be a Gemini-invoked tool at all, so
  MCP's reason for existing didn't apply. Worth revisiting only if a
  future weather-adjacent feature *does* need to be LLM-invoked.
- **Destination-typo geocoding has no fuzzy-match fallback.** Not an
  active bug (Gemini's own destination extraction already normalizes most
  typos before geocoding runs), but a real latent gap if the model ever
  doesn't catch one. Not worth solving speculatively without a real case.
- **Groq fallback is scoped to `llm_service.py` only** — `agent_service.py`'s
  currency tool-calling step deliberately doesn't get it, since it already
  degrades gracefully to `""` on any failure. Revisit if that step's
  reliability ever becomes a real problem.
- **Alembic still isn't set up** — every schema change this session needed
  a full local DB wipe. Fine for solo dev at this scale; will need real
  migrations before this could handle a shared/production database without
  data loss on every schema change.
