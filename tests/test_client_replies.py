"""Tests for the reply, relay, PIN, webhook, connection and billing client methods."""

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


DUPLICATE = '{"status": "sent", "message_id": null, "duplicate": true}'


class TestSendingOnce:
    """An idempotency_key goes out as the Idempotency-Key header; a duplicate answers None."""

    @pytest.mark.asyncio
    async def test_the_key_is_sent_as_a_header(self) -> None:
        client, seen = _recording_client(200, '{"status": "sent", "message_id": "msg_1"}')
        assert await client.send("Dinner at 7", idempotency_key="text-1") == "msg_1"
        assert await client.text_contact("+12125550100", "Hi", idempotency_key="text-2") == "msg_1"
        assert [r.headers.get("Idempotency-Key") for r in seen] == ["text-1", "text-2"]
        await client.close()

    @pytest.mark.asyncio
    async def test_no_key_no_header(self) -> None:
        client, seen = _recording_client(200, '{"status": "sent", "message_id": "msg_1"}')
        await client.send("Dinner at 7")
        assert "Idempotency-Key" not in seen[0].headers
        await client.close()

    @pytest.mark.asyncio
    async def test_a_duplicate_answers_none(self) -> None:
        client, _ = _recording_client(200, DUPLICATE)
        assert await client.send("Dinner at 7", idempotency_key="text-1") is None
        await client.close()

    @pytest.mark.asyncio
    async def test_a_duplicate_answer_to_a_request_without_a_key_is_invalid(self) -> None:
        client, _ = _recording_client(200, DUPLICATE)
        with pytest.raises(TextarooError) as exc_info:
            await client.send("Dinner at 7")
        assert exc_info.value.code == "invalid_response"
        await client.close()

    @pytest.mark.asyncio
    async def test_it_learns_whether_the_api_honours_keys(self) -> None:
        honoured = '{"status": "sent", "message_id": "m", "duplicate": false}'
        new_api, _ = _recording_client(200, honoured)
        old_api, _ = _recording_client(200, '{"status": "sent", "message_id": "m"}')
        assert new_api.idempotency_supported is None
        await new_api.send("Hi")  # no key: nothing learned
        assert new_api.idempotency_supported is None
        await new_api.send("Hi", idempotency_key="k1")
        await old_api.send("Hi", idempotency_key="k1")
        assert (new_api.idempotency_supported, old_api.idempotency_supported) == (True, False)
        await new_api.close()
        await old_api.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["", "has space", "x" * 65, "dot.ted"])
    async def test_a_malformed_key_is_refused_before_sending(self, key: str) -> None:
        client, seen = _recording_client(200, DUPLICATE)
        with pytest.raises(ValueError, match="idempotency_key"):
            await client.send("Hi", idempotency_key=key)
        assert seen == []
        await client.close()

    @pytest.mark.asyncio
    async def test_send_in_doubt(self) -> None:
        client, _ = _recording_client(
            409, '{"error": {"code": "send_in_doubt", "message": "It may have gone out already."}}'
        )
        with pytest.raises(TextarooError) as exc_info:
            await client.send("Dinner at 7", idempotency_key="text-1")
        assert (exc_info.value.code, exc_info.value.status_code) == ("send_in_doubt", 409)
        await client.close()


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

    @pytest.mark.asyncio
    async def test_set_pin(self) -> None:
        client, seen = _recording_client(200, '{"status": "pin_set"}')
        assert await client.set_pin("4821") == {"status": "pin_set"}
        assert (seen[0].method, seen[0].url.path) == ("POST", "/v1/account/pin")
        assert json.loads(seen[0].content) == {"pin": "4821"}
        await client.close()

    @pytest.mark.asyncio
    async def test_change_pin_sends_the_current_one(self) -> None:
        client, seen = _recording_client(200, '{"status": "pin_changed"}')
        assert await client.set_pin("4821", current_pin="1111") == {"status": "pin_changed"}
        assert json.loads(seen[0].content) == {"pin": "4821", "current_pin": "1111"}
        await client.close()

    @pytest.mark.asyncio
    async def test_remove_pin(self) -> None:
        client, seen = _recording_client(200, '{"status": "pin_removed"}')
        assert await client.remove_pin("1111") == {"status": "pin_removed"}
        assert (seen[0].method, seen[0].url.path) == ("DELETE", "/v1/account/pin")
        assert json.loads(seen[0].content) == {"current_pin": "1111"}
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
    async def test_set_with_pin(self) -> None:
        client, seen = _recording_client(200, '{"status": "registered", "owner_notified": true}')
        await client.set_webhook("https://hook.example", pin="4821")
        assert json.loads(seen[0].content) == {"url": "https://hook.example", "pin": "4821"}
        await client.close()

    @pytest.mark.asyncio
    async def test_pin_required_is_an_error(self) -> None:
        client, _ = _recording_client(
            403, '{"error": {"code": "pin_required", "message": "This account has a security PIN"}}'
        )
        with pytest.raises(TextarooError) as exc_info:
            await client.set_webhook("https://hook.example")
        assert exc_info.value.code == "pin_required"
        await client.close()

    @pytest.mark.asyncio
    async def test_remove(self) -> None:
        client, seen = _recording_client(200, '{"status": "removed"}')
        assert (await client.remove_webhook())["status"] == "removed"
        assert seen[0].method == "DELETE"
        await client.close()


