from datetime import date
from unittest.mock import patch

import pytest
from conftest import TEST_GOOGLE_SUB
from fastapi import Depends
from fastapi.testclient import TestClient

from app import date_resolver, models
from app.auth import get_current_user
from app.database import Base, SessionLocal, engine, get_db
from app.main import app
from app.routers.trips import MAX_CONTEXT_CHARS, _build_conversation_context

client = TestClient(app)

FAKE_ITINERARY = {
    "destination": "Austin",
    "days": [
        {"day_number": 1, "items": [{"time_of_day": "morning", "activity": "Zilker Park"}]}
    ],
}


def setup_function():
    # Fresh tables for each test since the shared in-memory SQLite engine
    # persists data across tests otherwise.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def mock_intent_classification():
    # Every existing test here exercises the itinerary pipeline directly, so
    # default classification to "new_trip" (the original, pre-routing
    # behavior) unless a test overrides this to exercise routing itself.
    with patch("app.llm_service.classify_intent", return_value=("new_trip", False)):
        yield


@pytest.fixture(autouse=True)
def mock_qa_tools_by_default():
    # Every question-path test written before the place-context tool loop
    # (agent_service.answer_question_with_tools) expects
    # llm_service.answer_question to be the only LLM call on that path.
    # Without a default here, those tests would hit answer_question_with_tools
    # for real -- which, since a live GEMINI_API_KEY often sits in the local
    # .env main.py loads, means a real network call to Gemini during a test
    # run, not just a broken test. Default it to "" (the router's existing
    # fallback path), matching the "fails quietly" contract
    # answer_question_with_tools already documents. Tests that specifically
    # want to exercise the tool loop override this explicitly, same pattern
    # already used for gather_trip_context and mock_intent_classification
    # above.
    #
    # Deliberately scoped to THIS file only (not conftest.py) -- agent_service
    # and app.routers.trips.agent_service are the same module object, so a
    # global autouse patch here would also clobber
    # test_agent_service.py's own direct tests of the real function.
    with patch("app.routers.trips.agent_service.answer_question_with_tools", return_value=("", [])):
        yield


def test_generate_trip_creates_placeholder_user_and_saves_trip():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    assert response.status_code == 200
    body = response.json()
    assert body["destination"] == "Austin"
    assert body["itinerary"][0]["activity"] == "Zilker Park"


def test_generate_trip_reuses_existing_user_on_second_call():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
        second = client.post("/trips/generate", json={"prompt": "week in Austin"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["trip_id"] != second.json()["trip_id"]


def test_generate_trip_forwards_requested_days_to_llm_service():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY) as mock_generate:
        client.post("/trips/generate", json={"prompt": "a month in Japan", "days": 30})

    mock_generate.assert_called_once_with(
        "a month in Japan", requested_days=30, conversation_context="", cached_agent_context=None,
        previous_total_days=None,
    )


def test_generate_trip_surfaces_note_from_llm_result():
    result_with_note = {**FAKE_ITINERARY, "note": "Requested 100 days exceeds the 60-day limit; showing the first 60 days."}
    with patch("app.llm_service.generate_itinerary", return_value=result_with_note):
        response = client.post("/trips/generate", json={"prompt": "100 day trip", "days": 100})

    assert response.json()["note"] == result_with_note["note"]


def test_first_message_creates_a_new_conversation():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    body = response.json()
    assert body["conversation_id"] is not None

    conv_response = client.get(f"/conversations/{body['conversation_id']}")
    assert conv_response.status_code == 200
    conv = conv_response.json()
    assert conv["title"].startswith("weekend in Austin")
    assert len(conv["messages"]) == 2  # user message + assistant message
    assert conv["messages"][0]["role"] == "user"
    assert conv["messages"][1]["role"] == "assistant"
    assert conv["messages"][1]["trip"]["destination"] == "Austin"


def test_assistant_message_stores_a_real_itinerary_summary_not_just_destination():
    # This is the fix for thin context: earlier, assistant turns only stored
    # "Planned a trip to X.", giving follow-up turns nothing concrete to
    # reference. Now the actual day/activity content should be present.
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    conv_id = response.json()["conversation_id"]
    conv = client.get(f"/conversations/{conv_id}").json()
    assistant_content = conv["messages"][1]["content"]
    assert "Zilker Park" in assistant_content
    assert "Day 1" in assistant_content


def test_second_message_continues_the_same_conversation():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
        conv_id = first.json()["conversation_id"]

        second = client.post(
            "/trips/generate",
            json={"prompt": "actually make it a full week", "conversation_id": conv_id},
        )

    assert second.status_code == 200
    assert second.json()["conversation_id"] == conv_id

    conv = client.get(f"/conversations/{conv_id}").json()
    assert len(conv["messages"]) == 4  # 2 user + 2 assistant across both turns


# ---------- _build_conversation_context (real bug, 2026-09-01) ----------


class _FakeMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


class _FakeConversation:
    def __init__(self, messages: list[_FakeMessage]):
        self.messages = messages


def test_build_conversation_context_keeps_most_recent_message_over_budget():
    # Regression test: a live-reported bug where the char-budget truncation
    # sliced the chronologically-joined string from the HEAD
    # (`[:MAX_CONTEXT_CHARS]`), keeping the oldest of the last
    # MAX_CONTEXT_MESSAGES turns and silently dropping the newest ones --
    # exactly backwards from what a "recent conversation memory" string
    # should preserve. Real symptom: a user discussed scuba diving
    # (Florida Keys, Biscayne National Park), then said "can we add to the
    # plan" -- the truncated context cut off mid-sentence through the scuba
    # answer, so the itinerary regeneration that followed had no idea what
    # to add.
    long_old_message = "Old context that is not what the user is asking about right now. " * 10
    newest_message = "The exact thing the user just asked to add to the plan: scuba diving in the Florida Keys."
    conversation = _FakeConversation([
        _FakeMessage("user", "some earlier question"),
        _FakeMessage("assistant", long_old_message),
        _FakeMessage("user", "another earlier question"),
        _FakeMessage("assistant", long_old_message),
        _FakeMessage("user", "that is nice where else can i go to in miami if i like scuba diving"),
        _FakeMessage("assistant", newest_message),
    ])

    result = _build_conversation_context(conversation)

    assert len(result) <= MAX_CONTEXT_CHARS
    assert "scuba diving in the Florida Keys" in result
    assert result.endswith(f"Assistant: {newest_message}")


def test_build_conversation_context_preserves_chronological_order():
    conversation = _FakeConversation([
        _FakeMessage("user", "first"),
        _FakeMessage("assistant", "second"),
        _FakeMessage("user", "third"),
    ])

    result = _build_conversation_context(conversation)

    assert result.index("first") < result.index("second") < result.index("third")


def test_build_conversation_context_under_budget_keeps_everything():
    conversation = _FakeConversation([
        _FakeMessage("user", "weekend in Austin"),
        _FakeMessage("assistant", "Sounds fun!"),
    ])

    result = _build_conversation_context(conversation)

    assert result == "User asked: weekend in Austin | Assistant: Sounds fun!"


def test_conversation_context_is_passed_to_llm_on_followup():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY) as mock_generate:
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
        conv_id = first.json()["conversation_id"]

        mock_generate.reset_mock()
        client.post("/trips/generate", json={"prompt": "make it vegetarian friendly", "conversation_id": conv_id})

    call_kwargs = mock_generate.call_args.kwargs
    assert "weekend in Austin" in call_kwargs["conversation_context"]


