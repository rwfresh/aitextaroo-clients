"""Tests for data models."""

from aitextaroo.models import (
    ConnectedEvent,
    ErrorEvent,
    EventType,
    InboundMessage,
    StreamEvent,
)


class TestInboundMessage:
    def test_create_with_defaults(self) -> None:
        msg = InboundMessage(id="abc", text="hello", received_at="2026-01-01T00:00:00Z")
        assert msg.id == "abc"
        assert msg.text == "hello"
        assert msg.channel == "sms"
        assert msg.trust_level == "low"
        assert msg.has_pin is False

    def test_immutable(self) -> None:
        msg = InboundMessage(id="abc", text="hello", received_at="2026-01-01T00:00:00Z")
        try:
            msg.text = "changed"  # type: ignore[misc]
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestStreamEvent:
    def test_connected_event(self) -> None:
        event = StreamEvent(
            type=EventType.CONNECTED,
            connected=ConnectedEvent(
                user_id="u1", assigned_number="+1234", server_time="now"
            ),
        )
        assert event.type == EventType.CONNECTED
        assert event.connected is not None
        assert event.message is None
        assert event.error is None

    def test_message_event(self) -> None:
        msg = InboundMessage(id="m1", text="hi", received_at="now")
        event = StreamEvent(type=EventType.MESSAGE, message=msg)
        assert event.type == EventType.MESSAGE
        assert event.message is msg

    def test_error_event(self) -> None:
        err = ErrorEvent(code="evicted", message="bye", retry_after=30)
        event = StreamEvent(type=EventType.ERROR, error=err)
        assert event.error is not None
        assert event.error.retry_after == 30


class TestEventType:
    def test_string_values(self) -> None:
        assert EventType.CONNECTED == "connected"
        assert EventType.MESSAGE == "message"
        assert EventType.ERROR == "error"
