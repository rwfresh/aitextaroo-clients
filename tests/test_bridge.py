"""Tests for the bridge orchestration."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from aitextaroo import bridge as bridge_module
from aitextaroo.agents import Agent
from aitextaroo.bridge import MAX_RETRY_AFTER, MAX_SMS_LENGTH, REFUSED_NOTICE, RETRY_DELAYS, Bridge
from aitextaroo.client import TextarooClient, TextarooError
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


class RaisingAgent(Agent):
    """Agent that always raises the given exception."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    @property
    def name(self) -> str:
        return "RaisingAgent"

    async def ask(self, text: str) -> str:
        raise self._error


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
    async def test_asyncio_timeout_sends_apology(self, monkeypatch) -> None:
        # CliAgent raises asyncio.TimeoutError. On Python 3.10 that's a class of
        # its own, not the built-in TimeoutError; recreate that here.
        class Py310AsyncioTimeoutError(Exception):
            pass

        monkeypatch.setattr(asyncio, "TimeoutError", Py310AsyncioTimeoutError)
        client = AsyncMock(spec=TextarooClient)
        bridge = Bridge(client=client, agent=RaisingAgent(Py310AsyncioTimeoutError()))

        await bridge._handle(_make_message("hi"))

        assert "too long" in client.send.call_args[0][0].lower()
        assert bridge._conversation.is_empty

    @pytest.mark.asyncio
    async def test_real_asyncio_timeout_sends_apology(self) -> None:
        client = AsyncMock(spec=TextarooClient)
        bridge = Bridge(client=client, agent=RaisingAgent(asyncio.TimeoutError()))

        await bridge._handle(_make_message("hi"))

        assert "too long" in client.send.call_args[0][0].lower()

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


# ── Replies that don't go out ───────────────────────────────


REPLY = "Dinner is at 7."


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """The bridge's waits between tries, recorded instead of slept."""
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(bridge_module, "_sleep", sleep)
    return waits


def _bridge(*outcomes: object) -> tuple[Bridge, AsyncMock]:
    """A bridge whose client's sends go these ways in turn (an exception, or a message id)."""
    client = AsyncMock(spec=TextarooClient)
    client.send.side_effect = list(outcomes)
    return Bridge(client=client, agent=FakeAgent(response=REPLY)), client


def _sent(client: AsyncMock) -> list[str]:
    return [call.args[0] for call in client.send.call_args_list]


def _api_error(status: int, code: str, retry_after: float | None = None) -> TextarooError:
    return TextarooError(
        code=code, message=f"{code} from the API", status_code=status, retry_after=retry_after
    )