def test_agent_context_is_cached_on_conversation_and_reused_on_followup():
    # Conversation.agent_context exists specifically so weather/currency
    # findings are gathered once per conversation, not re-fetched on every
    # edit turn. First call has nothing cached yet (None); once the first
    # call returns findings, they should be persisted and handed back to
    # llm_service on the next turn instead of leaving it to refetch them.
    result_with_context = {**FAKE_ITINERARY, "agent_context": "Rain expected; pack a jacket."}
    with patch("app.llm_service.generate_itinerary", return_value=result_with_context) as mock_generate:
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
        conv_id = first.json()["conversation_id"]

        assert mock_generate.call_args.kwargs["cached_agent_context"] is None
        # Freshly gathered on this turn -- should be surfaced in the response
        # so the frontend shows the "Agent findings" banner once.
        assert first.json()["agent_context"] == "Rain expected; pack a jacket."

        mock_generate.reset_mock()
        mock_generate.return_value = FAKE_ITINERARY
        second = client.post("/trips/generate", json={"prompt": "make it vegetarian friendly", "conversation_id": conv_id})

    assert mock_generate.call_args.kwargs["cached_agent_context"] == "Rain expected; pack a jacket."
    # Reused from cache on this turn, not freshly gathered -- must NOT be
    # surfaced again, otherwise the same findings banner reappears on every
    # edit turn in the conversation even though nothing new was found.
    assert second.json()["agent_context"] is None


def test_agent_context_caches_empty_string_when_nothing_found():
    # "" (agent step ran, found nothing useful) must still count as cached --
    # otherwise a conversation with no useful findings would re-run the
    # agent step on every single turn forever.
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY) as mock_generate:
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
        conv_id = first.json()["conversation_id"]

        mock_generate.reset_mock()
        client.post("/trips/generate", json={"prompt": "add a museum", "conversation_id": conv_id})

    assert mock_generate.call_args.kwargs["cached_agent_context"] == ""


def test_generate_trip_with_unknown_conversation_id_returns_404():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "hello", "conversation_id": 9999})

    assert response.status_code == 404


def test_list_conversations_returns_most_recent_first():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        client.post("/trips/generate", json={"prompt": "first trip"})
        client.post("/trips/generate", json={"prompt": "second trip"})

    conversations = client.get("/conversations").json()
    assert len(conversations) == 2
    assert conversations[0]["title"].startswith("second trip")


def test_delete_conversation_removes_it():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = response.json()["conversation_id"]

    delete_response = client.delete(f"/conversations/{conv_id}")
    assert delete_response.status_code == 200

    get_response = client.get(f"/conversations/{conv_id}")
    assert get_response.status_code == 404


def test_delete_conversation_with_a_generated_trip_does_not_500():
    # Regression test: Trip.conversation_id used to have no ondelete behavior,
    # so deleting a conversation that had already generated a trip violated
    # the FK constraint and raised a 500 against any DB that enforces FKs
    # (MySQL does by default; the old test above didn't catch it because
    # SQLite doesn't unless PRAGMA foreign_keys=ON is set -- see database.py).
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    trip_id = response.json()["trip_id"]
    conv_id = response.json()["conversation_id"]
    assert trip_id is not None

    delete_response = client.delete(f"/conversations/{conv_id}")
    assert delete_response.status_code == 200

    # The trip itself should survive, just unlinked from the deleted conversation.
    trip_response = client.get(f"/trips/{trip_id}")
    assert trip_response.status_code == 200
    assert trip_response.json()["destination"] == "Austin"


# ---------- intent routing: off-topic, question, and skip-heavy-pipeline behavior ----------

