# CLAUDE.md — Itinera

**This file is deliberately slim as of 2026-09-02.** It used to hold a
single sprawling decision log and architecture description; that content
now lives in four separate files, consolidated so each has one clear job:

- [`README.md`](README.md) — what the project is, how to run it.
- [`STATUS.md`](STATUS.md) — **read this first.** Current snapshot: what's
  live, what's paused, the next action, known blockers.
- [`decisions.md`](decisions.md) — what was decided, why, and when to
  revisit each decision.
- [`progress.md`](progress.md) — dated diary of what happened each
  session, including the specific bugs found and how they were fixed.

This file stays checked in — and stays short — specifically because
Claude Code auto-loads it as project instructions at the start of every
session. Read `STATUS.md` next, then `decisions.md` for anything you're
about to touch or reconsider.

## Operating principles

Apply these to every new tool/integration and every change, not just
where they're already in use. The reasoning and incidents behind each
one are in `decisions.md` and `progress.md` — these are the rules
themselves.

1. **Classify before anything expensive runs.** Gate new capabilities the
   same way `classify_intent` already gates itinerary generation — don't
   bolt them onto the main path unconditionally.
2. **Tools return small, flat, pre-aggregated JSON — never raw provider
   payloads.** A cost control once tokens cost real money, not just
   tidiness.
3. **Split client vs. tool.** Raw API wrapper (auth, retries, pagination)
   is a different layer from the LLM-facing tool function (shaped output,
   schema-described, never raises — returns `{"error": ...}`).
4. **Cache tool calls.** Same args within a short window should hit a TTL
   cache, not the live API again — required once running against
   rate-limited free tiers.
5. **Findings gathered once should serve the whole conversation, not be
   re-fetched per turn — and every consumer must actually read the
   cache.** Both halves (write *and* read) need checking explicitly for
   any new cached-findings feature.
6. **Never let the LLM do date arithmetic.** Inject `current_date` into
   every prompt as a fact; resolve relative expressions with real code.
7. **Don't let the model invent data it wasn't given.** Ground prompts in
   real fetched data when available; when it's not, actually try to fetch
   it before settling for "I don't know."
8. **Prefer MCP for new external tool integrations, when a trustworthy
   server exists** — but verify it's actually production-ready (not
   "experimental," not gated behind a preview program) before depending
   on it. See `decisions.md`'s Calendar and Maps entries for two real
   cases where this check said no.

## Constraints to keep in view

- **Budget is $0** unless explicitly told otherwise. Every new integration
  should be evaluated against a real, currently-live free tier — not a
  remembered one.
- Don't reorder the roadmap in `STATUS.md`/`decisions.md` without
  discussing it — the current order reflects real cost/risk tradeoffs,
  not arbitrary sequencing.
- If a session's direction starts drifting from what's in `STATUS.md`/
  `decisions.md` — scope creep, a re-litigated decision, a "shortcut"
  that contradicts a principle here — stop and re-read those files before
  continuing. If a request would meaningfully change scope, ask first.
