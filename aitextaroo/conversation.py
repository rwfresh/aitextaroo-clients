"""In-memory conversation history.

Tracks the back-and-forth between the SMS user and the AI agent.
Used by the bridge to provide context to stateless CLI agents so
they can maintain coherent multi-turn conversations.

Privacy: history lives in process memory only. Nothing is written
to disk or sent to AI Text-a-roo. When the bridge stops, history
is gone.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    """A single message in the conversation.

    Attributes:
        role: Who sent it — "user" or "assistant".
        text: The message content.
    """

    role: str
    text: str


class Conversation:
    """In-memory conversation history with automatic pruning.

    Stores messages as a bounded list. When the list exceeds
    max_messages, the oldest messages are removed from the front.

    Args:
        max_messages: Maximum messages to retain. Default 20
            (10 user + 10 assistant turns). Keeps token usage
            bounded while providing enough context.
    """

    def __init__(self, max_messages: int = 20) -> None:
        self._messages: deque[Message] = deque(maxlen=max_messages)

    @property
    def messages(self) -> list[Message]:
        """Current messages in chronological order."""
        return list(self._messages)

    @property
    def count(self) -> int:
        """Number of messages in history."""
        return len(self._messages)

    @property
    def is_empty(self) -> bool:
        return len(self._messages) == 0

    def add_user_message(self, text: str) -> None:
        """Record a message from the SMS user."""
        self._messages.append(Message(role="user", text=text))

    def add_assistant_message(self, text: str) -> None:
        """Record a response from the AI agent."""
        self._messages.append(Message(role="assistant", text=text))

    def clear(self) -> None:
        """Clear all history. Used by /new command."""
        self._messages.clear()

    def format_as_context(self) -> str:
        """Format the conversation as a text transcript for the agent.

        Returns an empty string if there's no history, so callers
        can simply prepend without checking.

        Example output:
            [Conversation history]
            User: Hey there
            Assistant: Hey! What's up?
            User: Tell me a joke
            Assistant: Why did the programmer...
        """
        if not self._messages:
            return ""

        lines = ["[Conversation history]"]
        for msg in self._messages:
            label = "User" if msg.role == "user" else "Assistant"
            lines.append(f"{label}: {msg.text}")

        return "\n".join(lines)