def test_off_topic_message_never_calls_generate_itinerary():
    with (
        patch("app.llm_service.classify_intent", return_value=("off_topic", False)),
        patch("app.llm_service.generate_itinerary") as mock_generate,
    ):
        response = client.post("/trips/generate", json={"prompt": "write me a python script"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"]
    assert body["trip_id"] is None
    mock_generate.assert_not_called()  # the entire expensive pipeline must be skipped


def test_off_topic_reply_is_saved_to_conversation():
    with patch("app.llm_service.classify_intent", return_value=("off_topic", False)):
        response = client.post("/trips/generate", json={"prompt": "help me debug my code"})

    conv_id = response.json()["conversation_id"]
    conv = client.get(f"/conversations/{conv_id}").json()
    assert len(conv["messages"]) == 2
    assert conv["messages"][1]["trip"] is None  # no itinerary was generated


def test_question_message_calls_answer_question_not_generate_itinerary():
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.llm_service.answer_question", return_value="It'll likely be warm and sunny.") as mock_answer,
        patch("app.llm_service.generate_itinerary") as mock_generate,
    ):
        response = client.post("/trips/generate", json={"prompt": "what's the weather like there?"})

    assert response.status_code == 200
    assert response.json()["reply"] == "It'll likely be warm and sunny."
    assert response.json()["trip_id"] is None
    mock_generate.assert_not_called()
    mock_answer.assert_called_once()


def test_question_uses_place_context_tool_answer_when_available():
    # When the place-context tool loop produces a real answer, it's used
    # directly and the plain llm_service.answer_question path is skipped
    # entirely -- the inverse of the conftest.py default (which returns ""
    # and falls through) used by every other question test in this file.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch(
            "app.routers.trips.agent_service.answer_question_with_tools",
            return_value=("The Louvre is a famous museum in Paris.", []),
        ) as mock_qa_tools,
        patch("app.llm_service.answer_question") as mock_answer,
    ):
        response = client.post("/trips/generate", json={"prompt": "tell me about the Louvre"})

    assert response.status_code == 200
    assert response.json()["reply"] == "The Louvre is a famous museum in Paris."
    mock_qa_tools.assert_called_once()
    mock_answer.assert_not_called()


def test_question_falls_back_to_plain_answer_when_tool_loop_returns_nothing():
    # The default/common case (also exercised implicitly by every other
    # question test via conftest.py's autouse override) -- spelled out
    # explicitly here as the direct counterpart to the test above.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.routers.trips.agent_service.answer_question_with_tools", return_value=("", [])) as mock_qa_tools,
        patch("app.llm_service.answer_question", return_value="A generic answer.") as mock_answer,
    ):
        response = client.post("/trips/generate", json={"prompt": "how much does that cost?"})

    assert response.status_code == 200
    assert response.json()["reply"] == "A generic answer."
    mock_qa_tools.assert_called_once()
    mock_answer.assert_called_once()


def test_tour_guide_mode_persists_across_question_turns_and_clears_on_edit_trip():
    # Turn 1: the user explicitly triggers tour-guide mode. classify_intent
    # reports tour_guide_requested=True for THIS turn -- the mode isn't on
    # yet when answer_question_with_tools is called (it only needs to cover
    # LATER turns, this one already gets a detailed reply via
    # QA_TOOL_SYSTEM_PROMPT's own per-turn instruction), but it must be
    # persisted onto the conversation afterward.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", True)),
        patch(
            "app.routers.trips.agent_service.answer_question_with_tools",
            return_value=("Sure, let's go!", []),
        ) as mock_qa,
    ):
        response = client.post("/trips/generate", json={"prompt": "be my tour guide"})

    conv_id = response.json()["conversation_id"]
    assert mock_qa.call_args.kwargs["tour_guide_mode"] is False  # not yet on entering this turn
    # Deterministic, Python-added acknowledgment on the activating turn --
    # see routers/trips.py's activating_tour_guide flag. Exact wording, not
    # something the (mocked) LLM reply happened to contain.
    assert response.json()["reply"] == "Tour guide mode on. Sure, let's go!"

    db = SessionLocal()
    try:
        conversation = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
        assert conversation.tour_guide_mode is True
    finally:
        db.close()

    # The frontend's only window into this state -- ConversationDetail,
    # not TripResponse, since a question turn's Message has no trip
    # attached at all (see schemas.py's ConversationDetail comment).
    assert client.get(f"/conversations/{conv_id}").json()["tour_guide_mode"] is True

    # Turn 2: a vague follow-up that does NOT re-trigger tour_guide_requested
    # -- the persisted mode from turn 1 should still be passed through.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch(
            "app.routers.trips.agent_service.answer_question_with_tools",
            return_value=("More detail...", []),
        ) as mock_qa2,
    ):
        turn2 = client.post(
            "/trips/generate",
            json={"prompt": "what else is nearby?", "conversation_id": conv_id},
        )

    assert mock_qa2.call_args.kwargs["tour_guide_mode"] is True
    # The acknowledgment is one-time, on activation only -- a later turn in
    # an already-active conversation must not repeat it.
    assert turn2.json()["reply"] == "More detail..."

    # Turn 3: explicitly back to planning -- mode clears.
    with (
        patch("app.llm_service.classify_intent", return_value=("edit_trip", False)),
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
    ):
        client.post(
            "/trips/generate",
            json={"prompt": "actually let's do a proper 3-day itinerary", "conversation_id": conv_id},
        )

    db = SessionLocal()
    try:
        conversation = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
        assert conversation.tour_guide_mode is False
    finally:
        db.close()

    assert client.get(f"/conversations/{conv_id}").json()["tour_guide_mode"] is False


def test_question_receives_real_chat_history_not_squashed_string():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = first.json()["conversation_id"]

    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.llm_service.answer_question", return_value="Sure thing.") as mock_answer,
    ):
        client.post("/trips/generate", json={"prompt": "why Zilker Park?", "conversation_id": conv_id})

    chat_messages_arg = mock_answer.call_args.args[1]
    assert isinstance(chat_messages_arg, list)
    assert chat_messages_arg[0]["role"] == "user"
    assert "weekend in Austin" in chat_messages_arg[0]["content"]


def test_question_receives_the_conversations_cached_agent_findings():
    # Regression test: follow-up questions like "what's the temperature
    # there?" were answered with invented numbers because the real forecast,
    # gathered once and cached on Conversation.agent_context, was never
    # passed to answer_question -- see llm_service.answer_question.
    result_with_context = {**FAKE_ITINERARY, "agent_context": "Austin: highs of 30C, sunny."}
    with patch("app.llm_service.generate_itinerary", return_value=result_with_context):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = first.json()["conversation_id"]

    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.llm_service.answer_question", return_value="It'll be hot.") as mock_answer,
    ):
        client.post("/trips/generate", json={"prompt": "what's the temperature there?", "conversation_id": conv_id})

    assert mock_answer.call_args.kwargs["agent_context"] == "Austin: highs of 30C, sunny."


