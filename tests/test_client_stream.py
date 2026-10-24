"""Tests for listen(): when the SSE stream reconnects and when it stops for good."""

import contextlib
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aitextaroo.client import (
    DEFAULT_RECONNECT_DELAY,
    STREAM_READ_TIMEOUT,
    STREAM_STOPS,
    TextarooClient,
    TextarooError,
)

CONNECTED = ("connected", None, {"user_id": "u1", "assigned_number": "+15551110000"})
SSE_HEADERS = {"content-type": "text/event-stream"}


def _message(msg_id: str, text: str) -> tuple[str, str, dict]:
    return ("message", msg_id, {"id": msg_id, "text": text, "received_at": "now"})


def _error(code: str, message: str = "server says") -> tuple[str, None, dict]:
    return ("error", None, {"code": code, "message": message})


def _sse_body(*events: tuple[str, str | None, dict]) -> bytes:
    lines = []
    for name, event_id, data in events:
        lines.append(f"event: {name}")
        if event_id:
            lines.append(f"id: {event_id}")
        lines.append(f"data: {json.dumps(data)}\n")
    return ("\n".join(lines) + "\n").encode()


def _sse(*events: tuple[str, str | None, dict]) -> httpx.Response:
    """One stream connection's worth of SSE events, then the server hangs up."""
    return httpx.Response(200, content=_sse_body(*events), headers=SSE_HEADERS)


class _GoesSilent(httpx.AsyncByteStream):
    """A stream connection that sends these bytes, then nothing until the read times out."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self):
        yield self._body
        raise httpx.ReadTimeout("nothing for too long")


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
        assert error.message == STREAM_STOPS["credential_revoked"]
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
    async def test_server_restarting_waits_retry_after_then_reconnects(self, sleep) -> None:
        # A deploy: every stream gets this, and must come back on its own.
        restarting = (
            "error",
            None,
            {"code": "server_restarting", "message": "Restarting.", "retry_after": 7},
        )
        client, seen = _streaming_client(
            _sse(CONNECTED, _message("m1", "before"), restarting),
            _sse(CONNECTED, _message("m2", "after"), _error("credential_revoked")),
        )
        texts, error = await _collect(client)
        assert texts == ["before", "after"]
        assert error is not None
        assert error.code == "credential_revoked"
        assert len(seen) == 2
        assert seen[1].headers["Last-Event-ID"] == "m1"
        sleep.assert_awaited_once_with(7.0)
        await client.close()

    @pytest.mark.asyncio
    async def test_unknown_codes_reconnect(self, sleep) -> None:
        # Only the codes in STREAM_STOPS stop for good, so a code added to the
        # API later never strands a bridge.
        client, seen = _streaming_client(
            _sse(CONNECTED, _error("some_new_code")),
            _sse(CONNECTED, _message("m1", "still here"), _error("evicted")),
        )
        texts, error = await _collect(client)
        assert texts == ["still here"]
        assert error is not None
        assert error.code == "evicted"
        assert len(seen) == 2
        sleep.assert_awaited_once_with(DEFAULT_RECONNECT_DELAY)
        await client.close()

    @pytest.mark.asyncio
    async def test_a_stream_that_goes_silent_reconnects(self, sleep) -> None:
        # After sleep/wake or a dropped NAT mapping no error ever arrives, and
        # the API's keepalives (at least every 20 s) just stop: only the read
        # timeout notices, and then listen() reconnects.
        silent = httpx.Response(
            200,
            stream=_GoesSilent(_sse_body(CONNECTED, _message("m1", "before"))),
            headers=SSE_HEADERS,
        )
        client, seen = _streaming_client(
            silent, _sse(CONNECTED, _message("m2", "after"), _error("credential_revoked"))
        )
        texts, error = await _collect(client)
        assert texts == ["before", "after"]
        assert error is not None
        assert error.code == "credential_revoked"
        assert len(seen) == 2
        assert seen[0].extensions["timeout"]["read"] == STREAM_READ_TIMEOUT == 90.0
        assert seen[1].headers["Last-Event-ID"] == "m1"
        sleep.assert_awaited_once()
        await client.close()

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ConnectError("connection refused"),
            httpx.ConnectTimeout("no answer"),
            httpx.ReadTimeout("nothing for too long"),
            httpx.RemoteProtocolError("peer closed connection"),
        ],
        ids=lambda exc: type(exc).__name__,
    )
    @pytest.mark.asyncio
    async def test_dropped_connection_reconnects(self, sleep, failure) -> None:
        responses = iter([failure, _sse(CONNECTED, _message("m1", "back"), _error("evicted"))])
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
