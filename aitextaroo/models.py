"""Data models for AI Text-a-roo events and messages.

All models are immutable dataclasses — no Pydantic dependency required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """SSE event types emitted by the /v1/stream endpoint."""

    CONNECTED = "connected"
    MESSAGE = "message"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """An inbound SMS message received via the SSE stream.

    Attributes:
        id: Unique message identifier (UUID).
        text: The message body.
        received_at: Server timestamp when the message was received.
        channel: Always "sms" for now.
        trust_level: "low" (unverified) or "high" (PIN verified).
        has_pin: Whether the sender has a PIN configured.
    """

    id: str
    text: str
    received_at: str
    channel: str = "sms"
    trust_level: str = "low"
    has_pin: bool = False


@dataclass(frozen=True, slots=True)
class ConnectedEvent:
    """Emitted when the SSE stream is successfully opened.

    Attributes:
        user_id: Your account identifier.
        assigned_number: The phone number assigned to your account.
        server_time: Server timestamp at connection time.
    """

    user_id: str
    assigned_number: str
    server_time: str


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    """Emitted when the server closes the stream due to an error.

    Attributes:
        code: Machine-readable error code (e.g., "evicted", "reconnect_required").
        message: Human-readable description.
        retry_after: Seconds to wait before reconnecting (if applicable).
    """

    code: str
    message: str
    retry_after: int | None = None


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """A parsed SSE event from the /v1/stream endpoint.

    Exactly one of connected, message, or error will be set.

    Attributes:
        type: The event type.
        connected: Present for EventType.CONNECTED.
        message: Present for EventType.MESSAGE.
        error: Present for EventType.ERROR.
    """

    type: EventType
    connected: ConnectedEvent | None = None
    message: InboundMessage | None = None
    error: ErrorEvent | None = None