def test_empty_agent_context_from_a_qa_turn_does_not_block_later_persistence():
    # Regression test (2026-08-30 code review): a conversation whose FIRST
    # turn is a question caches Conversation.agent_context = "" (the
    # currency loop is paused, so gather_trip_context always returns "").
    # A later new_trip/edit_trip turn's `was_freshly_gathered = ... is
    # None` check would then see agent_context as already-set (it's "",
    # not None) and never persist real findings gathered on that later
    # turn -- silently freezing the conversation's cache at "" forever.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.llm_service.answer_question", return_value="Sure."),
    ):
        first = client.post("/trips/generate", json={"prompt": "what's a good time to visit Lisbon?"})
    conv_id = first.json()["conversation_id"]

    result_with_context = {**FAKE_ITINERARY, "agent_context": "Lisbon is Portugal's coastal capital."}
    with (
        patch("app.llm_service.classify_intent", return_value=("new_trip", False)),
        patch("app.llm_service.generate_itinerary", return_value=result_with_context),
    ):
        client.post("/trips/generate", json={"prompt": "3 days in Lisbon", "conversation_id": conv_id})

    db = SessionLocal()
    try:
        conversation = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
        assert conversation.agent_context == "Lisbon is Portugal's coastal capital."
    finally:
        db.close()


def test_question_answer_failure_returns_502_not_500():
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.llm_service.answer_question", side_effect=RuntimeError("ollama unreachable")),
    ):
        response = client.post("/trips/generate", json={"prompt": "how much does that cost?"})

    assert response.status_code == 502


def test_question_triggers_on_demand_fetch_when_nothing_cached_yet():
    # Regression test for the reported bug: a weather question with nothing
    # cached yet (no prior trip generation in this conversation at all) got
    # no real data and no live fetch attempt -- the model just invented a
    # plausible-sounding forecast (wrong units, invented conditions). The
    # first question in a fresh conversation should try a real, scoped
    # fetch before answering.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch(
            "app.routers.trips.agent_service.gather_trip_context",
            return_value="Austin: highs of 32C, dry.",
        ) as mock_fetch,
        patch("app.llm_service.answer_question", return_value="It'll be hot and dry.") as mock_answer,
    ):
        response = client.post("/trips/generate", json={"prompt": "what's the weather in Austin?"})

    assert response.status_code == 200
    mock_fetch.assert_called_once_with("what's the weather in Austin?", destination=None)
    assert mock_answer.call_args.kwargs["agent_context"] == "Austin: highs of 32C, dry."


def test_question_on_demand_finding_is_cached_and_not_refetched():
    # Once an on-demand fetch has been attempted for a conversation (even if
    # it found nothing), it must not fire again on every later question --
    # same cache-once contract as itinerary generation's agent_context.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch(
            "app.routers.trips.agent_service.gather_trip_context",
            return_value="Austin: highs of 32C, dry.",
        ),
        patch("app.llm_service.answer_question", return_value="It'll be hot and dry."),
    ):
        first = client.post("/trips/generate", json={"prompt": "what's the weather in Austin?"})
    conv_id = first.json()["conversation_id"]

    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context") as mock_fetch_again,
        patch("app.llm_service.answer_question", return_value="Still hot.") as mock_answer,
    ):
        client.post("/trips/generate", json={"prompt": "is it humid too?", "conversation_id": conv_id})

    mock_fetch_again.assert_not_called()
    assert mock_answer.call_args.kwargs["agent_context"] == "Austin: highs of 32C, dry."


def test_question_on_demand_fetch_uses_existing_trip_destination_as_hint():
    # A bare follow-up ("what does the temperature look like?") doesn't name
    # a place on its own -- if a trip already exists for this conversation,
    # its destination should be passed along so the fetch knows which city
    # to check.
    db = SessionLocal()
    try:
        # google_sub must match conftest.py's auth override, which looks up
        # (and would otherwise create a *different* row for) "the current
        # user" by this same google_sub -- otherwise this conversation
        # belongs to a user the authenticated request isn't recognized as,
        # and the ownership check below 404s before gather_trip_context is
        # ever reached.
        user = models.User(email="placeholder-1@example.com", google_sub=TEST_GOOGLE_SUB)
        db.add(user)
        db.flush()
        conversation = models.Conversation(user_id=user.id, title="Test")
        db.add(conversation)
        db.flush()
        trip = models.Trip(user_id=user.id, conversation_id=conversation.id, destination="Austin", prompt="weekend in Austin")
        db.add(trip)
        db.commit()
        conv_id = conversation.id
    finally:
        db.close()

    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value="") as mock_fetch,
        patch("app.llm_service.answer_question", return_value="Not sure."),
    ):
        client.post(
            "/trips/generate",
            json={"prompt": "what does the temperature look like?", "conversation_id": conv_id},
        )

    mock_fetch.assert_called_once_with("what does the temperature look like?", destination="Austin")


# ---------- weather: date resolution + forecast attachment ----------

def test_weather_is_empty_when_no_date_resolves():
    # No date-like signal in the prompt -- resolve_trip_start_date returns
    # None, so Trip.start_date stays unset and get_or_refresh_trip_weather's
    # own short-circuit kicks in (see test_weather_service.py) without ever
    # hitting the network. weather_service is deliberately left unmocked
    # here to prove that: a real network call would make this test flaky/
    # slow instead of just failing loudly.
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    assert response.json()["weather"] == []


def test_weather_present_when_start_date_resolves():
    fake_weather = [
        {"day_number": 1, "date": "2026-08-30", "temp_min": 14.0, "temp_max": 22.5, "temp_min_f": 57.2, "temp_max_f": 72.5, "condition": "Clear sky"},
    ]
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
    ):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin starting 2026-08-30"})

    assert response.json()["weather"] == fake_weather


def test_weather_falls_back_to_previous_trips_start_date_on_a_followup():
    # An edit turn ("make it a full week") rarely repeats the date -- should
    # reuse the date resolved on the first turn in the same conversation,
    # same reuse pattern already used for agent_context/destination hints.
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
    ):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin starting 2026-08-30"})
    conv_id = first.json()["conversation_id"]

    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]) as mock_weather,
    ):
        client.post("/trips/generate", json={"prompt": "make it a full week", "conversation_id": conv_id})

    second_trip_arg = mock_weather.call_args.args[0]
    assert second_trip_arg.start_date == date(2026, 8, 30)


