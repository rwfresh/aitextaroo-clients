"""In-memory conversation history with optional file persistence.

Tracks the back-and-forth between the SMS user and the AI agent.
Used by the bridge to provide context to stateless CLI agents so
they can maintain coherent multi-turn conversations.

Two modes:
- In-memory only (sessions_dir=None): history lives in process memory.
  When the bridge stops, history is gone. Original behavior.
- Persistent (sessions_dir=Path): messages appended to a JSONL file.
  Bridge restart loads the most recent session. /new creates a new file.

Privacy: persistent files live on the user's machine only. Nothing is
sent to AI Text-a-roo. The gateway never sees conversation history.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Message:
    """A single message in the conversation.

    Attributes:
        role: Who sent it — "user" or "assistant".
        text: The message content.
        ts: Unix timestamp (seconds). Only used for persistence.
    """

    role: str
    text: str
    ts: float = 0.0

    _VALID_ROLES: ClassVar[frozenset[str]] = frozenset({"user", "assistant"})

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line."""
        return json.dumps({"role": self.role, "text": self.text, "ts": self.ts})

    @classmethod
    def from_dict(cls, data: dict) -> Message | None:
        """Deserialize from a parsed JSON dict. Returns None on invalid data."""
        role = data.get("role", "")
        text = data.get("text", "")
        if role not in cls._VALID_ROLES or not isinstance(text, str):
            return None
        return cls(role=role, text=text, ts=data.get("ts", 0.0))


class Conversation:
    """In-memory conversation history with automatic pruning.

    Stores messages as a bounded deque. When the deque exceeds
    max_messages, the oldest messages are removed from the front.

    If sessions_dir is provided, messages are also appended to a
    JSONL file on disk. Bridge restart loads the most recent session.
    /new creates a new session file; old ones are preserved.

    Args:
        max_messages: Maximum messages to retain in the deque.
            Default 20 (10 user + 10 assistant turns).
        sessions_dir: Directory for session files. None = in-memory only.
        session_id: Explicit session ID. If None and sessions_dir is set,
            a new session ID is generated.
    """

    def __init__(
        self,
        max_messages: int = 20,
        sessions_dir: Path | None = None,
        session_id: str | None = None,
    ) -> None:
        self._messages: deque[Message] = deque(maxlen=max_messages)
        self._max_messages = max_messages
        self._sessions_dir = sessions_dir
        self._session_id = session_id

        if sessions_dir is not None:
            sessions_dir.mkdir(parents=True, exist_ok=True)
            if session_id is None:
                self._session_id = _generate_session_id()
            # Touch the file so it exists even if no messages are added
            self._session_path.touch()

    @classmethod
    def load_latest(cls, sessions_dir: Path, max_messages: int = 20) -> Conversation:
        """Load the most recently modified session, or create a new one.

        Scans sessions_dir for .jsonl files, picks the one with the
        most recent mtime, and loads the last max_messages lines.

        Args:
            sessions_dir: Directory containing session files.
            max_messages: Maximum messages to retain.

        Returns:
            A Conversation populated from the latest session file.
        """
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_files = sorted(
            sessions_dir.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not session_files:
            conv = cls(max_messages=max_messages, sessions_dir=sessions_dir)
            logger.info("No existing sessions. Created new session %s", conv.session_id)
            return conv

        latest = session_files[0]
        session_id = latest.stem

        conv = cls(
            max_messages=max_messages,
            sessions_dir=sessions_dir,
            session_id=session_id,
        )
        conv._load_from_file(latest)
        logger.info(
            "Loaded session %s (%d messages)",
            session_id, conv.count,
        )
        return conv

    @property
    def session_id(self) -> str | None:
        """Current session ID, or None if in-memory only."""
        return self._session_id

    @property
    def _session_path(self) -> Path:
        """Path to the current session file. Only valid when persistent."""
        assert self._sessions_dir is not None
        return self._sessions_dir / f"{self._session_id}.jsonl"

    @property
    def messages(self) -> list[Message]:
        """Current messages in chronological order."""
        return list(self._messages)

    @property
    def count(self) -> int:
        """Number of messages in the deque."""
        return len(self._messages)

    @property
    def is_empty(self) -> bool:
        return len(self._messages) == 0

    def add_user_message(self, text: str) -> None:
        """Record a message from the SMS user."""
        self._add(Message(role="user", text=text, ts=_now()))

    def add_assistant_message(self, text: str) -> None:
        """Record a response from the AI agent."""
        self._add(Message(role="assistant", text=text, ts=_now()))

    def new_session(self) -> str:
        """Start a new session. Old session file is preserved.

        Returns:
            The new session ID.
        """
        self._messages.clear()
        new_id = _generate_session_id()
        self._session_id = new_id

        if self._sessions_dir is not None:
            self._session_path.touch()
            logger.info("New session %s", new_id)

        return new_id

    def clear(self) -> None:
        """Clear history. Creates a new session file if persistent."""
        if self._sessions_dir is not None:
            self.new_session()
        else:
            self._messages.clear()

    def session_count(self) -> int:
        """Count session files on disk. Returns 0 if not persistent."""
        if self._sessions_dir is None:
            return 0
        return len(list(self._sessions_dir.glob("*.jsonl")))

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

    def _add(self, message: Message) -> None:
        """Add a message to the deque and persist if configured."""
        self._messages.append(message)
        if self._sessions_dir is not None:
            self._append_to_file(message)

    def _append_to_file(self, message: Message) -> None:
        """Append a single message to the session file."""
        try:
            with open(self._session_path, "a", encoding="utf-8") as f:
                f.write(message.to_jsonl() + "\n")
                f.flush()
        except OSError:
            logger.exception("Failed to write to session file %s", self._session_path)

    def _load_from_file(self, path: Path) -> None:
        """Load messages from a JSONL file into the deque."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            logger.exception("Failed to read session file %s", path)
            return

        # Only load the last max_messages lines to match deque capacity
        recent_lines = lines[-self._max_messages:] if lines else []

        for line_num, line in enumerate(recent_lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping corrupt line %d in %s", line_num, path.name)
                continue

            msg = Message.from_dict(data)
            if msg is None:
                logger.warning("Skipping invalid message at line %d in %s", line_num, path.name)
                continue

            self._messages.append(msg)


def _generate_session_id() -> str:
    """Generate a short unique session ID."""
    return uuid.uuid4().hex[:8]


def _now() -> float:
    """Current time as Unix timestamp. Extracted for testability."""
    import time
    return time.time()
