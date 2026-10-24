# AI Text-a-roo REST API

Base URL: `https://api.aitextaroo.com/v1`. Authenticated endpoints need `Authorization: Bearer <API key>`. Requests and responses are JSON. OpenAPI spec: https://api.aitextaroo.com/openapi.json

## Sign-up (no API key)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/verify` | `{"phone": "+12125551234"}` | `{"status": "code_sent", "expires_in": 300}` |
| POST | `/auth/confirm` | `{"phone": "+12125551234", "code": "123456"}` | `{"api_key", "assigned_number", "tier", ...}` |

## Messaging

| Method | Path | Body / query | Notes |
|---|---|---|---|
| POST | `/send` | `{"text": "…"}` | Texts the user. Max 1,600 characters. |
| POST | `/send` | `{"text": "…", "to": "+1…", "recipient_name": "Mom"}` | Texts a contact (Pro). Replies are forwarded to the user. |
| POST | `/messages/wait` | `{"timeout_seconds": 60}` (1–120) | Waits for the user's next text. Returns `{"message": {...} \| null, "timed_out": bool}`. |
| GET | `/messages/recent` | `?after_id=<message id>` (optional) | Texts from the last 5 minutes: `{"messages": [...], "retention_seconds": 300}`. |
| GET | `/stream` | `Accept: text/event-stream` | Server-Sent Events stream of inbound texts. One stream per key; supports `Last-Event-ID`. |

An inbound message looks like `{"id": "<uuid>", "text": "…", "received_at": "…", "channel": "sms", "trust_level": "low", "has_pin": true}`.

Delivery order: a pending `/messages/wait` (or MCP `wait_for_reply`) gets the next text first; otherwise it goes to the live `/stream` connection or webhook; otherwise it waits in memory for up to 5 minutes.

## Account and security

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/account` | | Plan, assigned number, `has_pin`, `messages_today`, `daily_limit`, and `webhook` (whether texts are forwarded, and to which host). |
| POST | `/account/pin` | `{"pin": "4821", "current_pin": "1111"}` | Set the security PIN (4–8 digits, chosen by the user), or change it: `current_pin` is required when a PIN exists. The user is texted first. Returns `pin_set` or `pin_changed`. |
| DELETE | `/account/pin` | `{"current_pin": "1111"}` | Remove the PIN (needs the current one; the user is texted first). |
| POST | `/verify-pin` | `{"pin": "4821"}` | `{"verified": bool, "attempts_remaining": int \| null}`. Only wrong PINs count: 3 per 5 minutes and 10 a day pause checks. |
| POST | `/webhook` | `{"url": "https://…", "auth_header": "Bearer …", "pin": "4821"}` | Forward inbound texts to a URL. `auth_header` is optional; `pin` is required if the user has one. The user is texted the destination first and can reply `UNHOOK` to stop it. |
| DELETE | `/webhook` | | Stop webhook delivery (the user is texted). |

## Billing

| Method | Path | Returns |
|---|---|---|
| POST | `/billing/checkout` | `{"checkout_url": "https://checkout.stripe.com/…"}`: send it to the user to start Pro (14-day free trial). |
| POST | `/billing/portal` | `{"portal_url": "…"}` to manage or cancel. |

## Errors

Errors return `{"error": {"code": "…", "message": "…"}}` (authentication failures wrap the same object in `detail`). Common codes:

- `unauthorized` (401): missing, wrong or regenerated API key.
- `tier_required` (403): texting contacts needs Pro.
- `rate_limit_exceeded` (429): more than 5 texts in a minute.
- `daily_limit_reached` (429): resets at midnight UTC.
- `pin_locked` (429): too many wrong PIN attempts; try again in a few minutes.
