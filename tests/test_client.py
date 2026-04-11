"""Tests for the TextarooClient — API methods and SSE parser."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aitextaroo.client import (
    TextarooClient,
    TextarooError,
    _parse_event,
    _parse_json_response,
)
from aitextaroo.models import EventType


# ── _parse_json_response (the core fix) ─────────────────────────


class TestParseJsonResponse:
    """Tests for the response parser that all API methods depend on."""

    def _make_response(self, status_code: int, body: str, content_type: str = "application/json") -> httpx.Response:
        """Build a fake httpx.Response."""
        return httpx.Response(
            status_code=status_code,
            content=body.encode() if body else b"",
            headers={"content-type": content_type},
            request=httpx.Request("POST", "https://example.com/test"),
        )

    def test_200_with_valid_json(self) -> None:
        resp = self._make_response(200, '{"status": "ok"}')
        assert _parse_json_response(resp, "fail") == {"status": "ok"}

    def test_400_with_error_envelope(self) -> None:
        resp = self._make_response(400, '{"error": {"code": "bad_input", "message": "Invalid phone"}}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "fail")
        assert exc_info.value.code == "bad_input"
        assert exc_info.value.message == "Invalid phone"
        assert exc_info.value.status_code == 400

    def test_400_with_empty_body(self) -> None:
        resp = self._make_response(400, "")
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Request failed")
        assert exc_info.value.code == "http_error"
        assert "HTTP 400" in exc_info.value.message
        assert exc_info.value.status_code == 400

    def test_500_with_empty_body(self) -> None:
        resp = self._make_response(500, "")
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Server error")
        assert exc_info.value.code == "http_error"
        assert exc_info.value.status_code == 500

    def test_502_with_html_body(self) -> None:
        resp = self._make_response(502, "<html>Bad Gateway</html>", "text/html")
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Gateway error")
        assert exc_info.value.code == "http_error"
        assert exc_info.value.status_code == 502

    def test_200_with_empty_body(self) -> None:
        resp = self._make_response(200, "")
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Unexpected empty")
        assert exc_info.value.code == "invalid_response"

    def test_200_with_html_body(self) -> None:
        resp = self._make_response(200, "<html>not json</html>")
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Bad response")
        assert exc_info.value.code == "invalid_response"

    def test_400_without_error_key(self) -> None:
        resp = self._make_response(400, '{"detail": "something wrong"}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback msg")
        assert exc_info.value.code == "unknown"
        assert exc_info.value.message == "Fallback msg"

    def test_429_rate_limited(self) -> None:
        resp = self._make_response(429, '{"error": {"code": "rate_limited", "message": "Too many requests"}}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "fail")
        assert exc_info.value.code == "rate_limited"
        assert exc_info.value.status_code == 429

    def test_401_unauthorized(self) -> None:
        resp = self._make_response(401, '{"error": {"code": "unauthorized", "message": "Bad key"}}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "fail")
        assert exc_info.value.code == "unauthorized"
        assert exc_info.value.status_code == 401

    def test_200_with_json_array(self) -> None:
        resp = self._make_response(200, "[]")
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Expected object")
        assert exc_info.value.code == "invalid_response"

    def test_200_with_json_null(self) -> None:
        resp = self._make_response(200, "null")
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Expected object")
        assert exc_info.value.code == "invalid_response"


# ── TextarooClient API methods ──────────────────────────────────


def _mock_transport(status_code: int, body: str) -> httpx.MockTransport:
    """Create a mock transport that returns a fixed response."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body.encode())
    return httpx.MockTransport(handler)


class TestRequestVerification:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        transport = _mock_transport(200, '{"status": "code_sent", "expires_in": 300}')
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                result = await TextarooClient.request_verification("+12125551234")
        assert result["status"] == "code_sent"
        assert result["expires_in"] == 300

    @pytest.mark.asyncio
    async def test_rate_limited(self) -> None:
        transport = _mock_transport(429, '{"error": {"code": "rate_limited", "message": "Wait 60s"}}')
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                with pytest.raises(TextarooError) as exc_info:
                    await TextarooClient.request_verification("+12125551234")
        assert exc_info.value.code == "rate_limited"

    @pytest.mark.asyncio
    async def test_empty_500(self) -> None:
        transport = _mock_transport(500, "")
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                with pytest.raises(TextarooError) as exc_info:
                    await TextarooClient.request_verification("+12125551234")
        assert exc_info.value.status_code == 500


