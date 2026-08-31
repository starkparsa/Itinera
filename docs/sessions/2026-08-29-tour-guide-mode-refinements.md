# 2026-08-29 — Tour guide mode: activation ack, brief-by-default, accent color

**Three user-requested refinements to persistent tour-guide mode: a
deterministic one-time "Tour guide mode on." acknowledgment, replies
defaulting to brief summaries again instead of forced-detailed, and a real
UI accent color swap while active.**

## Changes shipped

- `backend/app/routers/trips.py`: captures `activating_tour_guide`
  (`tour_guide_requested and not conversation.tour_guide_mode`, read
  before the mutation) and prepends a fixed `"Tour guide mode on. "`
  string to `reply_text` in Python when true — not an LLM instruction.
  Works identically whether the reply came from the tools loop or the
  plain fallback.
- `backend/app/agent_service.py`: `answer_question_with_tools`'s
  `tour_guide_mode` branch no longer forces `detail="detailed"` on every
  later turn. Now: stay in the tour-guide persona, default to brief +
  a touch of relevant history, escalate to `detail="detailed"` only when
  *that turn's own wording* explicitly asks to go deeper — and not
  sticky, each new question judged fresh.
- `backend/app/schemas.py` / `routers/conversations.py`: `tour_guide_mode`
  is now on `ConversationDetail` (conversation-level, not `TripResponse`
  — a question turn's assistant `Message` has no `trip_id` at all).
- `frontend/src/lib/types.ts`, `components/ChatApp.tsx`: mirror the new
  field; new `tourGuideMode` state set from `loadConversation`/reset in
  `startNewChat`; `data-tour-guide-mode="true"` on the root wrapper.
- `frontend/src/app/globals.css`: `[data-tour-guide-mode="true"]`
  overrides `--primary`/`--ring`/`--sidebar-primary`/`--sidebar-ring` to
  an amber accent (Tailwind's amber-700/400 oklch stops), mirrored in the
  existing dark-mode media query. No new dependency, no per-component
  changes needed.
- Tests: updated `test_qa_tools_folds_tour_guide_mode_note_into_system_instruction`
  for the new brief-by-default phrasing; extended the existing
  `test_tour_guide_mode_persists_across_question_turns_and_clears_on_edit_trip`
  with assertions on the exact acknowledgment prefix (present once, not
  repeated) and on `GET /conversations/{id}`'s `tour_guide_mode` field
  (True then False). Full suite: 222 passed, `ruff check` clean.

## Follow-up bug fix, same day: activation turn recapping the whole itinerary

User reported the activation turn (a bare "be my tour guide", no place
named) returned a full multi-paragraph, day-by-day recap of an entire
5-day Miami itinerary instead of a short welcome. Root cause:
`QA_TOOL_SYSTEM_PROMPT` listed "be my tour guide" itself alongside genuine
escalation phrases ("tell me the full history", "give me more detail") as
a trigger for `detail="detailed"` — so *activating the persona* was being
read as *asking for maximum detail on the whole trip*.

Fixed in `backend/app/agent_service.py`: dropped "be my tour guide" from
that trigger list (the phrase now affects persona/voice only, per the
design above -- not detail level) and added an explicit instruction that
a tour-guide request with no specific place named should get a short,
friendly welcome inviting the user to pick a stop, not a recap of every
day already in the conversation. New regression test,
`test_qa_system_prompt_does_not_treat_be_my_tour_guide_as_a_detail_trigger`.
Full suite: 223 passed, `ruff check` clean.

Live-verified against the exact reported shape (a real 5-day Miami
itinerary generated first, then a bare "be my tour guide"): reply dropped
from a multi-paragraph day-by-day recap to a 284-character welcome ending
in a question. Checked for over-correction too — a same-conversation
follow-up naming a specific place ("Tell me about South Beach") still got
a real, grounded, brief answer (575 characters, using `get_place_context`
in brief mode), confirming the fix didn't make the model refuse to answer
actual place questions.

## Bugs found & fixed (environment, not this feature)

- **A real backend server was silently serving stale code for an unknown
  length of time.** `uvicorn --reload`'s reloader supervisor process had
  apparently already been killed at some earlier point this session, but
  its spawned worker child kept running as an orphan (inherited the
  listening socket), so it kept answering requests — with `--reload`'s
  watcher gone, it would never pick up further file changes. First live
  verification attempt against "the already-running dev server" returned
  `tour_guide_mode: null` for a brand-new conversation, which should be
  structurally impossible for a required `bool` field — traced to this,
  not a code bug. Fixed by identifying and force-killing the orphaned
  child (`Get-CimInstance Win32_Process` to find it, since `Get-Process`
  on the parent's old PID reported nothing) and starting a fresh instance
  through `preview_start`/`.claude/launch.json` instead of an untracked
  background shell process, specifically so its logs stay inspectable.
- **The shared dev MySQL instance is currently rejecting its own
  configured credentials** (`travel_user`@`localhost`, real `ERROR 1045`
  confirmed directly via the `mysql` CLI, independent of any Python/app
  code) — a pre-existing environment issue, unrelated to this session's
  changes, not touched or "fixed" here (didn't want to unilaterally
  reset a local DB password). Live verification used a scratch
  SQLite-backed instance instead (`DATABASE_URL` override, matching the
  pattern from the 2026-08-27 tour-guide-mode verification session).
  Flagging for the user to look at separately.

## Key learnings

- `uvicorn --reload` orphaning a worker process when its parent is killed
  is a real Windows-specific failure mode worth remembering: `taskkill`
  reporting success on the parent PID does not guarantee the process tree
  is actually gone, and the orphan will keep serving traffic on the same
  port indefinitely with no further reloads. When in doubt, verify with
  `Get-CimInstance Win32_Process` (to see full command lines, not just
  PIDs) rather than trusting `netstat`'s reported owning PID at face
  value.
- On Windows, a `sqlite:////path` URL built from a Git-Bash-style
  `/tmp/...` path silently fails for a native Windows Python process
  ("unable to open database file") — needs a real Windows absolute path
  (e.g. under the scratchpad directory) in the SQLite URL instead.

## Open items / follow-ups

- The dev MySQL credential rejection above is unresolved — needs the user
  to check the local `MySQL80` service's actual grants/password for
  `travel_user`, not something to guess-fix from here.
- `llm_service.answer_question()` (the plain, non-tool fallback used only
  when the tools loop itself returns `""`) still has no `tour_guide_mode`
  parameter at all, so a reply on that rare fallback path gets the
  Python-added acknowledgment prefix but not the persona/brief-history
  framing. Pre-existing, not introduced this session, not fixed — none of
  the three requested changes needed it.
