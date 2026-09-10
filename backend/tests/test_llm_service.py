from unittest.mock import Mock, patch

import pytest
from google.genai import errors as genai_errors

from app import llm_service
from app.llm_service import (
    ChunkItineraryDay,
    ChunkItineraryItem,
    ConversationTitleResult,
    IntentResult,
    ItineraryChunk,
    TripMeta,
)


@pytest.fixture(autouse=True)
def mock_agent_context():
    # Every test in this file exercises the itinerary pipeline in isolation.
    # Without this, generate_itinerary's calls to
    # agent_service.gather_trip_context, agent_service.gather_place_
    # context_for_itinerary, and agent_service.gather_named_place_pool
    # would make real network calls to Gemini/Google Places during tests.
    with (
        patch("app.llm_service.agent_service.gather_trip_context", return_value=""),
        patch("app.llm_service.agent_service.gather_place_context_for_itinerary", return_value=("", [])),
        patch("app.llm_service.agent_service.gather_named_place_pool", return_value=("", [])),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_conversation_title():
    # Shadows conftest.py's own autouse fixture of the same name (pytest
    # resolves the closest-scoped fixture first) -- that one stubs
    # generate_conversation_title itself, a sane default for every OTHER
    # test file that just wants conversation creation to not make a real
    # Gemini call for a title it doesn't care about. This file's own tests
    # test generate_conversation_title's actual internals directly, so
    # that stub would make them meaningless (every call would return the
    # stub's canned answer regardless of how _call_gemini is mocked). A
    # no-op override for this file only.
    yield


def _chunk(day_activity_pairs: list[tuple[int, str]]) -> ItineraryChunk:
    """Builds an ItineraryChunk from (day_number, activity) pairs -- a
    shorthand for the common case of one activity per day in these tests."""
    return ItineraryChunk(days=[
        ChunkItineraryDay(day_number=day, items=[ChunkItineraryItem(activity=activity)])
        for day, activity in day_activity_pairs
    ])


def test_short_trip_makes_one_meta_call_and_one_chunk_call():
    meta = TripMeta(destination="Kyoto", total_days=3)
    chunk = ItineraryChunk(days=[
        ChunkItineraryDay(day_number=1, items=[ChunkItineraryItem(time_of_day="morning", activity="Fushimi Inari")]),
        ChunkItineraryDay(day_number=2, items=[ChunkItineraryItem(time_of_day="morning", activity="Arashiyama")]),
        ChunkItineraryDay(day_number=3, items=[ChunkItineraryItem(time_of_day="morning", activity="Nishiki Market")]),
    ])

    with patch("app.llm_service._call_gemini", side_effect=[meta, chunk]):
        result = llm_service.generate_itinerary("3 days in Kyoto")

    assert result["destination"] == "Kyoto"
    assert len(result["days"]) == 3
    assert result["days"][0]["items"][0]["activity"] == "Fushimi Inari"


def test_long_trip_is_split_into_multiple_chunk_calls():
    # 12 days at CHUNK_SIZE_DAYS=5 should produce 3 chunk calls (5, 5, 2).
    meta = TripMeta(destination="Italy", total_days=12)
    chunk1 = _chunk([(i, f"Day {i} activity") for i in range(1, 6)])
    chunk2 = _chunk([(i, f"Day {i} activity") for i in range(6, 11)])
    chunk3 = _chunk([(i, f"Day {i} activity") for i in range(11, 13)])

    with patch("app.llm_service._call_gemini", side_effect=[meta, chunk1, chunk2, chunk3]) as mock_call:
        result = llm_service.generate_itinerary("12 days touring Italy")

    assert len(result["days"]) == 12
    assert result["days"][-1]["day_number"] == 12
    assert mock_call.call_count == 4  # 1 meta call + 3 chunk calls


def test_explicit_requested_days_overrides_model_inference():
    meta = TripMeta(destination="Peru", total_days=7)  # model guesses wrong
    chunk1 = _chunk([(i, "hike") for i in range(1, 6)])
    chunk2 = _chunk([(i, "hike") for i in range(6, 11)])

    with patch("app.llm_service._call_gemini", side_effect=[meta, chunk1, chunk2]):
        result = llm_service.generate_itinerary("trip to Peru", requested_days=10)

    assert len(result["days"]) == 10


def test_requested_days_beyond_cap_is_clamped_with_note():
    meta = TripMeta(destination="World Tour", total_days=7)
    # MAX_TOTAL_DAYS=60 -> 12 chunk calls of 5 days each
    chunks = [_chunk([(i, "explore") for i in range(s, min(s + 5, 61))]) for s in range(1, 61, 5)]

    with patch("app.llm_service._call_gemini", side_effect=[meta, *chunks]):
        result = llm_service.generate_itinerary("a 100 day round the world trip", requested_days=100)

    assert len(result["days"]) == 60
    assert "note" in result
    assert "60" in result["note"]


def test_invalid_meta_falls_back_to_defaults():
    # Simulates _call_gemini failing on the meta call (e.g. the model's
    # output didn't validate against TripMeta) -- _infer_trip_meta must
    # degrade to defaults rather than blow up the whole request.
    chunk1 = _chunk([(i, "explore") for i in range(1, 6)])
    chunk2 = _chunk([(i, "explore") for i in range(6, 8)])

    with patch("app.llm_service._call_gemini", side_effect=[RuntimeError("schema mismatch"), chunk1, chunk2]):
        result = llm_service.generate_itinerary("somewhere vague")

    assert result["destination"] == "Unknown"
    assert len(result["days"]) == 7  # DEFAULT_TOTAL_DAYS


def test_call_gemini_schema_mismatch_hints_truncation_when_max_tokens():
    # Regression test for the old _parse_json truncation hint, now living
    # inside _call_gemini itself: when response.parsed is None (the model's
    # output didn't validate against the schema) and the response was cut
    # off by the token budget, the error should say so, not just "invalid".
    fake_candidate = Mock(finish_reason="FinishReason.MAX_TOKENS")
    fake_response = Mock(parsed=None, text='{"days": [{"day_number": 1, "items": [{"activity": "Zilker', candidates=[fake_candidate])
    fake_client = Mock()
    fake_client.models.generate_content.return_value = fake_response

    with (
        patch("app.llm_service._get_client", return_value=fake_client),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service._call_gemini("prompt", response_schema=ItineraryChunk)

    assert "cut off" in str(exc_info.value)


# ---------- Groq fallback: only on Gemini's rate-limit failure ----------

def _rate_limit_error() -> genai_errors.ClientError:
    return genai_errors.ClientError(429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}})


