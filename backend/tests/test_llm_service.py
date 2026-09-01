from unittest.mock import Mock, patch

import pytest
from google.genai import errors as genai_errors

from app import llm_service
from app.llm_service import (
    ChunkItineraryDay,
    ChunkItineraryItem,
    IntentResult,
    ItineraryChunk,
    TripMeta,
)


@pytest.fixture(autouse=True)
def mock_agent_context():
    # Every test in this file exercises the itinerary pipeline in isolation.
    # Without this, generate_itinerary's calls to
    # agent_service.gather_trip_context and
    # agent_service.gather_place_context_for_itinerary would make real
    # network calls to Gemini during tests.
    with (
        patch("app.llm_service.agent_service.gather_trip_context", return_value=""),
        patch("app.llm_service.agent_service.gather_place_context_for_itinerary", return_value=""),
    ):
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
            return_value="Lisbon is Portugal's hilly, coastal capital, known for its trams and viewpoints.",
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
            return_value="Lisbon is Portugal's hilly, coastal capital, known for its trams and viewpoints.",
        ),
        patch("app.llm_service._call_gemini", side_effect=[meta, chunk]),
    ):
        result = llm_service.generate_itinerary("2 days in Lisbon, budget 500 USD")

    assert result["agent_context"] == (
        "500 USD is about 460 EUR. "
        "Lisbon is Portugal's hilly, coastal capital, known for its trams and viewpoints."
    )


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
