"""Tests for the reply, relay, PIN, webhook and billing client methods."""

import json

import httpx
import pytest

from aitextaroo.client import TextarooClient, TextarooError, _parse_json_response


def _recording_client(status_code: int, body: str) -> tuple[TextarooClient, list[httpx.Request]]:
    """A client whose transport records each request and returns a fixed response."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, content=body.encode())

    client = TextarooClient(api_key="test_key")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://test.com"
    )
    return client, seen


MESSAGE = {
    "id": "m1",
    "text": "Yes, open the PR",
    "received_at": "2026-10-23T12:00:00Z",
    "channel": "sms",
    "trust_level": "low",
    "has_pin": True,
}


class TestTextContact:
    @pytest.mark.asyncio
    async def test_sends_to_and_name(self) -> None:
        client, seen = _recording_client(200, '{"message_id": "msg_1"}')
        assert await client.text_contact("+12125550100", "Happy birthday!", "Mom") == "msg_1"
        assert seen[0].url.path == "/v1/send"
        assert json.loads(seen[0].content) == {
            "text": "Happy birthday!",
            "to": "+12125550100",
            "recipient_name": "Mom",
        }
        await client.close()

    @pytest.mark.asyncio
    async def test_omits_empty_name(self) -> None:
        client, seen = _recording_client(200, '{"message_id": "msg_1"}')
        await client.text_contact("+12125550100", "Hi")
        assert "recipient_name" not in json.loads(seen[0].content)
        await client.close()

    @pytest.mark.asyncio
    async def test_free_tier_rejected(self) -> None:
        client, _ = _recording_client(
            403, '{"error": {"code": "tier_required", "message": "Relay needs Pro"}}'
        )
        with pytest.raises(TextarooError) as exc_info:
            await client.text_contact("+12125550100", "Hi")
        assert exc_info.value.code == "tier_required"
        await client.close()


class TestWaitForReply:
    @pytest.mark.asyncio
    async def test_returns_message(self) -> None:
        client, seen = _recording_client(200, json.dumps({"message": MESSAGE, "timed_out": False}))
        reply = await client.wait_for_reply(30)
        assert reply is not None
        assert reply.text == "Yes, open the PR"
        assert reply.has_pin is True
        assert json.loads(seen[0].content) == {"timeout_seconds": 30}
        await client.close()

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self) -> None:
        client, _ = _recording_client(200, '{"message": null, "timed_out": true}')
        assert await client.wait_for_reply() is None
        await client.close()

    @pytest.mark.asyncio
    async def test_clamps_timeout_and_extends_http_timeout(self) -> None:
        client, seen = _recording_client(200, '{"message": null, "timed_out": true}')
        await client.wait_for_reply(999)
        assert json.loads(seen[0].content) == {"timeout_seconds": 120}
        # The HTTP request must outlive the server-side wait.
        assert seen[0].extensions["timeout"]["read"] > 120
        await client.wait_for_reply(0)
        assert json.loads(seen[1].content) == {"timeout_seconds": 1}
        await client.close()


class TestRecentMessages:
    @pytest.mark.asyncio
    async def test_parses_and_passes_cursor(self) -> None:
        client, seen = _recording_client(
            200, json.dumps({"messages": [MESSAGE, "junk"], "retention_seconds": 300})
        )
        messages = await client.recent_messages(after_id="m0")
        assert [m.id for m in messages] == ["m1"]
        assert seen[0].url.params["after_id"] == "m0"
        await client.close()

    @pytest.mark.asyncio
    async def test_no_cursor_and_bad_shape(self) -> None:
        client, seen = _recording_client(200, '{"messages": "nope"}')
        assert await client.recent_messages() == []
        assert "after_id" not in seen[0].url.params
        await client.close()


class TestVerifyPin:
    @pytest.mark.asyncio
    async def test_verified(self) -> None:
        client, seen = _recording_client(200, '{"verified": true, "attempts_remaining": null}')
        assert (await client.verify_pin("4821"))["verified"] is True
        assert json.loads(seen[0].content) == {"pin": "4821"}
        await client.close()

    @pytest.mark.asyncio
    async def test_locked(self) -> None:
        client, _ = _recording_client(
            429, '{"error": {"code": "pin_locked", "message": "Too many tries"}}'
        )
        with pytest.raises(TextarooError) as exc_info:
            await client.verify_pin("0000")
        assert exc_info.value.code == "pin_locked"
        await client.close()


class TestWebhook:
    @pytest.mark.asyncio
    async def test_set_with_auth_header(self) -> None:
        body = json.dumps(
            {"status": "registered", "url": "https://hook.example", "secret": "whsec_x",
             "has_auth_header": True}
        )
        client, seen = _recording_client(200, body)
        result = await client.set_webhook("https://hook.example", auth_header="Bearer abc")
        assert result["has_auth_header"] is True
        assert json.loads(seen[0].content) == {
            "url": "https://hook.example",
            "auth_header": "Bearer abc",
        }
        await client.close()

    @pytest.mark.asyncio
    async def test_remove(self) -> None:
        client, seen = _recording_client(200, '{"status": "removed"}')
        assert (await client.remove_webhook())["status"] == "removed"
        assert seen[0].method == "DELETE"
        await client.close()


class TestUpgradeLink:
    @pytest.mark.asyncio
    async def test_returns_url(self) -> None:
        client, _ = _recording_client(200, '{"checkout_url": "https://checkout.stripe.com/x"}')
        assert await client.upgrade_link() == "https://checkout.stripe.com/x"
        await client.close()

    @pytest.mark.asyncio
    async def test_missing_url(self) -> None:
        client, _ = _recording_client(200, '{"status": "ok"}')
        with pytest.raises(TextarooError) as exc_info:
            await client.upgrade_link()
        assert exc_info.value.code == "invalid_response"
        await client.close()


def test_auth_error_inside_detail_envelope() -> None:
    """FastAPI auth failures wrap the error as {"detail": {"error": {...}}}."""
    response = httpx.Response(
        401,
        content=b'{"detail": {"error": {"code": "unauthorized", "message": "Invalid API key."}}}',
        request=httpx.Request("GET", "https://test.com/v1/account"),
    )
    with pytest.raises(TextarooError) as exc_info:
        _parse_json_response(response, "Account lookup failed")
    assert exc_info.value.code == "unauthorized"
    assert exc_info.value.message == "Invalid API key."
