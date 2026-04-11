"""SMS-to-agent bridge for AI Text-a-roo.

Connects to the AI Text-a-roo SSE stream, forwards inbound SMS
messages to a local AI agent (with conversation context), and sends
the agent's formatted responses back as SMS.

This module is orchestration — it delegates to:
- agents.py for agent communication
- conversation.py for history management
- commands.py for /slash command handling
- formatting.py for SMS-friendly output
- client.py for API communication
"""

from __future__ import annotations

import logging
from pathlib import Path

from aitextaroo.agents import Agent
from aitextaroo.client import TextarooClient
from aitextaroo.commands import CommandRouter
from aitextaroo.conversation import Conversation
from aitextaroo.formatting import format_for_sms
from aitextaroo.models import InboundMessage

logger = logging.getLogger(__name__)

# SMS character limit. Responses exceeding this are truncated.
MAX_SMS_LENGTH = 1600


class Bridge:
    """Bridges SMS messages between AI Text-a-roo and a local AI agent.

    The bridge's message flow:
    1. Receive inbound SMS via SSE stream.
    2. If it's a /command, handle locally (no agent call).
    3. Otherwise, build full prompt (system + history + message).
    4. Send to agent, get response.
    5. Record both messages in conversation history.
    6. Format the response for SMS and send it back.

    The bridge owns prompt construction — the agent just receives
    a complete prompt and returns a response. This keeps system
    prompt and conversation context management in one place.

    Args:
        client: An authenticated TextarooClient.
        agent: An Agent implementation that processes messages.
        max_history: Max messages to keep in conversation context.
        sessions_dir: Directory for persistent session files.
            None = in-memory only (original behavior).
    """

    def __init__(
        self,
        client: TextarooClient,
        agent: Agent,
        max_history: int = 20,
        sessions_dir: Path | None = None,
    ) -> None:
        self._client = client
        self._agent = agent

        if sessions_dir is not None:
            self._conversation = Conversation.load_latest(
                sessions_dir, max_messages=max_history,
            )
            logger.info(
                "Session %s loaded (%d messages)",
                self._conversation.session_id,
                self._conversation.count,
            )
        else:
            self._conversation = Conversation(max_messages=max_history)

        self._commands = CommandRouter(
            agent_name=agent.name,
            conversation=self._conversation,
        )

    async def run(self) -> None:
        """Listen for SMS and bridge them to the agent.

        Runs indefinitely. The TextarooClient handles SSE reconnection
        automatically. Call this from asyncio.run() or as a task.
        """
        try:
            async for message in self._client.listen():
                await self._handle(message)
        finally:
            await self._agent.close()
            await self._client.close()

    async def _handle(self, message: InboundMessage) -> None:
        """Route an inbound SMS to commands or the agent."""
        text = message.text.strip()

        if self._commands.is_command(text):
            response = self._commands.handle(text)
            await self._send(response)
            return

        await self._handle_conversation(message.id, text)

    async def _handle_conversation(self, message_id: str, text: str) -> None:
        """Build prompt, call agent, record history, send reply."""
        logger.info("Inbound SMS [%s]: %s", message_id, text[:50])

        prompt = self._build_prompt(text)

        # Call the agent
        try:
            response = await self._agent.ask(prompt)
        except TimeoutError:
            logger.error("Agent timed out on message %s", message_id)
            await self._send("Sorry, I took too long to respond. Try again?")
            return
        except Exception:
            logger.exception("Agent error on message %s", message_id)
            await self._send("Sorry, something went wrong. Try again?")
            return

        if not response:
            logger.warning("Agent returned empty response for %s", message_id)
            return

        # Record both sides only after a successful response.
        # This keeps history balanced — no orphaned user messages.
        self._conversation.add_user_message(text)
        self._conversation.add_assistant_message(response)
        self._commands.increment_message_count()

        # Format for SMS and send
        formatted = format_for_sms(response)
        if len(formatted) > MAX_SMS_LENGTH:
            formatted = formatted[: MAX_SMS_LENGTH - 3] + "..."
            logger.warning("Response truncated to %d chars", MAX_SMS_LENGTH)

        await self._send(formatted)
        logger.info("Reply sent for %s", message_id)

    def _build_prompt(self, text: str) -> str:
        """Assemble the complete prompt: system + history + new message.

        The bridge owns prompt construction so that system instructions
        and conversation context are always included, regardless of
        which agent is being used or how many messages have been sent.
        """
        parts: list[str] = []

        # System prompt — always included so the agent stays in character
        system = self._agent.system_prompt
        if system:
            parts.append(f"[System]\n{system}")

        # Conversation history — provides multi-turn context
        context = self._conversation.format_as_context()
        if context:
            parts.append(context)

        # The new message
        parts.append(f"[New message]\nUser: {text}")

        return "\n\n".join(parts)

    async def _send(self, text: str) -> None:
        """Send a reply, logging but not raising on failure."""
        try:
            await self._client.send(text)
        except Exception:
            logger.exception("Failed to send reply")
