<!--
Copy this file to a new one named YYYY-MM-DD-short-slug.md for each session
(or each distinct chunk of work within a long session), fill it in, then add
one row for it to README.md's index table, newest first.

Keep this doc to "what happened and why it matters," not a transcript --
CLAUDE.md is still the single source of truth for current architecture and
decisions; link to it rather than re-explaining. This file's job is the
*history* CLAUDE.md doesn't keep: what changed this session, what broke and
why, and what was learned that isn't obvious from reading the code.
-->
# YYYY-MM-DD — Session title

**One-sentence summary of what this session was about.**

## Changes shipped

- What changed, file(s) touched, and *why* in one line each. Link to
  CLAUDE.md's decision log instead of repeating the full rationale there.

## Bugs found & fixed

- Symptom (what was actually observed/reported) → root cause → fix.
  Include the regression test name if one was added.

## Key learnings

- Anything discovered by actually running the code that wouldn't be
  obvious from reading it -- API quirks, free-tier numbers, model
  deprecations, environment gotchas. This section is the most valuable
  part of this file for future sessions; be concrete (real numbers, real
  error messages), not vague ("APIs can be unreliable").

## Open items / follow-ups

- Things flagged but deliberately not done this session, and why not
  (scope, budget, missing info). Check CLAUDE.md's decision log too --
  some of these may already be recorded there in more detail.
