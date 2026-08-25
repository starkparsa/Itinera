from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel, ValidationError

from app import groq_service


class _Meta(BaseModel):
    destination: str
    total_days: int


def _fake_completion(content: str) -> Mock:
    message = Mock(content=content)
    choice = Mock(message=message)
    return Mock(choices=[choice])


def test_call_groq_plain_text():
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = _fake_completion("  A short answer.  ")

    with patch("app.groq_service._get_client", return_value=fake_client):
        result = groq_service._call_groq("a prompt")

    assert result == "A short answer."


def test_call_groq_structured_output_parses_into_schema():
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"destination": "Lisbon", "total_days": 3}'
    )

    with patch("app.groq_service._get_client", return_value=fake_client):
        result = groq_service._call_groq("a prompt", response_schema=_Meta)

    assert result == _Meta(destination="Lisbon", total_days=3)


def test_call_groq_strips_markdown_fence_before_parsing():
    # Confirmed live that some models (Gemma 4) wrap JSON in a fence even
    # when asked for JSON-only output -- defensive insurance here in case
    # the Groq model ever does the same.
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '```json\n{"destination": "Lisbon", "total_days": 3}\n```'
    )

    with patch("app.groq_service._get_client", return_value=fake_client):
        result = groq_service._call_groq("a prompt", response_schema=_Meta)

    assert result == _Meta(destination="Lisbon", total_days=3)


def test_call_groq_structured_output_uses_non_strict_json_schema():
    # Groq's strict mode requires every property listed as required, which
    # doesn't match this app's schemas (optional fields) -- confirm the
    # request is built with strict: False rather than fighting that.
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = _fake_completion(
        '{"destination": "Lisbon", "total_days": 3}'
    )

    with patch("app.groq_service._get_client", return_value=fake_client):
        groq_service._call_groq("a prompt", response_schema=_Meta)

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"]["json_schema"]["strict"] is False


def test_call_groq_invalid_json_raises():
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = _fake_completion("not valid json at all")

    with patch("app.groq_service._get_client", return_value=fake_client), pytest.raises(ValidationError):
        groq_service._call_groq("a prompt", response_schema=_Meta)


def test_call_groq_chat_maps_roles_and_returns_text():
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = _fake_completion("Sure, happy to help.")

    with patch("app.groq_service._get_client", return_value=fake_client):
        result = groq_service._call_groq_chat(
            "system prompt", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], "a question",
        )

    assert result == "Sure, happy to help."
    sent_messages = fake_client.chat.completions.create.call_args.kwargs["messages"]
    assert sent_messages[0] == {"role": "system", "content": "system prompt"}
    assert sent_messages[1] == {"role": "user", "content": "hi"}
    assert sent_messages[2] == {"role": "assistant", "content": "hello"}
    assert sent_messages[3] == {"role": "user", "content": "a question"}