def test_day_count_falls_back_to_previous_trips_length_on_a_followup():
    # Regression test for the exact reported bug: "Plan a 5 day trip to
    # Miami" produced a real 5-day itinerary, then "I want to experience
    # the artsy miami" (no day-count language at all) silently produced a
    # 3-day itinerary instead of keeping 5 days -- because total_days was
    # re-guessed from scratch on every call with nothing anchoring it to
    # what was already established. This proves the router now looks up
    # the previous trip's day count and passes it through, same reuse
    # pattern as start_date above.
    five_day_itinerary = {
        "destination": "Miami",
        "days": [
            {"day_number": i, "items": [{"time_of_day": "morning", "activity": f"Day {i} activity"}]}
            for i in range(1, 6)
        ],
    }
    with patch("app.llm_service.generate_itinerary", return_value=five_day_itinerary):
        first = client.post("/trips/generate", json={"prompt": "Plan a 5 day trip to Miami"})
    conv_id = first.json()["conversation_id"]

    with patch("app.llm_service.generate_itinerary", return_value=five_day_itinerary) as mock_generate:
        client.post(
            "/trips/generate",
            json={"prompt": "I want to experience the artsy miami", "conversation_id": conv_id},
        )

    assert mock_generate.call_args.kwargs["previous_total_days"] == 5


def test_get_trip_by_id_includes_weather():
    fake_weather = [
        {"day_number": 1, "date": "2026-08-30", "temp_min": 14.0, "temp_max": 22.5, "temp_min_f": 57.2, "temp_max_f": 72.5, "condition": "Clear sky"},
    ]
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin starting 2026-08-30"})
    trip_id = created.json()["trip_id"]

    with patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather):
        fetched = client.get(f"/trips/{trip_id}")

    assert fetched.json()["weather"] == fake_weather


def test_conversation_reload_includes_weather():
    fake_weather = [
        {"day_number": 1, "date": "2026-08-30", "temp_min": 14.0, "temp_max": 22.5, "temp_min_f": 57.2, "temp_max_f": 72.5, "condition": "Clear sky"},
    ]
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
    ):
        created = client.post("/trips/generate", json={"prompt": "weekend in Austin starting 2026-08-30"})
    conv_id = created.json()["conversation_id"]

    with patch("app.routers.conversations.weather_service.get_or_refresh_trip_weather", return_value=fake_weather):
        conv = client.get(f"/conversations/{conv_id}").json()

    assert conv["messages"][1]["trip"]["weather"] == fake_weather


# ---------- regression: real weather must reach Q&A, not just currency ----------

def test_question_about_weather_is_grounded_in_the_real_forecast():
    # Regression test for the exact reported bug: "what should I pack given
    # the weather" was answered with plausible-but-wrong temperatures
    # (~70-80F) when the real fetched forecast was 104-108F, because the
    # real per-day weather was never passed to answer_question at all --
    # only the currency-only agent_context was. Weather must reach the
    # Q&A grounding even though it's a completely separate mechanism
    # (Trip.weather_json) from Conversation.agent_context.
    fake_weather = [
        {"day_number": 1, "date": "2026-08-26", "temp_min": 25.0, "temp_max": 40.0, "temp_min_f": 77.0, "temp_max_f": 104.0, "condition": "Overcast"},
    ]
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
    ):
        first = client.post("/trips/generate", json={"prompt": "4 days in Austin starting 2026-08-26"})
    conv_id = first.json()["conversation_id"]

    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
        patch("app.llm_service.answer_question", return_value="Light, breathable clothing given the heat.") as mock_answer,
    ):
        client.post(
            "/trips/generate",
            json={"prompt": "what outfits would you suggest based on the weather", "conversation_id": conv_id},
        )

    sent_context = mock_answer.call_args.kwargs["agent_context"]
    assert "104" in sent_context  # the real high, not an invented one
    assert "Austin" in sent_context


def test_question_weather_grounding_refreshes_every_turn_unlike_currency():
    # Unlike the currency agent step (gathered once per conversation and
    # cached on Conversation.agent_context), weather has its own cache
    # inside weather_service itself -- so it should be looked up on every
    # question turn, not just the first, even after Conversation.agent_context
    # is already set.
    fake_weather = [
        {"day_number": 1, "date": "2026-08-26", "temp_min": 25.0, "temp_max": 40.0, "temp_min_f": 77.0, "temp_max_f": 104.0, "condition": "Overcast"},
    ]
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
    ):
        first = client.post("/trips/generate", json={"prompt": "4 days in Austin starting 2026-08-26"})
    conv_id = first.json()["conversation_id"]

    # First question -- Conversation.agent_context transitions from None to "".
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
        patch("app.llm_service.answer_question", return_value="It'll be hot."),
    ):
        client.post("/trips/generate", json={"prompt": "how's the weather?", "conversation_id": conv_id})

    # Second question -- Conversation.agent_context is now "" (cached), but
    # weather grounding must still be fetched and included.
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context") as mock_currency_fetch,
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather) as mock_weather_fetch,
        patch("app.llm_service.answer_question", return_value="Still hot.") as mock_answer,
    ):
        client.post("/trips/generate", json={"prompt": "what should I wear?", "conversation_id": conv_id})

    mock_currency_fetch.assert_not_called()  # currency stays cache-once, unchanged
    mock_weather_fetch.assert_called_once()  # weather is looked up again
    assert "104" in mock_answer.call_args.kwargs["agent_context"]


def test_question_with_no_trip_has_no_weather_context():
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather") as mock_weather_fetch,
        patch("app.llm_service.answer_question", return_value="I'm not sure yet.") as mock_answer,
    ):
        client.post("/trips/generate", json={"prompt": "what's the weather like somewhere?"})

    mock_weather_fetch.assert_not_called()  # no trip in this conversation to fetch weather for
    assert mock_answer.call_args.kwargs["agent_context"] == ""


