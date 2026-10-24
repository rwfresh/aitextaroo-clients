"""Core client for the AI Text-a-roo SMS gateway.

Provides:
1. listen()          — SSE stream for real-time inbound SMS delivery
2. send()            — POST outbound SMS to the user's phone
3. wait_for_reply()  — ask a question, then wait for the user's answer
4. text_contact()    — text someone else on the user's behalf (Pro)
5. PIN checks, recent messages, webhooks and the Pro upgrade link

The SSE client handles reconnection, Last-Event-ID replay,
and keepalive parsing automatically. No public IP or webhook
configuration is needed — it's a single outbound HTTPS connection.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from aitextaroo.models import (
    ConnectedEvent,
    ErrorEvent,
    EventType,
    InboundMessage,
    StreamEvent,
)

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_BASE_URL = "https://api.aitextaroo.com"
DEFAULT_RECONNECT_DELAY = 3.0
MAX_RECONNECT_DELAY = 60.0
RECONNECT_BACKOFF_FACTOR = 2.0

# Server-side bounds for POST /v1/messages/wait.
MIN_WAIT_SECONDS = 1
MAX_WAIT_SECONDS = 120
# Extra HTTP time on top of the wait so the server answers before we give up.
WAIT_HTTP_MARGIN = 15.0


class TextarooError(Exception):
    """Raised when an API call fails."""

    def __init__(self, code: str, message: str, status_code: int = 0):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


def _parse_json_response(response: httpx.Response, fallback_message: str) -> dict:
    """Parse a JSON API response, raising TextarooError on failure.

    Handles three failure modes that response.json() alone does not:
    1. Empty response body (e.g., 502 from a gateway/proxy)
    2. Non-JSON response body (e.g., HTML error page)
    3. API error envelope ({"error": {"code": ..., "message": ...}})

    Args:
        response: The httpx Response object.
        fallback_message: Human-readable message if the response has
            no parseable error details.

    Returns:
        Parsed JSON dict on 200 OK.

    Raises:
        TextarooError: On any non-200 status or unparseable body.
    """
    # Try to parse JSON — but don't crash on empty/invalid body
    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise TextarooError(
            code="http_error" if response.status_code != 200 else "invalid_response",
            message=f"{fallback_message} (HTTP {response.status_code})",
            status_code=response.status_code,
        ) from exc

    # Non-200 with valid JSON — extract the API error envelope. Service
    # errors use {"error": {...}}; auth failures wrap it as {"detail": {"error": {...}}}.
    if response.status_code != 200:
        error = data.get("error") if isinstance(data, dict) else None
        detail = data.get("detail") if isinstance(data, dict) else None
        if not isinstance(error, dict) and isinstance(detail, dict):
            error = detail.get("error")
        if not isinstance(error, dict):
            error = {}
        raise TextarooError(
            code=error.get("code", "unknown"),
            message=error.get("message", fallback_message),
            status_code=response.status_code,
        )

    if not isinstance(data, dict):
        raise TextarooError(
            code="invalid_response",
            message=f"{fallback_message}: expected JSON object (HTTP {response.status_code})",
            status_code=response.status_code,
        )

    return data


class TextarooClient:
    """Client for the AI Text-a-roo SMS gateway.

    Args:
        api_key: Your AI Text-a-roo API key.
        base_url: API base URL. Defaults to https://api.aitextaroo.com.
        timeout: HTTP timeout in seconds for non-streaming requests.

    Example:
        >>> client = TextarooClient(api_key="YOUR_KEY")
        >>> async for message in client.listen():
        ...     print(message.text)
        ...     await client.send("Got it!")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None
        self._last_event_id: str | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Signup / verification (no API key needed) ─────────────

    @staticmethod
    async def request_verification(
        phone: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> dict[str, Any]:
        """Request a phone verification code (step 1 of signup).

        This is a static method — no API key needed. Call this before
        creating a TextarooClient.

        Args:
            phone: Phone number in E.164 format (e.g., "+12125551234").
            base_url: API base URL.

        Returns:
            {"status": "code_sent", "expires_in": 300}

        Raises:
            TextarooError: If the request fails (rate limited, invalid phone).
        """
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/auth/verify",
                json={"phone": phone},
            )
            return _parse_json_response(response, "Verification request failed")

    @staticmethod
    async def confirm_verification(
        phone: str,
        code: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> dict[str, Any]:
        """Confirm verification code and receive API key (step 2 of signup).

        This is a static method — no API key needed. The returned dict
        contains the api_key needed to create a TextarooClient.

        Args:
            phone: Same phone number used in request_verification.
            code: The 6-digit code received via SMS.
            base_url: API base URL.

        Returns:
            {"status": "verified", "api_key": "...", "assigned_number": "+1...",
             "tier": "free", "note": "..."}

        Raises:
            TextarooError: If the code is invalid or expired.
        """
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/auth/confirm",
                json={"phone": phone, "code": code},
            )
            return _parse_json_response(response, "Verification failed")

    # ── Outbound messaging ──────────────────────────────────────

    async def send(self, text: str) -> str:
        """Send an SMS to the registered user.

        Args:
            text: Message body (max 1600 characters).

        Returns:
            The carrier message ID.

        Raises:
            TextarooError: If the API returns an error.
        """
        return await self._post_send({"text": text})

    async def text_contact(self, to: str, text: str, recipient_name: str | None = None) -> str:
        """Text someone else on the user's behalf (Pro plan).

        The contact sees the AI's number. Their replies are forwarded to
        the user's phone, labeled with recipient_name when given.

        Args:
            to: The contact's number in E.164 format (e.g., "+12125550100").
            text: Message body (max 1600 characters).
            recipient_name: Optional name used to label forwarded replies.

        Returns:
            The carrier message ID.

        Raises:
            TextarooError: If the API returns an error ("tier_required" on Free).
        """
        body: dict[str, Any] = {"text": text, "to": to}
        if recipient_name:
            body["recipient_name"] = recipient_name
        return await self._post_send(body)

    async def _post_send(self, body: dict[str, Any]) -> str:
        client = await self._get_client()
        response = await client.post("/v1/send", json=body)
        data = _parse_json_response(response, "Send failed")
        message_id = data.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise TextarooError(
                code="invalid_response",
                message="Missing or invalid message_id in send response",
                status_code=response.status_code,
            )
        return message_id

    # ── Replies ─────────────────────────────────────────────────

    async def wait_for_reply(self, timeout_seconds: int = 60) -> InboundMessage | None:
        """Wait for the user's next text (or one that arrived since your last send).

        Use it after asking a question: send(...), then wait_for_reply().
        A pending wait gets the user's next text before the SSE stream or
        a webhook does, so the same reply is never handled twice.

        Args:
            timeout_seconds: How long the server waits, 1–120 seconds.

        Returns:
            The reply, or None if the user didn't answer in time.

        Raises:
            TextarooError: If the API returns an error.
        """
        timeout = max(MIN_WAIT_SECONDS, min(MAX_WAIT_SECONDS, int(timeout_seconds)))
        client = await self._get_client()
        response = await client.post(
            "/v1/messages/wait",
            json={"timeout_seconds": timeout},
            timeout=timeout + WAIT_HTTP_MARGIN,
        )
        data = _parse_json_response(response, "Wait for reply failed")
        message = data.get("message")
        return _message_from_dict(message) if isinstance(message, dict) else None

    async def recent_messages(self, after_id: str | None = None) -> list[InboundMessage]:
        """Texts the user sent in the last five minutes, oldest first.

        Args:
            after_id: Only return texts after this message id (a cursor).

        Returns:
            The messages still held in memory by the gateway.

        Raises:
            TextarooError: If the API returns an error.
        """
        client = await self._get_client()
        params = {"after_id": after_id} if after_id else None
        response = await client.get("/v1/messages/recent", params=params)
        data = _parse_json_response(response, "Recent messages lookup failed")
        messages = data.get("messages")
        if not isinstance(messages, list):
            return []
        return [_message_from_dict(m) for m in messages if isinstance(m, dict)]

    # ── Security PIN ────────────────────────────────────────────

    async def verify_pin(self, pin: str) -> dict[str, Any]:
        """Check a PIN the user texted against their security PIN.

        Ask for the PIN before anything sensitive (purchases, messages to
        other people, deletions). Don't store or repeat it.

        Returns:
            {"verified": bool, "attempts_remaining": int | None}

        Raises:
            TextarooError: "pin_not_set", or "pin_locked" after 3 wrong tries
                in 5 minutes.
        """
        client = await self._get_client()
        response = await client.post("/v1/verify-pin", json={"pin": pin})
        return _parse_json_response(response, "PIN verification failed")

    # ── Webhooks ────────────────────────────────────────────────

    async def set_webhook(self, url: str, auth_header: str | None = None) -> dict[str, Any]:
        """Forward each text the user sends to a URL as a signed JSON POST.

        Args:
            url: Public https URL that receives the deliveries.
            auth_header: Optional Authorization header value sent with each
                delivery (e.g., "Bearer <token>" for a Grok Bot webhook routine).

        Returns:
            {"status": "registered", "url": ..., "secret": ..., "has_auth_header": bool}.
            Verify deliveries with the secret: X-Signature is a hex
            HMAC-SHA256 of the raw body.

        Raises:
            TextarooError: If the API returns an error.
        """
        body: dict[str, Any] = {"url": url}
        if auth_header:
            body["auth_header"] = auth_header
        client = await self._get_client()
        response = await client.post("/v1/webhook", json=body)
        return _parse_json_response(response, "Webhook registration failed")

    async def remove_webhook(self) -> dict[str, Any]:
        """Stop webhook delivery."""
        client = await self._get_client()
        response = await client.delete("/v1/webhook")
        return _parse_json_response(response, "Webhook removal failed")

    # ── Billing ─────────────────────────────────────────────────

    async def upgrade_link(self) -> str:
        """A Stripe checkout link the user can open to start Pro.

        Raises:
            TextarooError: If the API returns an error (e.g. already on Pro).
        """
        client = await self._get_client()
        response = await client.post("/v1/billing/checkout")
        data = _parse_json_response(response, "Upgrade link failed")
        url = data.get("checkout_url")
        if not isinstance(url, str) or not url:
            raise TextarooError(
                code="invalid_response",
                message="Missing checkout_url in billing response",
                status_code=response.status_code,
            )
        return url

    # ── Account info ────────────────────────────────────────────

    async def account(self) -> dict[str, Any]:
        """Get account info (tier, assigned number, usage).

        Returns:
            Account details as a dictionary.

        Raises:
            TextarooError: If the API returns an error.
        """
        client = await self._get_client()
        response = await client.get("/v1/account")
        return _parse_json_response(response, "Account lookup failed")

    # ── SSE stream ──────────────────────────────────────────────

    async def listen(self, *, auto_reconnect: bool = True) -> AsyncIterator[InboundMessage]:
        """Listen for inbound SMS messages via the SSE stream.

        Yields InboundMessage objects as they arrive. Handles
        reconnection and Last-Event-ID replay automatically.

        Args:
            auto_reconnect: If True (default), reconnects on disconnect
                with exponential backoff and Last-Event-ID replay.

        Yields:
            InboundMessage for each received SMS.

        Example:
            >>> async for msg in client.listen():
            ...     print(f"From user: {msg.text}")
            ...     await client.send(f"Echo: {msg.text}")
        """
        delay = DEFAULT_RECONNECT_DELAY

        while True:
            try:
                async for event in self._stream_events():
                    if event.type == EventType.CONNECTED:
                        logger.info("Stream connected: %s", event.connected)
                        delay = DEFAULT_RECONNECT_DELAY  # Reset backoff

                    elif event.type == EventType.MESSAGE and event.message:
                        yield event.message

                    elif event.type == EventType.ERROR and event.error:
                        logger.warning("Stream error: %s", event.error)
                        if event.error.retry_after:
                            delay = float(event.error.retry_after)

            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as exc:
                logger.warning("Stream disconnected: %s", type(exc).__name__)

            except httpx.HTTPStatusError as exc:
                logger.error("Stream HTTP error: %d", exc.response.status_code)
                if exc.response.status_code == 401:
                    raise TextarooError(
                        code="unauthorized",
                        message="Invalid API key",
                        status_code=401,
                    ) from exc

            if not auto_reconnect:
                return

            logger.info("Reconnecting in %.1fs (Last-Event-ID: %s)", delay, self._last_event_id)
            await _async_sleep(delay)
            delay = min(delay * RECONNECT_BACKOFF_FACTOR, MAX_RECONNECT_DELAY)

    async def _stream_events(self) -> AsyncIterator[StreamEvent]:
        """Open the SSE stream and yield parsed events.

        Low-level generator — use listen() for the high-level API.
        """
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        if self._last_event_id:
            headers["Last-Event-ID"] = self._last_event_id

        client = await self._get_client()

        async with client.stream(
            "GET",
            "/v1/stream",
            headers=headers,
            timeout=None,  # Long-lived connection
        ) as response:
            response.raise_for_status()

            event_type: str | None = None
            event_id: str | None = None
            data_lines: list[str] = []

            async for raw_line in response.aiter_lines():
                line = raw_line.rstrip("\n\r")

                # Comment line (keepalive) — ignore
                if line.startswith(":"):
                    continue

                # Empty line = end of event
                if not line:
                    if data_lines:
                        event = _parse_event(event_type, event_id, data_lines)
                        if event:
                            if event_id:
                                self._last_event_id = event_id
                            yield event

                    # Reset for next event
                    event_type = None
                    event_id = None
                    data_lines = []
                    continue

                # Parse field
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line.startswith("id:"):
                    event_id = line[3:].strip()
                elif line.startswith("retry:"):
                    # Server-controlled reconnect interval — acknowledged but
                    # we manage our own backoff in listen()
                    pass


