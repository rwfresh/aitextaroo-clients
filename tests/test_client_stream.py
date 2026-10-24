"""Tests for listen(): when the SSE stream reconnects and when it stops for good."""

import contextlib
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aitextaroo.client import STREAM_STOPS, TextarooClient, TextarooError

CONNECTED = ("connected", None, {"user_id": "u1", "assigned_number": "+15551110000"})


def _message(msg_id: str, text: str) -> tuple[str, str, dict]:
    return ("message", msg_id, {"id": msg_id, "text": text, "received_at": "now"})


def _error(code: str, message: str = "server says") -> tuple[str, None, dict]:
    return ("error", None, {"code": code, "message": message})


def _sse(*events: tuple[str, str | None, dict]) -> httpx.Response:
    """One stream connection's worth of SSE events, then the server hangs up."""
    lines = []
    for name, event_id, data in events:
        lines.append(f"event: {name}")
        if event_id:
            lines.append(f"id: {event_id}")
        lines.append(f"data: {json.dumps(data)}\n")
    body = "\n".join(lines) + "\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def _streaming_client(*responses: httpx.Response) -> tuple[TextarooClient, list[httpx.Request]]:
    """A client whose Nth stream connection gets the Nth response."""
    seen: list[httpx.Request] = []
    pending = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return pending.pop(0)

    client = TextarooClient(api_key="test_key")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://test.com"
    )
    return client, seen


async def _collect(client: TextarooClient, **kwargs) -> tuple[list[str], TextarooError | None]:
    """Texts received until listen() raises (or ends)."""
    texts: list[str] = []
    try:
        async with contextlib.aclosing(client.listen(**kwargs)) as stream:
            async for message in stream:
                texts.append(message.text)
    except TextarooError as exc:
        return texts, exc
    return texts, None


@pytest.fixture
def sleep():
    with patch("aitextaroo.client._async_sleep", new_callable=AsyncMock) as mock:
        yield mock


class TestStreamStopsForGood:
    @pytest.mark.asyncio
    async def test_removed_key_stops_without_reconnecting(self, sleep) -> None:
        client, seen = _streaming_client(
            _sse(CONNECTED, _message("m1", "hi"), _error("credential_revoked"))
        )
        texts, error = await _collect(client)
        assert texts == ["hi"]  # texts before the removal still arrive
        assert error is not None
        assert error.code == "credential_revoked"
        assert error.message == (
            "This key was removed from your account; run aitextaroo-setup --save to add a new one."
        )
        assert len(seen) == 1
        sleep.assert_not_awaited()
        await client.close()

    @pytest.mark.asyncio
    async def test_evicted_stops_instead_of_fighting_the_other_stream(self, sleep) -> None:
        client, seen = _streaming_client(_sse(CONNECTED, _error("evicted")))
        texts, error = await _collect(client)
        assert texts == []
        assert error is not None
        assert error.code == "evicted"
        assert error.message == STREAM_STOPS["evicted"]
        assert len(seen) == 1
        sleep.assert_not_awaited()
        await client.close()

    @pytest.mark.asyncio
    async def test_stops_even_without_auto_reconnect(self, sleep) -> None:
        # Ending quietly would hide why no more texts come.
        client, _ = _streaming_client(_sse(CONNECTED, _error("credential_revoked")))
        _, error = await _collect(client, auto_reconnect=False)
        assert error is not None
        assert error.code == "credential_revoked"
        await client.close()

    @pytest.mark.asyncio
    async def test_401_is_fatal(self, sleep) -> None:
        client, seen = _streaming_client(
            httpx.Response(401, content=b'{"detail": {"error": {"code": "unauthorized"}}}')
        )
        _, error = await _collect(client)
        assert error is not None
        assert error.code == "unauthorized"
        assert error.status_code == 401
        assert len(seen) == 1
        sleep.assert_not_awaited()
        await client.close()


class TestStreamReconnects:
    @pytest.mark.asyncio
    async def test_reconnect_required_reconnects_with_last_event_id(self, sleep) -> None:
        client, seen = _streaming_client(
            _sse(CONNECTED, _message("m1", "first"), _error("reconnect_required")),
            _sse(CONNECTED, _message("m2", "second"), _error("credential_revoked")),
        )
        texts, error = await _collect(client)
        assert texts == ["first", "second"]
        assert error is not None
        assert error.code == "credential_revoked"
        assert len(seen) == 2
        assert seen[1].headers["Last-Event-ID"] == "m1"
        sleep.assert_awaited_once()
        await client.close()

    @pytest.mark.asyncio
    async def test_dropped_connection_reconnects(self, sleep) -> None:
        responses = iter(
            [
                httpx.ConnectError("connection refused"),
                _sse(CONNECTED, _message("m1", "back"), _error("evicted")),
            ]
        )
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            outcome = next(responses)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://test.com"
        )
        texts, error = await _collect(client)
        assert texts == ["back"]
        assert error is not None
        assert error.code == "evicted"
        assert len(seen) == 2
        sleep.assert_awaited_once()
        await client.close()