def test_question_resolves_start_date_from_the_question_itself_when_trip_has_none():
    # Regression test for the exact reported bug: a trip generated from a
    # prompt with no date phrase ("build me a 5 day trip to austin") has no
    # start_date, so a follow-up weather question got "I don't have current
    # weather data" even though the question itself named one ("this
    # weekend") -- the date was sitting right there in the text, but this
    # branch previously only ever read the trip's already-resolved
    # start_date, never the question's.
    fake_weather = [
        {"day_number": 1, "date": "2026-08-29", "temp_min": 20.0, "temp_max": 30.0, "temp_min_f": 68.0, "temp_max_f": 86.0, "condition": "Clear sky"},
    ]
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "build me a 5 day trip to austin"})
    trip_id = first.json()["trip_id"]
    conv_id = first.json()["conversation_id"]
    assert first.json()["start_date"] is None  # sanity-check the premise

    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather) as mock_weather_fetch,
        patch("app.llm_service.answer_question", return_value="Sunny and warm.") as mock_answer,
    ):
        client.post(
            "/trips/generate",
            json={
                "prompt": "what do the temperatures look like if i want to go there this weekend",
                "conversation_id": conv_id,
            },
        )

    mock_weather_fetch.assert_called_once()  # weather was actually attempted, not skipped
    assert "86" in mock_answer.call_args.kwargs["agent_context"]

    # The resolved date is persisted onto the trip, not just used for this
    # one answer -- so later turns (and calendar export) benefit too.
    updated_trip = client.get(f"/trips/{trip_id}").json()
    expected_date = date_resolver.resolve_trip_start_date("this weekend", date.today())
    assert updated_trip["start_date"] == expected_date.isoformat()


def test_question_does_not_override_an_already_resolved_start_date():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "4 days in Austin starting 2026-08-26"})
    trip_id = first.json()["trip_id"]
    conv_id = first.json()["conversation_id"]
    assert first.json()["start_date"] == "2026-08-26"

    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=[]),
        patch("app.llm_service.answer_question", return_value="Sure."),
    ):
        client.post(
            "/trips/generate",
            json={"prompt": "what about next weekend instead?", "conversation_id": conv_id},
        )

    updated_trip = client.get(f"/trips/{trip_id}").json()
    assert updated_trip["start_date"] == "2026-08-26"  # unchanged -- the original resolved date wins


# ---------- regression: get_conversation only refreshes the latest trip's weather ----------

def test_conversation_reload_only_refreshes_weather_for_the_latest_trip():
    # A conversation with two generated trips (e.g. one edit turn) used to
    # call get_or_refresh_trip_weather -- a freshness check, and on a cache
    # miss a live geocode + forecast fetch -- for EVERY trip with a message
    # on every single reload, not just the current one. Confirms the fix:
    # only the most recently generated trip gets that treatment; the older
    # one is served from whatever's already cached (weather_service.
    # read_cached_weather), with get_or_refresh_trip_weather never called
    # for it at all.
    fake_weather = [
        {"day_number": 1, "date": "2026-08-26", "temp_min": 14.0, "temp_max": 22.5, "temp_min_f": 57.2, "temp_max_f": 72.5, "condition": "Clear sky"},
    ]
    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
    ):
        first = client.post("/trips/generate", json={"prompt": "4 days in Austin starting 2026-08-26"})
    conv_id = first.json()["conversation_id"]
    older_trip_id = first.json()["trip_id"]

    with (
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
        patch("app.routers.trips.weather_service.get_or_refresh_trip_weather", return_value=fake_weather),
    ):
        second = client.post(
            "/trips/generate", json={"prompt": "make it a week instead", "conversation_id": conv_id},
        )
    latest_trip_id = second.json()["trip_id"]
    assert latest_trip_id != older_trip_id

    # Captured via side_effect, not read back from call_args afterward --
    # the request's DB session (and the ORM objects it produced) is closed
    # by the time client.get() returns, and get_conversation's own
    # db.commit() expires those objects' attributes by default, so reading
    # trip.id from a captured call_args after the fact raises a real
    # DetachedInstanceError. Recording the id live, while the session is
    # still open, sidesteps that entirely.
    refreshed_trip_ids = []
    cached_trip_ids = []

    def _record_refresh(trip, items):
        refreshed_trip_ids.append(trip.id)
        return fake_weather

    def _record_cached(trip):
        cached_trip_ids.append(trip.id)
        return []

    with (
        patch(
            "app.routers.conversations.weather_service.get_or_refresh_trip_weather", side_effect=_record_refresh,
        ) as mock_refresh,
        patch(
            "app.routers.conversations.weather_service.read_cached_weather", side_effect=_record_cached,
        ) as mock_cached,
    ):
        client.get(f"/conversations/{conv_id}")

    # Only ever called once, for the latest trip -- never for the older one.
    mock_refresh.assert_called_once()
    assert refreshed_trip_ids == [latest_trip_id]
    mock_cached.assert_called_once()
    assert cached_trip_ids == [older_trip_id]


# ---------- list_conversations pagination ----------

def test_list_conversations_respects_limit_and_offset():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        for prompt in ("trip one", "trip two", "trip three"):
            client.post("/trips/generate", json={"prompt": prompt})

    first_page = client.get("/conversations", params={"limit": 2, "offset": 0}).json()
    second_page = client.get("/conversations", params={"limit": 2, "offset": 2}).json()

    assert len(first_page) == 2
    assert len(second_page) == 1
    assert {c["id"] for c in first_page}.isdisjoint({c["id"] for c in second_page})


def test_list_conversations_rejects_a_limit_above_the_hard_cap():
    response = client.get("/conversations", params={"limit": 99999})
    assert response.status_code == 422  # FastAPI's own Query(le=...) validation, not a silent clamp


# ---------- GET /trips (list, backs the "Your Trips" page) ----------