def test_call_gemini_falls_back_to_groq_on_rate_limit():
    meta = TripMeta(destination="Reykjavik", total_days=3)

    with (
        patch("app.llm_service._get_client", side_effect=_rate_limit_error()),
        patch("app.llm_service.groq_service.GROQ_API_KEY", "fake-groq-key"),
        patch("app.llm_service.groq_service._call_groq", return_value=meta) as mock_groq,
    ):
        result = llm_service._call_gemini("prompt", response_schema=TripMeta)

    assert result == meta
    mock_groq.assert_called_once_with("prompt", TripMeta, 800)


def test_call_gemini_chat_falls_back_to_groq_on_rate_limit():
    with (
        patch("app.llm_service._get_client", side_effect=_rate_limit_error()),
        patch("app.llm_service.groq_service.GROQ_API_KEY", "fake-groq-key"),
        patch("app.llm_service.groq_service._call_groq_chat", return_value="Groq answered instead.") as mock_groq,
    ):
        result = llm_service._call_gemini_chat("system prompt", [], "a question")

    assert result == "Groq answered instead."
    mock_groq.assert_called_once()


def test_call_gemini_rate_limit_and_groq_also_fails_raises_combined_error():
    with (
        patch("app.llm_service._get_client", side_effect=_rate_limit_error()),
        patch("app.llm_service.groq_service.GROQ_API_KEY", "fake-groq-key"),
        patch("app.llm_service.groq_service._call_groq", side_effect=RuntimeError("groq is also down")),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service._call_gemini("prompt", response_schema=TripMeta)

    assert "groq is also down" in str(exc_info.value)


def test_call_gemini_non_rate_limit_error_does_not_fall_back_to_groq():
    # A schema mismatch, bad key, etc. must fail exactly as it always has --
    # falling back to Groq there would mask a real bug behind "well, Groq
    # answered", not just fill a genuine quota gap.
    not_found = genai_errors.ClientError(404, {"error": {"message": "not found", "status": "NOT_FOUND"}})

    with (
        patch("app.llm_service._get_client", side_effect=not_found),
        patch("app.llm_service.groq_service.GROQ_API_KEY", "fake-groq-key"),
        patch("app.llm_service.groq_service._call_groq") as mock_groq,
        pytest.raises(RuntimeError),
    ):
        llm_service._call_gemini("prompt", response_schema=TripMeta)

    mock_groq.assert_not_called()


def test_call_gemini_rate_limit_without_groq_key_does_not_fall_back():
    # No GROQ_API_KEY configured -- must raise the original Gemini message,
    # not attempt a Groq call that would fail confusingly on a missing key.
    with (
        patch("app.llm_service._get_client", side_effect=_rate_limit_error()),
        patch("app.llm_service.groq_service.GROQ_API_KEY", None),
        patch("app.llm_service.groq_service._call_groq") as mock_groq,
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service._call_gemini("prompt", response_schema=TripMeta)

    mock_groq.assert_not_called()
    assert "rate limit" in str(exc_info.value).lower()


def test_call_gemini_happy_path_never_calls_groq():
    fake_response = Mock(parsed=TripMeta(destination="Lisbon", total_days=4))
    fake_client = Mock()
    fake_client.models.generate_content.return_value = fake_response

    with (
        patch("app.llm_service._get_client", return_value=fake_client),
        patch("app.llm_service.groq_service._call_groq") as mock_groq,
    ):
        result = llm_service._call_gemini("prompt", response_schema=TripMeta)

    assert result.destination == "Lisbon"
    mock_groq.assert_not_called()


def test_agent_context_is_surfaced_in_result_and_prompt():
    meta = TripMeta(destination="Reykjavik", total_days=3)
    chunk = _chunk([(i, "sightsee") for i in range(1, 4)])

    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with (
        patch("app.llm_service.agent_service.gather_trip_context", return_value="Expect near-freezing temps; pack layers."),
        patch("app.llm_service._call_gemini", side_effect=_fake_call),
    ):
        result = llm_service.generate_itinerary("3 days in Reykjavik")

    assert result["agent_context"] == "Expect near-freezing temps; pack layers."
    # the context should have been folded into the chunk prompt (2nd call)
    assert "near-freezing" in captured_prompts[1]


def test_user_profile_note_is_folded_into_the_chunk_prompt():
    meta = TripMeta(destination="Lisbon", total_days=3)
    chunk = _chunk([(i, "explore") for i in range(1, 4)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary(
            "3 days in Lisbon", user_profile_note="pace: relaxed; interests: food, museums",
        )

    # Not in the meta prompt (1st call) -- destination/length inference has
    # no use for it; must be in the chunk prompt (2nd call).
    assert "relaxed" not in captured_prompts[0]
    assert "relaxed" in captured_prompts[1]
    assert "food, museums" in captured_prompts[1]


def test_empty_user_profile_note_adds_nothing_to_the_prompt():
    meta = TripMeta(destination="Lisbon", total_days=3)
    chunk = _chunk([(i, "explore") for i in range(1, 4)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary("3 days in Lisbon")

    # Not "stated preferences" generically -- PACE_VOCABULARY_NOTE (always
    # present, see its own tests below) legitimately contains that phrase
    # too, as a forward-reference to this exact context_note section.
    assert "Traveler's stated preferences" not in captured_prompts[1]


def test_previous_total_days_is_folded_into_the_meta_prompt_as_a_soft_fact():
    # Regression test: a follow-up with no day-count language at all ("I
    # want to experience the artsy miami") after a real 5-day trip was
    # already generated was silently coming back a different length,
    # because total_days was re-guessed from scratch every call with no
    # anchor to what was already established. previous_total_days grounds
    # the meta prompt in that real fact -- as a soft instruction the model
    # can still override if the new request itself asks for a different
    # length, not a hard value like requested_days.
    meta = TripMeta(destination="Miami", total_days=5)
    chunk = _chunk([(i, "explore") for i in range(1, 6)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary("I want to experience the artsy miami", previous_total_days=5)

    meta_prompt = captured_prompts[0]
    assert "5-day itinerary" in meta_prompt
    assert "unless" in meta_prompt


def test_previous_total_days_omitted_when_none_leaves_meta_prompt_unchanged():
    # A brand-new conversation (no prior trip) must still get the plain
    # META_INSTRUCTIONS heuristics untouched -- no "already has a" fact
    # should be injected when there's nothing to preserve.
    meta = TripMeta(destination="Kyoto", total_days=3)
    chunk = _chunk([(i, "sightsee") for i in range(1, 4)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary("3 days in Kyoto")

    assert "already has a" not in captured_prompts[0]


def test_pace_vocabulary_is_always_present_in_the_chunk_prompt():
    # Regression test: a request stating its own pace ("a 3 day balanced
    # trip") got NO concrete grounding at all when PACE_GUIDANCE only
    # reached the model through the stored-profile note -- this must be
    # unconditional, not dependent on user_profile_note being set.
    meta = TripMeta(destination="Lisbon", total_days=3)
    chunk = _chunk([(i, "explore") for i in range(1, 4)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary("a 3 day balanced trip to Lisbon")

    chunk_prompt = captured_prompts[1]
    assert "5-6 activities per day" in chunk_prompt
    assert "3-4 activities per day" in chunk_prompt
    assert "6-8 activities per day" in chunk_prompt


def test_pace_vocabulary_states_request_wording_takes_priority():
    meta = TripMeta(destination="Lisbon", total_days=3)
    chunk = _chunk([(i, "explore") for i in range(1, 4)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary(
            "a 3 day balanced trip to Lisbon", user_profile_note="pace: leisurely (3-4 activities per day)",
        )

    chunk_prompt = captured_prompts[1]
    assert "takes priority" in chunk_prompt.lower() or "take priority" in chunk_prompt.lower()


def test_typical_trip_length_is_folded_into_the_meta_prompt_as_a_soft_default():
    # A brand-new conversation, no trip generated yet -- the traveler's
    # profile-stated usual trip length should ground the meta prompt as a
    # default the latest request's own duration language can still
    # override, the same soft-instruction treatment previous_total_days
    # already gets.
    meta = TripMeta(destination="Lisbon", total_days=5)
    chunk = _chunk([(i, "explore") for i in range(1, 6)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary("a trip to Lisbon", typical_trip_length_days=5)

    meta_prompt = captured_prompts[0]
    assert "usually plan 5-day trips" in meta_prompt
    assert "unless" in meta_prompt


def test_typical_trip_length_omitted_when_none_leaves_meta_prompt_unchanged():
    meta = TripMeta(destination="Kyoto", total_days=3)
    chunk = _chunk([(i, "sightsee") for i in range(1, 4)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary("3 days in Kyoto")

    assert "usually plan" not in captured_prompts[0]


def test_previous_total_days_takes_priority_over_typical_trip_length():
    # An edit turn within an already-generated trip is a more specific
    # anchor than the traveler's general-purpose profile default -- the
    # established trip length must win, not silently revert to the
    # profile's usual length.
    meta = TripMeta(destination="Miami", total_days=5)
    chunk = _chunk([(i, "explore") for i in range(1, 6)])
    captured_prompts = []

    def _fake_call(prompt, response_schema=None, max_output_tokens=800):
        captured_prompts.append(prompt)
        return [meta, chunk][len(captured_prompts) - 1]

    with patch("app.llm_service._call_gemini", side_effect=_fake_call):
        llm_service.generate_itinerary(
            "I want to experience the artsy miami",
            previous_total_days=5, typical_trip_length_days=10,
        )

    meta_prompt = captured_prompts[0]
    assert "5-day itinerary" in meta_prompt
    assert "usually plan" not in meta_prompt


def test_committed_event_not_found_bails_out_before_writing_any_chunk():
    # Explicit product decision: a request that truly commits to a named
    # show but find_events genuinely finds nothing must NOT fall back to
    # planning a substitute general itinerary -- bail out before any
    # chunk is even generated, so routers/trips.py can tell the traveler
    # plainly instead. destination/day-count inference still runs (it's
    # independent, already in flight concurrently), but no chunk call
    # should happen at all.
    meta = TripMeta(destination="New York", total_days=3)

    with (
        patch(
            "app.llm_service.agent_service.gather_place_context_for_itinerary",
            return_value=("Checked for the requested show.\nEVENT_NOT_FOUND: Alex O'Connor\n", []),
        ),
        patch("app.llm_service._call_gemini", return_value=meta) as mock_call,
    ):
        result = llm_service.generate_itinerary("go to New York for Alex O'Connor's show")

    assert result == {"destination": "New York", "days": [], "event_not_found": "Alex O'Connor"}
    mock_call.assert_called_once()  # only the meta call -- never a chunk call


def test_event_not_found_is_only_checked_on_a_fresh_gather_not_a_cached_one():
    # A later, unrelated turn reusing cached_agent_context must not keep
    # blocking generation forever off a stale EVENT_NOT_FOUND marker from
    # an earlier failed attempt -- the check only runs in the branch that
    # actually re-invokes the planning loop.
    meta = TripMeta(destination="New York", total_days=3)
    chunk = _chunk([(i, "explore") for i in range(1, 4)])

    with patch("app.llm_service._call_gemini", side_effect=[meta, chunk]):
        result = llm_service.generate_itinerary(
            "actually just plan me a general trip",
            cached_agent_context="EVENT_NOT_FOUND: Alex O'Connor",
        )

    assert "event_not_found" not in result
    assert len(result["days"]) == 3


def test_describe_gemini_error_missing_api_key():
    exc = ValueError("No API key was provided. Please pass a valid API key.")
    assert "GEMINI_API_KEY" in llm_service._describe_gemini_error(exc)


def test_describe_gemini_error_invalid_model():
    exc = genai_errors.ClientError(404, {"error": {"message": "model not found", "status": "NOT_FOUND"}})
    message = llm_service._describe_gemini_error(exc)
    assert llm_service.GEMINI_MODEL in message
    assert "ai.google.dev" in message


def test_describe_gemini_error_rate_limit():
    exc = genai_errors.ClientError(429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}})
    message = llm_service._describe_gemini_error(exc)
    assert "rate limit" in message.lower()


def test_call_gemini_missing_api_key_has_actionable_message():
    # Regression test: a raw low-level exception used to be surfaced to the
    # user verbatim in the 502 response, with no hint of what to actually do
    # about it. Missing/blank GEMINI_API_KEY is the most common setup error.
    with (
        patch("app.llm_service._get_client", side_effect=ValueError("No API key was provided.")),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service.generate_itinerary("3 days in Reykjavik")

    assert "GEMINI_API_KEY" in str(exc_info.value)


def test_call_gemini_404_hints_invalid_model():
    with (
        patch(
            "app.llm_service._get_client",
            side_effect=genai_errors.ClientError(404, {"error": {"message": "not found", "status": "NOT_FOUND"}}),
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service.generate_itinerary("3 days in Reykjavik")

    assert "model" in str(exc_info.value).lower()


def test_answer_question_translates_missing_api_key():
    with (
        patch("app.llm_service._call_gemini_chat", side_effect=RuntimeError("GEMINI_API_KEY is not set -- add it to your .env file.")),
        pytest.raises(RuntimeError) as exc_info,
    ):
        llm_service.answer_question("what's the weather like?", [])

    message = str(exc_info.value)
    assert message.startswith("Failed to answer question:")  # preserves the existing contract
    assert "GEMINI_API_KEY" in message


def test_cached_agent_context_skips_the_agent_step_entirely():
    meta = TripMeta(destination="Reykjavik", total_days=3)
    chunk = _chunk([(i, "sightsee") for i in range(1, 4)])

    with (
        patch("app.llm_service.agent_service.gather_trip_context") as mock_gather,
        patch("app.llm_service.agent_service.gather_place_context_for_itinerary") as mock_place,
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary(
            "3 days in Reykjavik", cached_agent_context="Already known: expect snow.",
        )

    mock_gather.assert_not_called()  # the whole point of caching -- no network round-trip
    mock_place.assert_not_called()  # same -- place-context is cached alongside currency
    assert result["agent_context"] == "Already known: expect snow."


def test_empty_cached_agent_context_still_gathers_fresh():
    # Regression test (2026-08-30 code review): a Q&A-first conversation
    # caches Conversation.agent_context = "" (routers/trips.py's own
    # cache-fill, to avoid re-running the paused currency loop on every
    # question turn) -- an `is not None` gate here would treat that "" as
    # a real cached value and permanently skip gather_place_context_for_
    # itinerary for the rest of the conversation, even though the loop is
    # enabled and has never actually run. An empty cached value must be
    # treated the same as no cached value at all: worth a fresh gather.
    meta = TripMeta(destination="Lisbon", total_days=2)
    chunk = _chunk([(i, "explore") for i in range(1, 3)])

    with (
        patch("app.llm_service.agent_service.gather_trip_context", return_value="") as mock_gather,
        patch(
            "app.llm_service.agent_service.gather_place_context_for_itinerary",
            return_value=("Lisbon is Portugal's hilly, coastal capital, known for its trams and viewpoints.", []),
        ) as mock_place,
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary("2 days in Lisbon", cached_agent_context="")

    mock_gather.assert_called_once()
    mock_place.assert_called_once()
    assert result["agent_context"] == "Lisbon is Portugal's hilly, coastal capital, known for its trams and viewpoints."


def test_currency_and_place_context_are_combined_when_both_return_findings():
    meta = TripMeta(destination="Lisbon", total_days=2)
    chunk = _chunk([(i, "explore") for i in range(1, 3)])

    with (
        patch("app.llm_service.agent_service.gather_trip_context", return_value="500 USD is about 460 EUR."),
        patch(
            "app.llm_service.agent_service.gather_place_context_for_itinerary",
            return_value=("Lisbon is Portugal's hilly, coastal capital, known for its trams and viewpoints.", []),
        ),
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary("2 days in Lisbon, budget 500 USD")

    assert result["agent_context"] == (
        "500 USD is about 460 EUR. "
        "Lisbon is Portugal's hilly, coastal capital, known for its trams and viewpoints."
    )


# ---------- named place pool grounding (2026-09-09) ----------


def test_named_place_pool_text_is_folded_into_agent_context():
    meta = TripMeta(destination="Miami", total_days=2)
    chunk = _chunk([(i, "explore") for i in range(1, 3)])

    with (
        patch("app.llm_service.agent_service.gather_named_place_pool", return_value=(
            "Real, named places near the destination: restaurant: Joe's Stone Crab", [],
        )),
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary("2 days in Miami")

    assert "Joe's Stone Crab" in result["agent_context"]


def test_named_place_pool_is_called_with_the_resolved_destination_and_day_count():
    meta = TripMeta(destination="Miami", total_days=5)
    chunk = _chunk([(i, "explore") for i in range(1, 6)])

    with (
        patch("app.llm_service.agent_service.gather_named_place_pool", return_value=("", [])) as mock_pool,
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        llm_service.generate_itinerary("5 days in Miami")

    mock_pool.assert_called_once_with("Miami", 5)


def test_named_place_pool_is_not_consulted_on_a_cached_agent_context_turn():
    meta = TripMeta(destination="Miami", total_days=2)
    chunk = _chunk([(i, "explore") for i in range(1, 3)])

    with (
        patch("app.llm_service.agent_service.gather_named_place_pool") as mock_pool,
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        llm_service.generate_itinerary("2 days in Miami", cached_agent_context="Already known: sunny.")

    mock_pool.assert_not_called()


def test_itinerary_activity_naming_a_pooled_place_is_persisted_as_a_found_place():
    # The pool sweep itself is never persisted wholesale (would flood
    # SavedPlace with every candidate looked at) -- only the pool entries
    # the generated itinerary text actually used should end up in
    # result["found_places"].
    meta = TripMeta(destination="Miami", total_days=1)
    chunk = ItineraryChunk(days=[
        ChunkItineraryDay(day_number=1, items=[
            ChunkItineraryItem(activity="Dinner at Joe's Stone Crab"),
            ChunkItineraryItem(activity="Relax on the beach"),
        ]),
    ])
    pool_tool_calls = [{
        "tool": "find_nearby_places",
        "args": {"place_type": "restaurant", "near": "Miami", "limit": 5},
        "result": {"results": [
            {"name": "Joe's Stone Crab", "rating": 4.6, "address": "11 Washington Ave", "price_level": "EXPENSIVE", "open_now": True},
            {"name": "Unused Diner", "rating": 4.0, "address": "1 Nowhere St", "price_level": None, "open_now": None},
        ]},
    }]

    with (
        patch("app.llm_service.agent_service.gather_named_place_pool", return_value=("Real, named places...", pool_tool_calls)),
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary("1 day in Miami")

    found_names = [
        p["result"]["results"][0]["name"] for p in result["found_places"] if p["tool"] == "find_nearby_places"
    ]
    assert found_names == ["Joe's Stone Crab"]  # named, actually-used place only -- never the unused pool entry


def test_pooled_place_match_is_case_insensitive_and_deduped_across_days():
    meta = TripMeta(destination="Miami", total_days=2)
    chunk = ItineraryChunk(days=[
        ChunkItineraryDay(day_number=1, items=[ChunkItineraryItem(activity="Dinner at joe's stone crab")]),
        ChunkItineraryDay(day_number=2, items=[ChunkItineraryItem(activity="Lunch at Joe's Stone Crab again")]),
    ])
    pool_tool_calls = [{
        "tool": "find_nearby_places",
        "args": {"place_type": "restaurant", "near": "Miami", "limit": 5},
        "result": {"results": [{"name": "Joe's Stone Crab", "rating": 4.6, "address": "11 Washington Ave", "price_level": "EXPENSIVE", "open_now": True}]},
    }]

    with (
        patch("app.llm_service.agent_service.gather_named_place_pool", return_value=("...", pool_tool_calls)),
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary("2 days in Miami")

    assert len(result["found_places"]) == 1  # mentioned on both days, saved once


def test_no_found_places_key_when_the_itinerary_names_no_pooled_place():
    meta = TripMeta(destination="Miami", total_days=1)
    chunk = _chunk([(1, "Relax at the hotel")])
    pool_tool_calls = [{
        "tool": "find_nearby_places",
        "args": {"place_type": "restaurant", "near": "Miami", "limit": 5},
        "result": {"results": [{"name": "Joe's Stone Crab", "rating": 4.6, "address": "11 Washington Ave", "price_level": "EXPENSIVE", "open_now": True}]},
    }]

    with (
        patch("app.llm_service.agent_service.gather_named_place_pool", return_value=("...", pool_tool_calls)),
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary("1 day in Miami")

    assert "found_places" not in result


# ---------- intent classification ----------

def test_intent_instructions_disambiguate_tour_guide_phrasing_from_edit_trip():
    # Regression test: "be my tour guide"/"take me through this place" was
    # being misclassified as edit_trip (regenerating a whole new itinerary)
    # instead of question (the Wikipedia-grounded Q&A path) -- see
    # docs/sessions/ for the live bug report. INTENT_INSTRUCTIONS had zero
    # few-shot examples to disambiguate narrative/tour-guide phrasing from
    # an actual itinerary-modification request. This guards the examples
    # that fix it against being trimmed away later -- it cannot prove real
    # classification behavior, since classify_intent's other tests all mock
    # the Gemini response; that needs a live-verification pass instead.
    assert "be my tour guide" in llm_service.INTENT_INSTRUCTIONS
    assert "take me through this place" in llm_service.INTENT_INSTRUCTIONS
    assert "swap day 2" in llm_service.INTENT_INSTRUCTIONS  # edit_trip contrast example still present


def test_classify_intent_new_trip():
    with patch("app.llm_service._call_gemini", return_value=IntentResult(intent="new_trip")):
        assert llm_service.classify_intent("plan me a trip to Peru", "") == ("new_trip", False)


def test_classify_intent_off_topic():
    with patch("app.llm_service._call_gemini", return_value=IntentResult(intent="off_topic")):
        assert llm_service.classify_intent("write me a sorting algorithm", "") == ("off_topic", False)


def test_classify_intent_question():
    with patch("app.llm_service._call_gemini", return_value=IntentResult(intent="question")):
        assert llm_service.classify_intent(
            "what's the weather like there?", "trip to Kyoto discussed",
        ) == ("question", False)


def test_classify_intent_schema_mismatch_falls_back_to_new_trip():
    # The Literal-typed schema means Gemini can't return an invalid category
    # in the first place -- the failure mode now is _call_gemini raising
    # when the model's output doesn't validate at all.
    with patch("app.llm_service._call_gemini", side_effect=RuntimeError("schema mismatch")):
        assert llm_service.classify_intent("plan a trip", "") == ("new_trip", False)


def test_classify_intent_failure_fails_open_to_new_trip():
    with patch("app.llm_service._call_gemini", side_effect=ConnectionError("unreachable")):
        assert llm_service.classify_intent("plan a trip", "") == ("new_trip", False)


def test_classify_intent_extracts_tour_guide_requested():
    with patch(
        "app.llm_service._call_gemini",
        return_value=IntentResult(intent="question", tour_guide_requested=True),
    ):
        assert llm_service.classify_intent(
            "can you be my tour guide and take me through this place", "",
        ) == ("question", True)


def test_generate_conversation_title_returns_the_models_title():
    with patch(
        "app.llm_service._call_gemini",
        return_value=ConversationTitleResult(title="NYC For Alex O'Connor's Show"),
    ):
        assert llm_service.generate_conversation_title(
            "I want to go to New York to go to Alex O'Connor's show",
        ) == "NYC For Alex O'Connor's Show"


def test_generate_conversation_title_truncates_a_too_long_title():
    long_title = "A " * 40
    with patch("app.llm_service._call_gemini", return_value=ConversationTitleResult(title=long_title)):
        result = llm_service.generate_conversation_title("plan a trip")

    assert len(result) <= 60


def test_generate_conversation_title_falls_back_to_prompt_truncation_on_empty_title():
    with patch("app.llm_service._call_gemini", return_value=ConversationTitleResult(title="")):
        assert llm_service.generate_conversation_title("plan a trip to Peru") == "plan a trip to Peru"


def test_generate_conversation_title_falls_back_on_failure():
    with patch("app.llm_service._call_gemini", side_effect=RuntimeError("schema mismatch")):
        assert llm_service.generate_conversation_title("plan a trip to Peru") == "plan a trip to Peru"


def test_generate_conversation_title_fallback_truncates_a_long_prompt():
    long_prompt = "a" * 100
    with patch("app.llm_service._call_gemini", side_effect=RuntimeError("down")):
        result = llm_service.generate_conversation_title(long_prompt)

    assert result == "a" * 60 + "..."


def test_generate_conversation_title_failure_is_logged_not_silent(caplog):
    # Regression test (2026-09-10): a real conversation's title silently
    # fell back to the raw prompt with nothing in the logs to explain why
    # -- same class of gap the 2026-08-31 architecture review already
    # fixed for agent_service.py's tool-calling loops. The fallback
    # behavior itself is correct and unchanged (a conversation must never
    # fail to be created just because titling it failed); this only
    # asserts the failure is now visible.
    with (
        patch("app.llm_service._call_gemini", side_effect=RuntimeError("quota exceeded")),
        caplog.at_level("ERROR", logger="app.llm_service"),
    ):
        llm_service.generate_conversation_title("plan a trip to Peru")

    assert any("generate_conversation_title" in r.message and "failed" in r.message for r in caplog.records)


def test_classify_intent_failure_fails_open_tour_guide_requested_false():
    # Same fail-open case as test_classify_intent_failure_fails_open_to_new_trip,
    # asserted specifically on the tour_guide_requested slot -- a classifier
    # failure must never leave a stale True lingering, it should read as a
    # normal fresh new_trip turn.
    with patch("app.llm_service._call_gemini", side_effect=ConnectionError("unreachable")):
        intent, tour_guide_requested = llm_service.classify_intent("plan a trip", "")

    assert intent == "new_trip"
    assert tour_guide_requested is False


def test_intent_instructions_constrains_tour_guide_requested_to_question_intent():
    # Regression guard: the instruction that keeps tour_guide_requested from
    # coincidentally firing True alongside edit_trip/new_trip.
    assert "tour_guide_requested can only be true when intent is" in llm_service.INTENT_INSTRUCTIONS


def test_intent_instructions_recognizes_being_physically_present_as_a_tour_guide_trigger():
    # Regression test: a live-reported bug (2026-09-01) -- "I think i am
    # already at wynwood walls i really want understand the importaance of
    # the place" did not trigger tour_guide_requested, because the only
    # recognized trigger phrasing was the literal "be my tour guide"/"take
    # me through this place" set. A user describing being at a place and
    # wanting to understand its importance is the same narrative/deep-dive
    # request in different words.
    assert "I'm at X and I want to understand its importance" in llm_service.INTENT_INSTRUCTIONS


def test_intent_instructions_disambiguate_single_recommendation_from_new_trip():
    # Regression test, same live-reported bug: "That is great i want to go
    # somewhere to read a book can you suggest a place where i can go but
    # still see the murals" -- a request to recommend ONE nearby spot within
    # an already-discussed location -- was misclassified as new_trip and
    # regenerated a whole unrelated 5-day Miami itinerary from scratch,
    # instead of staying "question" (ideally reaching the new
    # find_nearby_places tool). INTENT_INSTRUCTIONS had no example
    # disambiguating a single-place recommendation ask from a genuine
    # "plan a new trip" request.
    assert "suggest a place where I can read but still see the murals" in llm_service.INTENT_INSTRUCTIONS
    assert "not asking to plan a" in llm_service.INTENT_INSTRUCTIONS


# ---------- conversational Q&A path ----------

def test_answer_question_returns_model_content():
    with patch("app.llm_service._call_gemini_chat", return_value="It should be sunny and warm in June."):
        result = llm_service.answer_question("what's the weather like?", [{"role": "user", "content": "trip to Kyoto"}])

    assert result == "It should be sunny and warm in June."


def test_answer_question_raises_on_failure():
    with patch("app.llm_service._call_gemini_chat", side_effect=RuntimeError("unreachable")):
        try:
            llm_service.answer_question("what's the weather like?", [])
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "Failed to answer" in str(exc)


def test_answer_question_grounds_the_model_in_real_agent_findings():
    # Regression test: temperature/weather questions were being answered with
    # invented numbers because the real forecast (agent_context) was fetched
    # once during generation and shown in the UI, but never made it into the
    # prompt for follow-up questions -- the model had nothing real to draw on
    # and made something up. The real findings must reach the system prompt.
    with patch("app.llm_service._call_gemini_chat", return_value="Highs around 24C, per the forecast.") as mock_call:
        llm_service.answer_question(
            "what's the temperature there?", [], agent_context="Kyoto: highs of 22-26C, low rain chance.",
        )

    sent_system_prompt = mock_call.call_args.args[0]
    assert "Kyoto: highs of 22-26C" in sent_system_prompt
    assert "invent" in sent_system_prompt.lower()  # instructed not to fabricate numbers


def test_answer_question_instructs_model_not_to_volunteer_agent_context():
    # Regression test: cached agent_context (weather/currency findings from
    # turn 1) was being surfaced unconditionally on every later question in
    # the conversation, so the model kept bringing up weather even on
    # unrelated questions ("what's a good day-3 restaurant area?"). The
    # system prompt must explicitly tell it to only use the data when the
    # question is actually about it.
    with patch("app.llm_service._call_gemini_chat", return_value="Try the east side for dinner.") as mock_call:
        llm_service.answer_question(
            "what's a good area for dinner?", [], agent_context="Kyoto: highs of 22-26C, low rain chance.",
        )

    sent_system_prompt = mock_call.call_args.args[0]
    assert "not proactively mention" in sent_system_prompt.lower()


def test_answer_question_without_agent_context_still_works():
    # No findings cached yet (e.g. first message in a conversation is a
    # question) -- should behave exactly as before, no crash, no empty note.
    with patch("app.llm_service._call_gemini_chat", return_value="I'd need a destination to check that.") as mock_call:
        result = llm_service.answer_question("what's the temperature there?", [])

    sent_system_prompt = mock_call.call_args.args[0]
    assert sent_system_prompt == llm_service.QUESTION_SYSTEM_PROMPT
    assert result == "I'd need a destination to check that."


def test_answer_question_personalizes_with_the_user_profile_note():
    # Same gap as generate_itinerary had before user_profile_note existed
    # there: a conversational question ("suggest somewhere to eat") had
    # zero awareness of the traveler's own stated preferences even though
    # the data already existed and was already used one code path over.
    with patch("app.llm_service._call_gemini_chat", return_value="Try a vegetarian spot on the east side.") as mock_call:
        llm_service.answer_question(
            "where should I eat tonight?", [],
            user_profile_note="dietary needs: vegetarian; budget: mid",
        )

    sent_system_prompt = mock_call.call_args.args[0]
    assert "vegetarian" in sent_system_prompt
    assert "budget: mid" in sent_system_prompt
    # Same "preference, not fact" caution generate_itinerary's chunk prompt
    # already applies to this same note -- must not be dropped here.
    assert "invent" in sent_system_prompt.lower()


def test_answer_question_without_user_profile_note_adds_nothing():
    with patch("app.llm_service._call_gemini_chat", return_value="Sure thing.") as mock_call:
        llm_service.answer_question("what's a good area for dinner?", [])

    sent_system_prompt = mock_call.call_args.args[0]
    assert sent_system_prompt == llm_service.QUESTION_SYSTEM_PROMPT


def test_answer_question_instructs_honesty_even_with_no_agent_context():
    # Regression test: a weather question with nothing cached yet (no prior
    # trip generation, or the agent step found nothing) got zero grounding
    # AND zero instruction not to guess -- the model just fabricated a
    # confident-sounding forecast (wrong units, invented conditions like
    # "sunny" that don't even exist in the tool's data shape). The base
    # system prompt must forbid guessing real-time facts unconditionally,
    # not just when real data happens to be available.
    with patch("app.llm_service._call_gemini_chat", return_value="I don't have current data for that.") as mock_call:
        llm_service.answer_question("what does the temperature look like?", [], agent_context="")

    sent_system_prompt = mock_call.call_args.args[0]
    assert "do not have live access" in sent_system_prompt.lower()
    assert "don't have current data" in sent_system_prompt.lower()


def test_answer_question_forbids_inventing_units_or_conditions_not_given():
    # Regression test for the exact bug: real agent_context had Celsius
    # numbers only, but the model answered in Fahrenheit with invented sky
    # conditions ("Partly cloudy") that were never part of the data.
    with patch("app.llm_service._call_gemini_chat", return_value="Highs around 24C, per the forecast.") as mock_call:
        llm_service.answer_question(
            "what's the temperature there?", [], agent_context="Kyoto: highs of 22-26C, low rain chance.",
        )

    sent_system_prompt = mock_call.call_args.args[0]
    assert "fahrenheit" in sent_system_prompt.lower()
    assert "sunny" in sent_system_prompt.lower() or "cloudy" in sent_system_prompt.lower()


def test_answer_question_maps_chat_history_roles_for_gemini():
    # Gemini's Content.role expects "user"/"model" -- "assistant" (this
    # app's DB convention) is not a recognized role and gets rejected by the
    # real API (confirmed live during this migration).
    with patch("app.llm_service._get_client") as mock_get_client:
        fake_response = Mock(text="answer")
        mock_get_client.return_value.models.generate_content.return_value = fake_response

        llm_service.answer_question(
            "day 3?", [{"role": "user", "content": "trip to Kyoto"}, {"role": "assistant", "content": "sounds great"}],
        )

    sent_contents = mock_get_client.return_value.models.generate_content.call_args.kwargs["contents"]
    roles = [c.role for c in sent_contents]
    assert roles == ["user", "model", "user"]
