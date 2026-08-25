"""Fallback LLM provider, used only when Gemini fails specifically because
its request quota is exhausted (see llm_service.py's _is_rate_limited).
Groq's free tier -- 30 RPM / 6,000 TPM / 14,400 requests/day, no card, no
expiry -- is roughly 700x the 20-requests/day free-tier cap that actually
got hit on `gemini-3.6-flash` (see CLAUDE.md decision log), so it's real
headroom for a live demo rather than a second thing that can also run out
mid-presentation.

Deliberately mirrors llm_service.py's _call_gemini/_call_gemini_chat
contract exactly -- same inputs, same outputs (a parsed Pydantic instance
or plain text) -- so the fallback in llm_service.py is a drop-in second
call, not a rewrite of caller logic.

Uses the `openai` SDK pointed at Groq's OpenAI-compatible endpoint rather
than a hand-rolled HTTP client (principle #3: don't reinvent a wrapper
that already exists). Model is deliberately NOT Gemma 4, despite it also
being servable via Groq -- live testing found real problems (a trailing
markdown fence breaking strict JSON parsing, and unreliable adherence to
"write only days N-M" chunk instructions; see CLAUDE.md decision log) --
a large, well-established instruction-following model is used instead.
"""
import os

from openai import OpenAI
from pydantic import BaseModel

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# llama-3.3-70b-versatile (this row's original pick) is confirmed gone from
# Groq's catalog as of 2026-08-25 (live 404, "does not exist or you do not
# have access to it") -- same model-churn pattern already seen with Gemini.
# openai/gpt-oss-120b verified live in its place: a large, strong
# instruction-following open-weight model, actually present in this
# account's live model list (client.models.list()). Re-verify against
# console.groq.com/docs/models (or list your own account's models) before
# changing this again -- same "these move" discipline as GEMINI_MODEL.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Constructed lazily so importing this module never fails just
    because GROQ_API_KEY isn't set -- mirrors llm_service._get_client."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    return _client


def _reasoning_kwargs() -> dict:
    """GPT-OSS models (openai/gpt-oss-20b, openai/gpt-oss-120b) are
    reasoning models with a hidden "thinking" token budget spent before the
    visible answer -- confirmed live: at the default reasoning_effort
    ("medium"), a small max_tokens budget was consumed entirely by
    invisible reasoning, producing an empty response and, separately, a
    multi-day chunk request that only returned 1 of 3 days. "low" mirrors
    the exact fix already applied to Gemini's thinking_config=MINIMAL for
    the same underlying problem. Only sent for gpt-oss models -- Groq
    rejects/ignores this parameter for models that don't support it, so it
    shouldn't be sent blindly if GROQ_MODEL is ever changed to something
    else."""
    if "gpt-oss" in GROQ_MODEL:
        return {"reasoning_effort": "low"}
    return {}


def _strip_markdown_fence(text: str) -> str:
    """Some models wrap JSON output in a ``` fence even when explicitly
    asked for JSON-only output -- confirmed live with Gemma 4 (see
    CLAUDE.md decision log). Not required for the current Groq model in
    testing so far, but cheap insurance before handing text to Pydantic
    rather than a second unexplained failure mode."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _call_groq(
    prompt: str, response_schema: type[BaseModel] | None = None, max_output_tokens: int = 800,
) -> str | BaseModel:
    """Mirrors llm_service._call_gemini's contract exactly. Raises on
    failure (network, schema mismatch, etc.) -- the caller (llm_service.py)
    is responsible for combining this with the original Gemini failure
    into one descriptive error if this also fails."""
    kwargs = {}
    if response_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema.__name__,
                "schema": response_schema.model_json_schema(),
                # Groq's strict mode requires every property to be listed
                # as required, which doesn't match this app's schemas
                # (e.g. ChunkItineraryItem.notes is optional) -- best-effort
                # + manual Pydantic validation below instead of fighting
                # that mismatch.
                "strict": False,
            },
        }

    response = _get_client().chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_output_tokens,
        **_reasoning_kwargs(),
        **kwargs,
    )
    text = (response.choices[0].message.content or "").strip()

    if response_schema is None:
        return text
    return response_schema.model_validate_json(_strip_markdown_fence(text))


def _call_groq_chat(
    system_instruction: str, chat_messages: list[dict], prompt: str, max_output_tokens: int = 600,
) -> str:
    """Mirrors llm_service._call_gemini_chat's contract exactly."""
    messages = [{"role": "system", "content": system_instruction}]
    for m in chat_messages:
        role = "assistant" if m["role"] == "assistant" else "user"
        messages.append({"role": role, "content": m["content"]})
    messages.append({"role": "user", "content": prompt})

    response = _get_client().chat.completions.create(
        model=GROQ_MODEL, messages=messages, max_tokens=max_output_tokens, **_reasoning_kwargs(),
    )
    return (response.choices[0].message.content or "").strip()
