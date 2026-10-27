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

import asyncio
import logging
from pathlib import Path

import httpx

from aitextaroo.agents import Agent
from aitextaroo.client import TextarooClient, TextarooError
from aitextaroo.commands import CommandRouter
from aitextaroo.conversation import Conversation
from aitextaroo.formatting import format_for_sms
from aitextaroo.models import InboundMessage

logger = logging.getLogger(__name__)

# SMS character limit. Responses exceeding this are truncated.
MAX_SMS_LENGTH = 1600

# A text that certainly wasn't sent (the API restarting for a deploy, the
# carrier turning it down, the per-minute limit) is tried again after each
# of these delays, in seconds. Nothing went out, so the owner can't get it twice.
RETRY_DELAYS = (2.0, 5.0, 15.0)
# The longest the bridge waits when the API says how long (retry_after).
MAX_RETRY_AFTER = 60.0

# Texted in place of a reply the API refuses, so the owner isn't left waiting.
REFUSED_NOTICE = "Sorry, my reply couldn't be sent. Try asking again?"

# What the API's gateway answers while the API restarts: the request never reached it.
_NOT_REACHED = frozenset({502, 503})
# The API sends nothing before these: the carrier turned the text down, or a limit.
_NOT_SENT = frozenset({"carrier_error", "rate_limit_exceeded"})
# Statuses where a notice can't help: the key doesn't work, or a limit the API
# already texts the owner about.
_NO_NOTICE = frozenset({401, 403, 429})


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

        Runs until cancelled; the TextarooClient handles SSE reconnection
        automatically. Call this from asyncio.run() or as a task.

        Raises:
            TextarooError: When the stream stops for good: the key was
                rejected ("unauthorized") or removed from the account
                ("credential_revoked"), or another stream took over the
                account ("evicted").
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
        # Before Python 3.11, asyncio.TimeoutError isn't the built-in TimeoutError.
        except (TimeoutError, asyncio.TimeoutError):
            logger.error("Agent timed out on message %s", message_id)
            await self._send("Sorry, I took too long to respond. Try again?")
            return
        except Exception:
            logger.exception("Agent error on message %s", message_id)
            await self._send("Sorry, something went wrong. Try again?")
            return

        # Format for SMS (markdown can leave nothing at all)
        formatted = format_for_sms(response) if response else ""
        if not formatted:
            logger.warning("Agent returned empty response for %s", message_id)
            return
        if len(formatted) > MAX_SMS_LENGTH:
            formatted = formatted[: MAX_SMS_LENGTH - 3] + "..."
            logger.warning("Response truncated to %d chars", MAX_SMS_LENGTH)

        if not await self._send(formatted):
            return

        # Record both sides only once the reply went out, so the history
        # matches what the owner saw (and has no orphaned user messages).
        self._conversation.add_user_message(text)
        self._conversation.add_assistant_message(response)
        self._commands.increment_message_count()
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

    async def _send(self, text: str) -> bool:
        """Text the owner; returns whether it went out. Never raises (but can be cancelled).

        A text that certainly wasn't sent is tried again (RETRY_DELAYS). One
        the API refuses is replaced with REFUSED_NOTICE, so the owner knows
        the reply isn't coming. Every failure is logged with the API's reason.
        """
        error = await self._try_send(text)
        if error is None:
            return True
        if _refused(error):
            logger.error("The API refused a reply (%s); telling the owner", _reason(error))
            notice_error = await self._try_send(REFUSED_NOTICE)
            if notice_error is not None:
                logger.error("Couldn't text the owner that either (%s)", _reason(notice_error))
        else:
            logger.error("Couldn't send a reply (%s)", _reason(error), exc_info=_unexpected(error))
        return False

    async def _try_send(self, text: str) -> Exception | None:
        """Send, trying again while nothing was sent: the last error, or None once it's sent."""
        delays = list(RETRY_DELAYS)
        while True:
            try:
                await self._client.send(text)
                return None
            except Exception as exc:  # cancellation isn't an Exception: it ends the bridge
                if not delays or not _nothing_sent(exc):
                    return exc
                wait = _retry_wait(exc, delays.pop(0))
                logger.warning("Text not sent (%s); trying again in %g s", _reason(exc), wait)
                await asyncio.sleep(wait)


def _nothing_sent(exc: Exception) -> bool:
    """Whether a failed send certainly texted nobody, so trying again can't text the owner twice."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return True  # the request never left this machine
    return isinstance(exc, TextarooError) and (
        exc.status_code in _NOT_REACHED or exc.code in _NOT_SENT
    )


def _refused(exc: Exception) -> bool:
    """Whether the API turned a text down for what it says, and the owner can be told."""
    return (
        isinstance(exc, TextarooError)
        and 400 <= exc.status_code < 500
        and exc.status_code not in _NO_NOTICE
    )


def _retry_wait(exc: Exception, delay: float) -> float:
    """Seconds before the next try: what the API asked for (up to MAX_RETRY_AFTER), else delay."""
    retry_after = exc.retry_after if isinstance(exc, TextarooError) else None
    return delay if retry_after is None else min(max(float(retry_after), delay), MAX_RETRY_AFTER)


def _reason(exc: Exception) -> str:
    """A failure for the log: the API's code and message, or the error's type (never the text)."""
    if isinstance(exc, TextarooError):
        return f"{exc.code}: {exc.message}"
    return type(exc).__name__


def _unexpected(exc: Exception) -> bool:
    """Whether a failure is worth a traceback in the log: not one from the API or the network."""
    return not isinstance(exc, (TextarooError, httpx.HTTPError))
