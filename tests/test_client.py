"""Tests for the SSE client event parser."""

from aitextaroo.client import _parse_event
from aitextaroo.models import EventType


class TestParseEvent:
    def test_parse_connected(self) -> None:
        event = _parse_event(
            "connected",
            None,
            ['{"user_id": "u1", "assigned_number": "+1234", "server_time": "now"}'],
        )
        assert event is not None
        assert event.type == EventType.CONNECTED
        assert event.connected is not None
        assert event.connected.user_id == "u1"

    def test_parse_message(self) -> None:
        event = _parse_event(
            "message",
            "msg-123",
            ['{"id": "msg-123", "text": "hello", "received_at": "now", "has_pin": true}'],
        )
        assert event is not None
        assert event.type == EventType.MESSAGE
        assert event.message is not None
        assert event.message.text == "hello"
        assert event.message.has_pin is True

    def test_parse_error(self) -> None:
        event = _parse_event(
            "error",
            None,
            ['{"code": "evicted", "message": "kicked", "retry_after": 30}'],
        )
        assert event is not None
        assert event.type == EventType.ERROR
        assert event.error is not None
        assert event.error.code == "evicted"
        assert event.error.retry_after == 30

    def test_parse_unknown_type(self) -> None:
        event = _parse_event("unknown_type", None, ['{"foo": "bar"}'])
        assert event is None

    def test_parse_empty_data(self) -> None:
        event = _parse_event("message", None, [])
        assert event is None

    def test_parse_invalid_json(self) -> None:
        event = _parse_event("message", None, ["not json"])
        assert event is None

    def test_parse_message_defaults(self) -> None:
        event = _parse_event("message", None, ['{"id": "1", "text": "hi", "received_at": "now"}'])
        assert event is not None
        assert event.message is not None
        assert event.message.channel == "sms"
        assert event.message.trust_level == "low"
        assert event.message.has_pin is False
