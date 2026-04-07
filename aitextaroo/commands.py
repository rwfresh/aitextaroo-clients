"""SMS command handling for the bridge.

Dispatches /slash commands from inbound SMS messages. Commands
return a response string directly — no agent invocation needed.

Commands are intentionally minimal. SMS is a constrained medium;
every command the user has to remember is friction.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from aitextaroo.conversation import Conversation


class CommandRouter:
    """Routes /slash commands and returns response text.

    Args:
        agent_name: Name of the active agent (for /status).
        conversation: The active conversation (for /new).
        start_time: Process start time (for /status uptime).
    """

    # Prefix that identifies a command. Single character, universal.
    PREFIX = "/"

    def __init__(
        self,
        agent_name: str,
        conversation: Conversation,
        start_time: float | None = None,
    ) -> None:
        self._agent_name = agent_name
        self._conversation = conversation
        self._start_time = start_time or time.time()
        self._message_count = 0

        self._commands: dict[str, tuple[str, Callable[[], str]]] = {
            "help": ("List commands", self._cmd_help),
            "new": ("Start a new conversation", self._cmd_new),
            "status": ("Show bridge status", self._cmd_status),
        }

    @property
    def message_count(self) -> int:
        return self._message_count

    def increment_message_count(self) -> None:
        """Called by the bridge after each non-command message is processed."""
        self._message_count += 1

    def is_command(self, text: str) -> bool:
        """Check if the text is a /slash command."""
        return text.startswith(self.PREFIX) and len(text) > 1

    def handle(self, text: str) -> str:
        """Dispatch a command and return the response text.

        Args:
            text: The full message text (e.g., "/help").

        Returns:
            Response string to send back via SMS.
        """
        # Parse command name (strip prefix, take first word, lowercase)
        parts = text[len(self.PREFIX):].strip().split(maxsplit=1)
        name = parts[0].lower() if parts else ""

        entry = self._commands.get(name)
        if entry is None:
            return f"Unknown command: /{name}\nType /help for available commands."

        _, handler = entry
        return handler()

    def _cmd_help(self) -> str:
        lines = ["Available commands:"]
        for name, (description, _) in self._commands.items():
            lines.append(f"  /{name} — {description}")
        return "\n".join(lines)

    def _cmd_new(self) -> str:
        self._conversation.clear()
        return "Conversation cleared. Fresh start!"

    def _cmd_status(self) -> str:
        uptime = time.time() - self._start_time
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            uptime_str = f"{hours}h {minutes}m"
        elif minutes > 0:
            uptime_str = f"{minutes}m {seconds}s"
        else:
            uptime_str = f"{seconds}s"

        return (
            f"Agent: {self._agent_name}\n"
            f"Uptime: {uptime_str}\n"
            f"Messages: {self._message_count}\n"
            f"History: {self._conversation.count} messages"
        )
