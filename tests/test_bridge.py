"""Tests for the bridge orchestration."""

from unittest.mock import AsyncMock

import pytest

from aitextaroo.agents import Agent
from aitextaroo.bridge import Bridge, MAX_SMS_LENGTH
from aitextaroo.client import TextarooClient
from aitextaroo.models import InboundMessage


def _make_message(text: str = "hello", msg_id: str = "msg-1") -> InboundMessage:
    return InboundMessage(id=msg_id, text=text, received_at="2026-01-01T00:00:00Z")


class FakeAgent(Agent):
    """Agent that returns a canned response."""

    def __init__(self, response: str = "reply", system: str = "Be concise.") -> None:
        self._response = response
        self._system = system
        self.last_input: str | None = None

    @property
    def name(self) -> str:
        return "FakeAgent"

    @property
    def system_prompt(self) -> str:
        return self._system

    async def ask(self, text: str) -> str:
        self.last_input = text
        return self._response


class TimeoutAgent(Agent):
    """Agent that always times out."""

    @property
    def name(self) -> str:
        return "TimeoutAgent"

    async def ask(self, text: str) -> str:
        raise TimeoutError("Agent too slow")


class ErrorAgent(Agent):
    """Agent that always raises."""

    @property
    def name(self) -> str:
        return "ErrorAgent"

    async def ask(self, text: str) -> str:
        raise RuntimeError("Agent crashed")


class TestBridgePromptConstruction:
    @pytest.mark.asyncio
    async def test_first_message_includes_system_prompt(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="hi", system="You are an SMS bot.")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hello"))

        assert "[System]" in agent.last_input
        assert "You are an SMS bot." in agent.last_input
        assert "hello" in agent.last_input

    @pytest.mark.asyncio
    async def test_second_message_includes_system_and_history(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="first reply", system="Be concise.")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("first"))

        agent._response = "second reply"
        await bridge._handle(_make_message("second", msg_id="msg-2"))

        prompt = agent.last_input
        # System prompt always present
        assert "[System]" in prompt
        assert "Be concise." in prompt
        # History present
        assert "[Conversation history]" in prompt
        assert "User: first" in prompt
        assert "Assistant: first reply" in prompt
        # New message present
        assert "User: second" in prompt

    @pytest.mark.asyncio
    async def test_no_system_prompt_if_agent_has_none(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="reply", system="")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hi"))

        assert "[System]" not in agent.last_input

    @pytest.mark.asyncio
    async def test_new_command_then_message_gets_system_prompt(self) -> None:
        """After /new, the next message should still get the system prompt."""
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="reply", system="Be concise.")
        bridge = Bridge(client=client, agent=agent)

        # Send a message, then /new, then another message
        await bridge._handle(_make_message("first"))
        await bridge._handle(_make_message("/new", msg_id="msg-2"))
        await bridge._handle(_make_message("after reset", msg_id="msg-3"))

        prompt = agent.last_input
        assert "Be concise." in prompt
        assert "first" not in prompt  # History was cleared


class TestBridgeConversation:
    @pytest.mark.asyncio
    async def test_sends_agent_response(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="I'm here!")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hi"))

        client.send.assert_awaited_once_with("I'm here!")

    @pytest.mark.asyncio
    async def test_records_both_sides_after_success(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="reply")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hello"))

        assert bridge._conversation.count == 2
        msgs = bridge._conversation.messages
        assert msgs[0].role == "user"
        assert msgs[0].text == "hello"
        assert msgs[1].role == "assistant"
        assert msgs[1].text == "reply"

    @pytest.mark.asyncio
    async def test_no_history_recorded_on_agent_error(self) -> None:
        """If the agent fails, neither message should be in history."""
        client = AsyncMock(spec=TextarooClient)
        agent = ErrorAgent()
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hello"))

        assert bridge._conversation.is_empty

    @pytest.mark.asyncio
    async def test_no_history_recorded_on_timeout(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = TimeoutAgent()
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hello"))

        assert bridge._conversation.is_empty

    @pytest.mark.asyncio
    async def test_truncates_long_response(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="x" * 2000)
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hi"))

        sent_text = client.send.call_args[0][0]
        assert len(sent_text) == MAX_SMS_LENGTH
        assert sent_text.endswith("...")

    @pytest.mark.asyncio
    async def test_strips_markdown_before_sending(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="**Bold** and `code`")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hi"))

        sent_text = client.send.call_args[0][0]
        assert sent_text == "Bold and code"

    @pytest.mark.asyncio
    async def test_empty_response_not_sent(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hi"))

        client.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_timeout_sends_apology(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = TimeoutAgent()
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hi"))

        sent_text = client.send.call_args[0][0]
        assert "too long" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_error_sends_apology(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = ErrorAgent()
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("hi"))

        sent_text = client.send.call_args[0][0]
        assert "wrong" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_send_failure_does_not_raise(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        client.send.side_effect = RuntimeError("Network error")
        agent = FakeAgent(response="reply")
        bridge = Bridge(client=client, agent=agent)

        # Should not raise
        await bridge._handle(_make_message("hi"))


class TestBridgeCommands:
    @pytest.mark.asyncio
    async def test_slash_command_handled_without_agent(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="should not be called")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("/help"))

        sent_text = client.send.call_args[0][0]
        assert "/help" in sent_text
        assert agent.last_input is None  # Agent was not called

    @pytest.mark.asyncio
    async def test_new_command_clears_history(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        agent = FakeAgent(response="reply")
        bridge = Bridge(client=client, agent=agent)

        await bridge._handle(_make_message("first"))
        await bridge._handle(_make_message("second", msg_id="msg-2"))
        assert bridge._conversation.count == 4

        await bridge._handle(_make_message("/new", msg_id="msg-3"))
        assert bridge._conversation.is_empty