def test_list_trips_returns_most_recent_first():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        client.post("/trips/generate", json={"prompt": "first trip"})
        client.post("/trips/generate", json={"prompt": "second trip"})

    trips = client.get("/trips").json()
    assert len(trips) == 2
    assert trips[0]["destination"] == "Austin"  # both come from FAKE_ITINERARY; order is what's under test
    assert trips[0]["created_at"] >= trips[1]["created_at"]


def test_list_trips_collapses_multiple_edit_turns_to_one_card():
    # Regression test: a real user conversation refined 4 times showed up
    # as 4 separate "Miami" cards on Your Trips, because generate_trip
    # creates a brand-new Trip row on every edit_trip turn (it never
    # updates one in place) and list_trips originally listed every row
    # unfiltered. One conversation should always be exactly one card,
    # reflecting the latest version -- confirmed here with a real
    # multi-turn edit sequence, not just a single generate call.
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = first.json()["conversation_id"]
    first_trip_id = first.json()["trip_id"]

    later_itinerary = {**FAKE_ITINERARY, "destination": "Austin (updated)"}
    with patch("app.llm_service.generate_itinerary", return_value=later_itinerary):
        for _ in range(3):
            latest = client.post(
                "/trips/generate", json={"prompt": "add a day", "conversation_id": conv_id},
            )
    latest_trip_id = latest.json()["trip_id"]

    assert latest_trip_id != first_trip_id  # really did create new rows each time

    trips = client.get("/trips").json()
    assert len(trips) == 1
    assert trips[0]["id"] == latest_trip_id
    assert trips[0]["destination"] == "Austin (updated)"


def test_list_trips_keeps_conversationless_trips_separate_not_collapsed():
    # A Trip with no conversation_id (e.g. its conversation was later
    # deleted -- Trip.conversation_id is ON DELETE SET NULL) has nothing
    # to group by. A naive `GROUP BY conversation_id` would put every such
    # trip in the same NULL group and only show the single latest one --
    # this confirms each stays its own card instead.
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    trip_id = response.json()["trip_id"]
    conv_id = response.json()["conversation_id"]

    # Detach this trip from its conversation, then delete the conversation
    # (real ON DELETE SET NULL path) so a second, genuinely
    # conversation-less trip can be created independently.
    db = SessionLocal()
    try:
        db.query(models.Trip).filter(models.Trip.id == trip_id).update({"conversation_id": None})
        db.commit()
    finally:
        db.close()
    client.delete(f"/conversations/{conv_id}")

    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        client.post("/trips/generate", json={"prompt": "another weekend in Austin"})

    trips = client.get("/trips").json()
    assert len(trips) == 2


def test_list_trips_respects_limit_and_offset():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        for prompt in ("trip one", "trip two", "trip three"):
            client.post("/trips/generate", json={"prompt": prompt})

    first_page = client.get("/trips", params={"limit": 2, "offset": 0}).json()
    second_page = client.get("/trips", params={"limit": 2, "offset": 2}).json()

    assert len(first_page) == 2
    assert len(second_page) == 1
    assert {t["id"] for t in first_page}.isdisjoint({t["id"] for t in second_page})


def test_list_trips_rejects_a_limit_above_the_hard_cap():
    response = client.get("/trips", params={"limit": 99999})
    assert response.status_code == 422


def test_list_trips_only_returns_the_current_users_trips():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        client.post("/trips/generate", json={"prompt": "my trip"})

    # Swap the authenticated user mid-test to someone who owns nothing.
    def _other_user(db=Depends(get_db)):
        user = models.User(google_sub="a-different-google-sub", email="someone-else@example.com")
        db.add(user)
        db.flush()
        return user

    app.dependency_overrides[get_current_user] = _other_user
    try:
        response = client.get("/trips")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.json() == []


def test_list_trips_includes_derived_day_count_and_status():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        response = client.post("/trips/generate", json={"prompt": "a trip with no date mentioned"})
    conv_id = response.json()["conversation_id"]

    trips = client.get("/trips").json()
    assert len(trips) == 1
    assert trips[0]["day_count"] == 1  # FAKE_ITINERARY has a single day_number: 1 item
    # No date-like text in the prompt above, so date_resolver resolves
    # nothing and this should read as a draft -- exercises the real
    # endpoint-to-trip_status wiring, not just derive_status in isolation
    # (already covered by test_trip_status.py).
    assert trips[0]["status"] == "draft"
    assert trips[0]["start_date"] is None

    # Now force a resolved start_date directly (avoids relying on fuzzy
    # prompt-text date parsing here) and set it far enough in the past that
    # a 1-day trip is unambiguously over, to confirm the "completed" branch
    # is reachable end-to-end through the same endpoint.
    db = SessionLocal()
    try:
        trip = db.query(models.Trip).filter(models.Trip.conversation_id == conv_id).first()
        trip.start_date = date(2000, 1, 1)
        db.commit()
    finally:
        db.close()

    trips_after = client.get("/trips").json()
    assert trips_after[0]["status"] == "completed"
    assert trips_after[0]["start_date"] == "2000-01-01"


# ---------- per-account daily quota (usage_quota.py) ----------