def _parse_event(
    event_type: str | None,
    event_id: str | None,
    data_lines: list[str],
) -> StreamEvent | None:
    """Parse raw SSE fields into a typed StreamEvent."""
    if not data_lines:
        return None

    raw_data = "\n".join(data_lines)

    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        logger.warning("Failed to parse SSE data: %s", raw_data[:100])
        return None

    if event_type == "connected":
        return StreamEvent(
            type=EventType.CONNECTED,
            connected=ConnectedEvent(
                user_id=data.get("user_id", ""),
                assigned_number=data.get("assigned_number", ""),
                server_time=data.get("server_time", ""),
            ),
        )

    if event_type == "message":
        return StreamEvent(type=EventType.MESSAGE, message=_message_from_dict(data))

    if event_type == "error":
        return StreamEvent(
            type=EventType.ERROR,
            error=ErrorEvent(
                code=data.get("code", "unknown"),
                message=data.get("message", ""),
                retry_after=data.get("retry_after"),
            ),
        )

    logger.debug("Unknown event type: %s", event_type)
    return None


def _message_from_dict(data: dict) -> InboundMessage:
    """Build an InboundMessage from the API's message JSON (SSE, wait, recent)."""
    return InboundMessage(
        id=data.get("id", ""),
        text=data.get("text", ""),
        received_at=data.get("received_at", ""),
        channel=data.get("channel", "sms"),
        trust_level=data.get("trust_level", "low"),
        has_pin=data.get("has_pin", False),
    )


async def _async_sleep(seconds: float) -> None:
    """Async sleep — extracted for testability."""
    import asyncio

    await asyncio.sleep(seconds)
