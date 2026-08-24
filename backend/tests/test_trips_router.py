from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import models
from app.database import Base, SessionLocal, engine
from app.main import app

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
    with patch("app.llm_service.classify_intent", return_value="new_trip"):
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
        patch("app.llm_service.classify_intent", return_value="off_topic"),
        patch("app.llm_service.generate_itinerary") as mock_generate,
    ):
        response = client.post("/trips/generate", json={"prompt": "write me a python script"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"]
    assert body["trip_id"] is None
    mock_generate.assert_not_called()  # the entire expensive pipeline must be skipped


def test_off_topic_reply_is_saved_to_conversation():
    with patch("app.llm_service.classify_intent", return_value="off_topic"):
        response = client.post("/trips/generate", json={"prompt": "help me debug my code"})

    conv_id = response.json()["conversation_id"]
    conv = client.get(f"/conversations/{conv_id}").json()
    assert len(conv["messages"]) == 2
    assert conv["messages"][1]["trip"] is None  # no itinerary was generated


def test_question_message_calls_answer_question_not_generate_itinerary():
    with (
        patch("app.llm_service.classify_intent", return_value="question"),
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


def test_question_receives_real_chat_history_not_squashed_string():
    with patch("app.llm_service.generate_itinerary", return_value=FAKE_ITINERARY):
        first = client.post("/trips/generate", json={"prompt": "weekend in Austin"})
    conv_id = first.json()["conversation_id"]

    with (
        patch("app.llm_service.classify_intent", return_value="question"),
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
        patch("app.llm_service.classify_intent", return_value="question"),
        patch("app.llm_service.answer_question", return_value="It'll be hot.") as mock_answer,
    ):
        client.post("/trips/generate", json={"prompt": "what's the temperature there?", "conversation_id": conv_id})

    assert mock_answer.call_args.kwargs["agent_context"] == "Austin: highs of 30C, sunny."


def test_question_answer_failure_returns_502_not_500():
    with (
        patch("app.llm_service.classify_intent", return_value="question"),
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
        patch("app.llm_service.classify_intent", return_value="question"),
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
        patch("app.llm_service.classify_intent", return_value="question"),
        patch(
            "app.routers.trips.agent_service.gather_trip_context",
            return_value="Austin: highs of 32C, dry.",
        ),
        patch("app.llm_service.answer_question", return_value="It'll be hot and dry."),
    ):
        first = client.post("/trips/generate", json={"prompt": "what's the weather in Austin?"})
    conv_id = first.json()["conversation_id"]

    with (
        patch("app.llm_service.classify_intent", return_value="question"),
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
        user = models.User(id=1, email="placeholder-1@example.com")
        db.add(user)
        db.flush()
        conversation = models.Conversation(user_id=1, title="Test")
        db.add(conversation)
        db.flush()
        trip = models.Trip(user_id=1, conversation_id=conversation.id, destination="Austin", prompt="weekend in Austin")
        db.add(trip)
        db.commit()
        conv_id = conversation.id
    finally:
        db.close()

    with (
        patch("app.llm_service.classify_intent", return_value="question"),
        patch("app.routers.trips.agent_service.gather_trip_context", return_value="") as mock_fetch,
        patch("app.llm_service.answer_question", return_value="Not sure."),
    ):
        client.post(
            "/trips/generate",
            json={"prompt": "what does the temperature look like?", "conversation_id": conv_id},
        )

    mock_fetch.assert_called_once_with("what does the temperature look like?", destination="Austin")