KEY_ID = "key_0f8c2b9e-3a41-4d6b-9c1e-7a5d2f4b8e10"
CONNECTIONS = {
    "keys": [
        {"id": KEY_ID, "kind": "key", "label": "aitextaroo on studio-mac", "hint": "...3f9a",
         "created_at": "2026-10-24T12:00:00Z", "last_used_at": None, "current": True,
         "forwarding": False},
    ],
    "apps": [
        {"id": "app_Fam1ly_1d-xyz", "kind": "app", "label": "Grok", "verified": True,
         "created_at": "2026-10-20T09:00:00Z", "last_used_at": "2026-10-24T11:00:00Z",
         "current": False, "forwarding": True},
    ],
    "forwarding": {"host": "api.x.ai", "set_by": "app_Fam1ly_1d-xyz",
                   "set_at": "2026-10-20T09:05:00Z"},
    "max_keys": 10,
}
REMOVED = {
    "status": "removed",
    "removed": {"id": "app_Fam1ly_1d-xyz", "kind": "app", "label": "Grok"},
    "forwarding_stopped": "api.x.ai",
    "owner_notified": True,
    "was_current": False,
}


class TestConnections:
    @pytest.mark.asyncio
    async def test_list(self) -> None:
        client, seen = _recording_client(200, json.dumps(CONNECTIONS))
        assert await client.list_connections() == CONNECTIONS
        assert (seen[0].method, seen[0].url.path) == ("GET", "/v1/account/connections")
        await client.close()

    @pytest.mark.asyncio
    async def test_remove_without_a_pin_sends_no_body(self) -> None:
        client, seen = _recording_client(200, json.dumps(REMOVED))
        assert await client.remove_connection("app_Fam1ly_1d-xyz") == REMOVED
        assert seen[0].method == "DELETE"
        assert seen[0].url.path == "/v1/account/connections/app_Fam1ly_1d-xyz"
        assert seen[0].content == b""
        await client.close()

    @pytest.mark.asyncio
    async def test_remove_with_a_pin(self) -> None:
        client, seen = _recording_client(200, json.dumps({**REMOVED, "was_current": True}))
        result = await client.remove_connection(KEY_ID, pin="4821")
        assert result["was_current"] is True
        assert seen[0].url.path == f"/v1/account/connections/{KEY_ID}"
        assert json.loads(seen[0].content) == {"pin": "4821"}
        await client.close()

    @pytest.mark.parametrize(
        ("status", "code"),
        [
            (403, "pin_required"),
            (403, "pin_incorrect"),
            (404, "connection_not_found"),
            (429, "rate_limit_exceeded"),
            (429, "pin_locked"),
            (503, "temporarily_unavailable"),
        ],
    )
    @pytest.mark.asyncio
    async def test_remove_errors(self, status: int, code: str) -> None:
        client, _ = _recording_client(
            status, json.dumps({"error": {"code": code, "message": "Nope"}})
        )
        with pytest.raises(TextarooError) as exc_info:
            await client.remove_connection(KEY_ID, pin="0000")
        assert (exc_info.value.code, exc_info.value.status_code) == (code, status)
        assert exc_info.value.message == "Nope"
        await client.close()

    @pytest.mark.parametrize(
        "connection_id",
        [
            "../../webhook",  # would collapse into DELETE /v1/webhook
            "..",
            "key_../../account/pin",
            "app_%2e%2e",
            "key_abc/def",
            "key_abc?x=1",
            "key_abc\n",
            "KEY_abc",
            "webhook",
            "key_",
            "",
        ],
    )
    @pytest.mark.asyncio
    async def test_anything_but_a_connection_id_never_reaches_the_api(
        self, connection_id: str
    ) -> None:
        client, seen = _recording_client(200, json.dumps(REMOVED))
        with pytest.raises(TextarooError) as exc_info:
            await client.remove_connection(connection_id)
        assert exc_info.value.code == "connection_not_found"
        assert seen == []
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