def test_generate_trip_returns_429_once_the_daily_quota_is_exhausted():
    with (
        patch("app.usage_quota.DAILY_TRIP_GENERATION_LIMIT", 2),
        patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY),
    ):
        first = client.post("/trips/generate", json={"prompt": "trip one"})
        second = client.post("/trips/generate", json={"prompt": "trip two"})
        third = client.post("/trips/generate", json={"prompt": "trip three"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert "Daily limit" in third.json()["detail"]


def test_daily_quota_blocks_before_any_llm_call_at_all():
    # The whole point of checking this first (architecture principle #1,
    # applied one step earlier than intent classification) -- a request
    # over quota shouldn't cost so much as a single Gemini call, including
    # off_topic/question turns, which also route through classify_intent.
    with (
        patch("app.usage_quota.DAILY_TRIP_GENERATION_LIMIT", 0),
        patch("app.llm_service.classify_intent") as mock_classify,
    ):
        response = client.post("/trips/generate", json={"prompt": "anything at all"})

    assert response.status_code == 429
    mock_classify.assert_not_called()


# ---------- Saved Places auto-persistence (models.SavedPlace) ----------

FAKE_ITINERARY_WITH_PLACES = {
    **FAKE_ITINERARY,
    "found_places": [
        {
            "tool": "find_nearby_places",
            "args": {"place_type": "cafe", "near": "Wynwood"},
            "result": {"results": [
                {"name": "Maman", "rating": 4.6, "address": "123 NW 2nd Ave", "price_level": "PRICE_LEVEL_MODERATE"},
                {"name": "Angelina", "rating": 4.4, "address": "456 NW 3rd Ave", "price_level": None},
            ]},
        },
    ],
}


def test_generate_trip_persists_found_places_from_the_planning_loop():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY_WITH_PLACES):
        response = client.post("/trips/generate", json={"prompt": "trip with cafes near Wynwood"})
    trip_id = response.json()["trip_id"]

    trip_response = client.get(f"/trips/{trip_id}").json()
    names = {p["name"] for p in trip_response["saved_places"]}
    assert names == {"Maman", "Angelina"}
    maman = next(p for p in trip_response["saved_places"] if p["name"] == "Maman")
    assert maman["rating"] == 4.6
    assert maman["price_level"] == "PRICE_LEVEL_MODERATE"


def test_generate_trip_never_persists_wikipedia_or_currency_results_as_places():
    fake_with_wikipedia = {
        **FAKE_ITINERARY,
        "found_places": [
            {"tool": "get_place_context", "args": {"place_name": "Austin"}, "result": {"place": "Austin", "summary": "..."}},
        ],
    }
    with patch("app.llm_service.generate_itinerary", return_value=fake_with_wikipedia):
        response = client.post("/trips/generate", json={"prompt": "trip to Austin"})
    trip_id = response.json()["trip_id"]

    trip_response = client.get(f"/trips/{trip_id}").json()
    assert trip_response["saved_places"] == []


def test_repeated_find_nearby_places_call_does_not_duplicate_saved_places():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY_WITH_PLACES):
        first = client.post("/trips/generate", json={"prompt": "trip with cafes near Wynwood"})
    conv_id = first.json()["conversation_id"]
    trip_id = first.json()["trip_id"]

    # An edit turn in the SAME conversation that re-surfaces "Maman" (a
    # trip already exists here, so this exercises the planning path's
    # dedupe against a real existing row, not just an empty table).
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY_WITH_PLACES):
        client.post("/trips/generate", json={"prompt": "add a day", "conversation_id": conv_id})

    trip_response = client.get(f"/trips/{trip_id}").json()
    maman_count = sum(1 for p in trip_response["saved_places"] if p["name"] == "Maman")
    assert maman_count == 1


def test_question_turn_persists_found_places_against_the_conversations_latest_trip():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        generate_response = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = generate_response.json()["conversation_id"]
    trip_id = generate_response.json()["trip_id"]

    qa_tool_calls = [
        {"tool": "find_nearby_places", "args": {}, "result": {"results": [
            {"name": "Radio Coffee", "rating": 4.7, "address": "4204 Menchaca Rd", "price_level": None},
        ]}},
    ]
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch(
            "app.routers.trips.agent_service.answer_question_with_tools",
            return_value=("A few spots nearby.", qa_tool_calls),
        ),
    ):
        response = client.post(
            "/trips/generate", json={"prompt": "any good coffee nearby?", "conversation_id": conv_id},
        )

    assert response.status_code == 200
    trip_response = client.get(f"/trips/{trip_id}").json()
    assert {p["name"] for p in trip_response["saved_places"]} == {"Radio Coffee"}


def test_question_turn_with_no_existing_trip_skips_persistence_cleanly():
    # No trip exists yet in a brand-new conversation -- nothing to attach
    # a found place to, should not error.
    qa_tool_calls = [
        {"tool": "find_nearby_places", "args": {}, "result": {"results": [{"name": "Some Cafe", "rating": 4.0, "address": None, "price_level": None}]}},
    ]
    with (
        patch("app.llm_service.classify_intent", return_value=("question", False)),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value=""),
        patch(
            "app.routers.trips.agent_service.answer_question_with_tools",
            return_value=("Sure, here's one.", qa_tool_calls),
        ),
    ):
        response = client.post("/trips/generate", json={"prompt": "any good coffee nearby?"})

    assert response.status_code == 200  # doesn't 500 despite nothing to attach the place to


# ---------- Pexels trip photos (GET /trips list) ----------

def test_list_trips_includes_photo_when_pexels_configured():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    with (
        patch("app.routers.trips.pexels_service.pexels_client.PEXELS_API_ENABLED", True),
        patch(
            "app.routers.trips.pexels_service.pexels_client.search_photo",
            return_value={"url": "https://images.pexels.com/austin.jpeg", "photographer": "Jane Doe", "photographer_url": "x"},
        ),
    ):
        trips = client.get("/trips").json()

    assert trips[0]["photo_url"] == "https://images.pexels.com/austin.jpeg"
    assert trips[0]["photo_credit"] == "Jane Doe"


def test_list_trips_photo_is_null_when_pexels_not_configured():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    with patch("app.routers.trips.pexels_service.pexels_client.PEXELS_API_ENABLED", False):
        trips = client.get("/trips").json()

    assert trips[0]["photo_url"] is None
    assert trips[0]["photo_credit"] is None


def test_list_trips_photo_fetched_once_then_cached_on_the_trip_row():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        client.post("/trips/generate", json={"prompt": "weekend in Austin"})

    with (
        patch("app.routers.trips.pexels_service.pexels_client.PEXELS_API_ENABLED", True),
        patch(
            "app.routers.trips.pexels_service.pexels_client.search_photo",
            return_value={"url": "https://images.pexels.com/austin.jpeg", "photographer": "Jane Doe", "photographer_url": "x"},
        ) as mock_search,
    ):
        client.get("/trips")
        client.get("/trips")

    mock_search.assert_called_once()  # second list call reads the cached Trip.photo_url instead
