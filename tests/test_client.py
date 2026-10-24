"""Tests for the TextarooClient — API methods and SSE parser."""

import json
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
        resp = self._make_response(400, '{"message": "something wrong"}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback msg")
        assert exc_info.value.code == "unknown"
        assert exc_info.value.message == "Fallback msg"

    def test_string_detail_is_the_message(self) -> None:
        """FastAPI HTTPException: {"detail": "..."}."""
        resp = self._make_response(409, '{"detail": "Already subscribed to Pro"}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "http_409"
        assert exc_info.value.message == "Already subscribed to Pro"
        assert exc_info.value.status_code == 409

    def test_422_validation_error_reports_first_problem(self) -> None:
        body = (
            '{"detail": ['
            '{"type": "missing", "loc": ["body", "phone"], "msg": "Field required", "input": {}},'
            '{"type": "missing", "loc": ["body", "code"], "msg": "Field required", "input": {}}'
            "]}"
        )
        resp = self._make_response(422, body)
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "validation_error"
        assert exc_info.value.message == "phone: Field required"
        assert exc_info.value.status_code == 422

    @pytest.mark.parametrize(
        ("loc", "message"),
        [
            ('["body", "contacts", 0, "to"]', "contacts.0.to: Bad number"),
            ('["query", "after_id"]', "after_id: Bad number"),
            ('["body"]', "Bad number"),
            ("null", "Bad number"),
        ],
    )
    def test_422_field_name_comes_from_loc(self, loc: str, message: str) -> None:
        resp = self._make_response(422, f'{{"detail": [{{"loc": {loc}, "msg": "Bad number"}}]}}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "validation_error"
        assert exc_info.value.message == message

    def test_422_without_msg_uses_fallback(self) -> None:
        resp = self._make_response(422, '{"detail": [{"loc": ["body", "phone"]}]}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "validation_error"
        assert exc_info.value.message == "Fallback"

    @pytest.mark.parametrize("detail", ['""', "[]", '["oops"]', "42", "null"])
    def test_unusable_detail_uses_fallback(self, detail: str) -> None:
        resp = self._make_response(400, f'{{"detail": {detail}}}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "unknown"
        assert exc_info.value.message == "Fallback"

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

    def test_400_with_error_as_list(self) -> None:
        """Malformed error envelope where 'error' is a list, not a dict."""
        resp = self._make_response(400, '{"error": []}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "unknown"
        assert exc_info.value.message == "Fallback"
        assert exc_info.value.status_code == 400

    def test_400_with_error_as_string(self) -> None:
        """Malformed error envelope where 'error' is a string."""
        resp = self._make_response(400, '{"error": "oops"}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "unknown"
        assert exc_info.value.message == "Fallback"

    def test_400_with_error_as_null(self) -> None:
        resp = self._make_response(400, '{"error": null}')
        with pytest.raises(TextarooError) as exc_info:
            _parse_json_response(resp, "Fallback")
        assert exc_info.value.code == "unknown"


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

    @staticmethod
    async def _confirm_recording(
        status_code: int, body: str, **kwargs
    ) -> tuple[dict, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(status_code, content=body.encode())

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                result = await TextarooClient.confirm_verification(
                    "+12125551234", "123456", **kwargs
                )
        return result, seen

    @pytest.mark.asyncio
    async def test_sends_the_label_and_returns_the_key_id(self) -> None:
        body = json.dumps(
            {"status": "verified", "api_key": "k" * 64, "key_id": "key_0f8c2b9e",
             "assigned_number": "+18005551234", "tier": "free"}
        )
        result, seen = await self._confirm_recording(200, body, label="Bridge on studio-mac")
        assert result["key_id"] == "key_0f8c2b9e"
        assert seen[0].url.path == "/v1/auth/confirm"
        assert json.loads(seen[0].content) == {
            "phone": "+12125551234",
            "code": "123456",
            "label": "Bridge on studio-mac",
        }

    @pytest.mark.parametrize("label", [None, ""])
    @pytest.mark.asyncio
    async def test_no_label_leaves_the_name_to_the_api(self, label) -> None:
        _, seen = await self._confirm_recording(200, '{"api_key": "k"}', label=label)
        assert "label" not in json.loads(seen[0].content)

    @pytest.mark.asyncio
    async def test_rejected_label_is_a_validation_error(self) -> None:
        body = '{"detail": [{"loc": ["body", "label"], "msg": "Value error, Use 1-40 characters"}]}'
        with pytest.raises(TextarooError) as exc_info:
            await self._confirm_recording(422, body, label="no/slashes")
        assert exc_info.value.code == "validation_error"
        assert exc_info.value.message.startswith("label: ")

    @pytest.mark.asyncio
    async def test_base_url_is_still_the_third_argument(self) -> None:
        # 0.2.x callers wrote confirm_verification(phone, code, base_url). The
        # phone and code must still go to that server (staging, say), not to
        # production.
        transport = _mock_transport(200, '{"api_key": "k"}')
        async with httpx.AsyncClient(transport=transport, base_url="https://test.com") as client:
            with patch("aitextaroo.client.httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                await TextarooClient.confirm_verification(
                    "+12125551234", "123456", "https://staging.example"
                )
        assert mock_cls.call_args.kwargs["base_url"] == "https://staging.example"

    @pytest.mark.asyncio
    async def test_label_goes_by_name_only(self) -> None:
        with pytest.raises(TypeError):
            await TextarooClient.confirm_verification(
                "+12125551234", "123456", "https://staging.example", "Bridge on studio-mac"
            )


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

    @pytest.mark.asyncio
    async def test_missing_message_id(self) -> None:
        """200 OK with no message_id field — server contract violation."""
        transport = _mock_transport(200, '{"status": "ok"}')
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        with pytest.raises(TextarooError) as exc_info:
            await client.send("Hello!")
        assert exc_info.value.code == "invalid_response"
        assert "message_id" in exc_info.value.message
        await client.close()

    @pytest.mark.asyncio
    async def test_empty_message_id(self) -> None:
        """200 OK with empty string message_id."""
        transport = _mock_transport(200, '{"message_id": ""}')
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        with pytest.raises(TextarooError) as exc_info:
            await client.send("Hello!")
        assert exc_info.value.code == "invalid_response"
        await client.close()

    @pytest.mark.asyncio
    async def test_non_string_message_id(self) -> None:
        """200 OK with numeric message_id instead of string."""
        transport = _mock_transport(200, '{"message_id": 12345}')
        client = TextarooClient(api_key="test_key")
        client._client = httpx.AsyncClient(transport=transport, base_url="https://test.com")
        with pytest.raises(TextarooError) as exc_info:
            await client.send("Hello!")
        assert exc_info.value.code == "invalid_response"
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