class TestConfirmVerification:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        body = '{"status": "verified", "api_key": "test_key_123", "assigned_number": "+18005551234", "tier": "free"}'
        transport = _mock_transport(200, body)
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                result = await TextarooClient.confirm_verification("+12125551234", "123456")
        assert result["api_key"] == "test_key_123"
        assert result["assigned_number"] == "+18005551234"

    @pytest.mark.asyncio
    async def test_expired_code(self) -> None:
        body = '{"error": {"code": "code_expired", "message": "No valid verification code found."}}'
        transport = _mock_transport(400, body)
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                with pytest.raises(TextarooError) as exc_info:
                    await TextarooClient.confirm_verification("+12125551234", "999999")
        assert exc_info.value.code == "code_expired"

    @pytest.mark.asyncio
    async def test_empty_response_body(self) -> None:
        """The actual bug that triggered this fix — API returning empty body."""
        transport = _mock_transport(500, "")
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                with pytest.raises(TextarooError) as exc_info:
                    await TextarooClient.confirm_verification("+12125551234", "123456")
        assert exc_info.value.code == "http_error"
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_html_error_page(self) -> None:
        transport = _mock_transport(502, "<html>Bad Gateway</html>")
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                with pytest.raises(TextarooError) as exc_info:
                    await TextarooClient.confirm_verification("+12125551234", "123456")
        assert exc_info.value.status_code == 502


class TestSend:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        transport = _mock_transport(200, '{"message_id": "msg_abc123"}')
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        result = await client.send("Hello!")
        assert result == "msg_abc123"
        await client.close()

    @pytest.mark.asyncio
    async def test_daily_limit(self) -> None:
        transport = _mock_transport(429, '{"error": {"code": "daily_limit_reached", "message": "Limit reached"}}')
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        with pytest.raises(TextarooError) as exc_info:
            await client.send("Hello!")
        assert exc_info.value.code == "daily_limit_reached"
        await client.close()

    @pytest.mark.asyncio
    async def test_empty_500(self) -> None:
        transport = _mock_transport(500, "")
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        with pytest.raises(TextarooError) as exc_info:
            await client.send("Hello!")
        assert exc_info.value.status_code == 500
        await client.close()


class TestAccount:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        body = '{"tier": "free", "assigned_number": "+18005551234", "usage": {"today": 3}}'
        transport = _mock_transport(200, body)
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        result = await client.account()
        assert result["tier"] == "free"
        assert result["assigned_number"] == "+18005551234"
        await client.close()

    @pytest.mark.asyncio
    async def test_unauthorized(self) -> None:
        transport = _mock_transport(401, '{"error": {"code": "unauthorized", "message": "Bad key"}}')
        client = TextarooClient(api_key="bad_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        with pytest.raises(TextarooError) as exc_info:
            await client.account()
        assert exc_info.value.code == "unauthorized"
        await client.close()

    @pytest.mark.asyncio
    async def test_empty_500(self) -> None:
        transport = _mock_transport(500, "")
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        with pytest.raises(TextarooError) as exc_info:
            await client.account()
        assert exc_info.value.status_code == 500
        await client.close()


# ── TextarooClient constructor ──────────────────────────────────


class TestClientInit:
    def test_requires_api_key(self) -> None:
        with pytest.raises(ValueError, match="api_key is required"):
            TextarooClient(api_key="")

    def test_strips_trailing_slash(self) -> None:
        client = TextarooClient(api_key="test", base_url="https://example.com/")
        assert client._base_url == "https://example.com"


# ── SSE event parser (existing tests) ───────────────────────────


class TestParseEvent:
    def test_parse_connected(self) -> None:
        event = _parse_event(
            "connected",
            None,
            ['{"user_id": "u1", "assigned_number": "+1234", "server_time": "now"}'],
        )
        assert event is not None
        assert event.type == EventType.CONNECTED
        assert event.connected is not None
        assert event.connected.user_id == "u1"

    def test_parse_message(self) -> None:
        event = _parse_event(
            "message",
            "msg-123",
            ['{"id": "msg-123", "text": "hello", "received_at": "now", "has_pin": true}'],
        )
        assert event is not None
        assert event.type == EventType.MESSAGE
        assert event.message is not None
        assert event.message.text == "hello"
        assert event.message.has_pin is True

    def test_parse_error(self) -> None:
        event = _parse_event(
            "error",
            None,
            ['{"code": "evicted", "message": "kicked", "retry_after": 30}'],
        )
        assert event is not None
        assert event.type == EventType.ERROR
        assert event.error is not None
        assert event.error.code == "evicted"
        assert event.error.retry_after == 30

    def test_parse_unknown_type(self) -> None:
        event = _parse_event("unknown_type", None, ['{"foo": "bar"}'])
        assert event is None

    def test_parse_empty_data(self) -> None:
        event = _parse_event("message", None, [])
        assert event is None

    def test_parse_invalid_json(self) -> None:
        event = _parse_event("message", None, ["not json"])
        assert event is None

    def test_parse_message_defaults(self) -> None:
        event = _parse_event("message", None, ['{"id": "1", "text": "hi", "received_at": "now"}'])
        assert event is not None
        assert event.message is not None
        assert event.message.channel == "sms"
        assert event.message.trust_level == "low"
        assert event.message.has_pin is False