class TestBridgeSendFailures:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", [
        _api_error(502, "http_error"),  # the API restarting for a deploy
        _api_error(503, "http_error"),
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("slow"),
        httpx.PoolTimeout("busy"),
    ])
    async def test_a_text_that_wasnt_sent_is_tried_again(self, sleeps, failure) -> None:
        bridge, client = _bridge(failure, failure, "msg-1")

        await bridge._handle(_make_message("When's dinner?"))

        assert _sent(client) == [REPLY] * 3
        assert sleeps == list(RETRY_DELAYS[:2])
        assert bridge._conversation.count == 2  # recorded once it went out

    @pytest.mark.asyncio
    async def test_it_gives_up_after_the_last_try(self, sleeps, caplog) -> None:
        bridge, client = _bridge(*[_api_error(503, "http_error")] * (len(RETRY_DELAYS) + 1))

        with caplog.at_level(logging.WARNING, logger="aitextaroo.bridge"):
            await bridge._handle(_make_message("When's dinner?"))

        # No notice: it couldn't get through either.
        assert _sent(client) == [REPLY] * (len(RETRY_DELAYS) + 1)
        assert sleeps == list(RETRY_DELAYS)
        assert bridge._conversation.is_empty  # the owner never got it
        assert "Couldn't send a reply (http_error: http_error from the API)" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", [
        httpx.ReadTimeout("no answer"),  # the API may have sent it
        httpx.RemoteProtocolError("cut off"),
        _api_error(504, "http_error"),
        _api_error(500, "internal_error"),
        _api_error(200, "invalid_response"),
        RuntimeError("bug"),
    ])
    async def test_a_text_that_may_have_gone_out_isnt_sent_twice(
        self, sleeps, caplog, failure
    ) -> None:
        bridge, client = _bridge(failure)

        with caplog.at_level(logging.ERROR, logger="aitextaroo.bridge"):
            await bridge._handle(_make_message("When's dinner?"))

        assert _sent(client) == [REPLY]
        assert sleeps == []
        assert bridge._conversation.count == 2  # the owner may have it
        assert "A reply may not have been sent" in caplog.text

    @pytest.mark.asyncio
    async def test_an_unexpected_failure_logs_its_traceback(self, sleeps, caplog) -> None:
        bridge, _client = _bridge(RuntimeError("bug"))

        with caplog.at_level(logging.ERROR, logger="aitextaroo.bridge"):
            await bridge._handle(_make_message("When's dinner?"))

        (record,) = [r for r in caplog.records if "may not have been sent" in r.getMessage()]
        assert record.exc_info is not None and record.exc_info[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_a_refused_reply_is_replaced_with_a_notice(self, sleeps, caplog) -> None:
        bridge, client = _bridge(_api_error(422, "validation_error"), "msg-1")

        with caplog.at_level(logging.ERROR, logger="aitextaroo.bridge"):
            await bridge._handle(_make_message("When's dinner?"))

        assert _sent(client) == [REPLY, REFUSED_NOTICE]
        assert bridge._conversation.is_empty
        assert "refused a reply (validation_error: validation_error from the API)" in caplog.text
        assert REPLY not in caplog.text  # the log never carries the texts

    @pytest.mark.asyncio
    async def test_a_notice_that_fails_too_is_logged(self, sleeps, caplog) -> None:
        refused = _api_error(400, "invalid_request")
        bridge, client = _bridge(refused, refused)

        with caplog.at_level(logging.ERROR, logger="aitextaroo.bridge"):
            await bridge._handle(_make_message("When's dinner?"))

        assert _sent(client) == [REPLY, REFUSED_NOTICE]  # one notice, no loop
        assert "Couldn't text the owner that either (invalid_request" in caplog.text

    @pytest.mark.asyncio
    async def test_a_refused_command_reply_gets_the_notice_too(self, sleeps) -> None:
        bridge, client = _bridge(_api_error(422, "validation_error"), "msg-1")

        await bridge._handle(_make_message("/help"))

        assert _sent(client)[1] == REFUSED_NOTICE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", [
        _api_error(429, "daily_limit_reached"),  # the API texts the owner about this itself
        _api_error(401, "unauthorized"),  # the key stopped working: the stream ends too
        _api_error(403, "forbidden"),
        _api_error(500, "carrier_error"),  # the carrier turned it down; it would again
    ])
    async def test_no_retry_or_notice_when_neither_can_help(self, sleeps, failure) -> None:
        bridge, client = _bridge(failure)

        await bridge._handle(_make_message("When's dinner?"))

        assert _sent(client) == [REPLY]
        assert sleeps == []
        assert bridge._conversation.is_empty  # none of these sent anything

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("retry_after", "wait"), [
        (30, 30.0),
        (600, MAX_RETRY_AFTER),
        (None, RETRY_DELAYS[0]),
        (10**400, RETRY_DELAYS[0]),  # too big for a float: ignored
        (float("nan"), RETRY_DELAYS[0]),
        (-5, RETRY_DELAYS[0]),
    ])
    async def test_the_per_minute_limit_waits_as_long_as_the_api_asks(
        self, sleeps, retry_after, wait
    ) -> None:
        bridge, client = _bridge(_api_error(429, "rate_limit_exceeded", retry_after), "msg-1")

        await bridge._handle(_make_message("When's dinner?"))

        assert _sent(client) == [REPLY, REPLY]
        assert sleeps == [wait]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("response", ["```\n```", "---", "  \n  "])
    async def test_a_reply_that_formats_to_nothing_isnt_sent(self, response) -> None:
        client = AsyncMock(spec=TextarooClient)
        bridge = Bridge(client=client, agent=FakeAgent(response=response))

        await bridge._handle(_make_message("hi"))

        client.send.assert_not_called()
        assert bridge._conversation.is_empty

    @pytest.mark.asyncio
    async def test_cancelling_stops_the_retries(self, monkeypatch) -> None:
        slept = asyncio.Event()

        async def sleep(seconds: float) -> None:
            slept.set()
            await asyncio.Event().wait()  # until cancelled

        monkeypatch.setattr(bridge_module, "_sleep", sleep)
        bridge, client = _bridge(_api_error(503, "http_error"), "msg-1")
        task = asyncio.create_task(bridge._handle(_make_message("hi")))
        await slept.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert _sent(client) == [REPLY]


class TestBridgeSendFailuresOverHttp:
    """The same, through a real TextarooClient and the API's real error bodies."""

    def _bridge(self, *responses: httpx.Response) -> tuple[Bridge, list[str]]:
        pending = list(responses)
        texts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            texts.append(json.loads(request.content)["text"])
            return pending.pop(0)

        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://test.com"
        )
        return Bridge(client=client, agent=FakeAgent(response=REPLY)), texts

    @pytest.mark.asyncio
    async def test_the_gateways_502_page_is_tried_again(self, sleeps) -> None:
        gateway = httpx.Response(502, text="<html>Application failed to respond</html>")
        bridge, texts = self._bridge(gateway, httpx.Response(200, json=SENT))

        await bridge._handle(_make_message("When's dinner?"))

        assert texts == [REPLY, REPLY]
        assert bridge._conversation.count == 2

    @pytest.mark.asyncio
    async def test_the_apis_refusal_gets_the_notice(self, sleeps) -> None:
        refusal = httpx.Response(
            422, json={"detail": [{"loc": ["body", "text"], "msg": "Value error, too long"}]}
        )
        bridge, texts = self._bridge(refusal, httpx.Response(200, json=SENT))

        await bridge._handle(_make_message("When's dinner?"))

        assert texts == [REPLY, REFUSED_NOTICE]

    @pytest.mark.asyncio
    async def test_the_per_minute_limit_waits_what_the_api_says(self, sleeps) -> None:
        limited = httpx.Response(429, json={"error": {
            "code": "rate_limit_exceeded", "message": "Per-minute rate limit exceeded.",
            "retry_after": 60,
        }})
        bridge, texts = self._bridge(limited, httpx.Response(200, json=SENT))

        await bridge._handle(_make_message("When's dinner?"))

        assert texts == [REPLY, REPLY]
        assert sleeps == [60.0]


SENT = {"status": "sent", "message_id": "msg-1"}
