"""Shared Gemini client construction, model name, and thinking-config.

Factored out of llm_service.py (2026-08-31 architecture review, Tier 2)
because agent_service.py's tool-calling loops need the exact same
client/model/thinking-config to call Gemini's function-calling API
directly (agent_service._call_gemini_with_tools bypasses llm_service's
_call_gemini/_call_gemini_chat entirely, since it needs the raw SDK
response to inspect response.function_calls). Before this module existed,
agent_service.py got these by importing llm_service and reaching into its
underscore-prefixed internals (llm_service._get_client(),
llm_service.GEMINI_MODEL, llm_service._THINKING_CONFIG) -- real coupling
across a module boundary that also happened to be the two ends of this
codebase's one circular import (llm_service imports agent_service for the
itinerary-planning gather step; agent_service imported llm_service right
back, for this and only this). Neither module owns Gemini client
construction now; both import it from here, and agent_service.py no
longer needs to import llm_service at all.

llm_service.py still re-exports GEMINI_MODEL/_THINKING_CONFIG/_get_client
as module-level names (see its own top, right below its imports) purely so
the existing test suite's `patch("app.llm_service._get_client", ...)`
call sites keep working unchanged -- this module is the single source of
truth either way; llm_service's names are aliases, not a second
definition.
"""
import os

from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# gemini-2.5-flash is no longer available to new API keys (confirmed live:
# it 404s, Google's own error message points at gemini-3.6-flash).
# gemini-3.6-flash itself was swapped out 2026-08-25 after hitting its
# free tier's hard 20-requests/*day* cap live (RESOURCE_EXHAUSTED,
# GenerateRequestsPerDayPerProjectPerModel-FreeTier) -- disqualifying for
# anything that needs to survive a live demo. gemini-3.5-flash-lite is a
# separate model in Google's quota system (answered successfully while
# gemini-3.6-flash's daily cap was still exhausted) and was verified live
# to match on every axis that mattered: clean response_schema output (no
# markdown-fence leakage), correct start_day/end_day chunk-range
# instruction-following, and correct function-calling behavior (calls
# convert_currency when useful, doesn't over-call when not). See
# CLAUDE.md's decision log for the comparison against Gemma 4, which was
# tried first and rejected -- its structured output leaked a trailing
# ```` ``` ```` fence past response_schema and it didn't reliably follow
# the day-range instruction. Re-verify at
# ai.google.dev/gemini-api/docs/models before changing this again --
# model strings and deprecations move fast, gemini-2.5-flash-lite (an
# earlier candidate) already 404s for new users as of this change.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# gemini-3.6-flash was a reasoning model with an internal "thinking" token
# budget that's spent out of the same max_output_tokens budget as the
# visible answer -- confirmed live: leaving thinking at its default consumed
# an entire small max_output_tokens budget on invisible reasoning tokens,
# producing an empty response.text. MINIMAL keeps these calls fast, cheap,
# and deterministic (verified live: produces no thinking tokens at all) --
# appropriate for classification/extraction/structured generation and even
# for conversational Q&A here, since QUESTION_SYSTEM_PROMPT is already
# explicit/directive rather than relying on the model's own deliberation.
# Also confirmed harmless (no error, no behavior change) on
# gemini-3.5-flash-lite, which isn't itself a reasoning model in the same
# sense -- kept for consistency and as cheap insurance if that changes.
THINKING_CONFIG = types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)

_client: genai.Client | None = None


def get_client() -> genai.Client:
    """Constructed lazily (not at import time) so importing this module
    never fails just because GEMINI_API_KEY isn't set -- e.g. the test
    suite imports it without a real key, since every Gemini call is
    mocked at a higher level (llm_service._call_gemini/_call_gemini_chat,
    or agent_service._call_gemini_with_tools), never reaching this."""
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=180_000,  # milliseconds
                retry_options=types.HttpRetryOptions(attempts=3, initial_delay=1.0, max_delay=5.0),
            ),
        )
    return _client
