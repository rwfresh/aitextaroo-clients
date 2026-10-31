# AI Text-a-roo REST API

Base URL: `https://api.aitextaroo.com/v1`. Authenticated endpoints need `Authorization: Bearer <API key>`. Requests and responses are JSON. OpenAPI spec: https://api.aitextaroo.com/openapi.json

## Sign-up (no API key)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/verify` | `{"phone": "+14165550123"}` | `{"status": "code_sent", "expires_in": 300}` |
| POST | `/auth/confirm` | `{"phone": "+14165550123", "code": "123456", "label": "Claude on studio-mac"}` | `{"api_key", "key_id", "assigned_number", "tier", "note", "retired"}` |

Each confirmation adds a key named `label` (optional, 1–40 letters, digits, spaces or `. _ ( ) ' @ # : + -`; default "API key"). If the account already exists, its other keys, app sign-ins and forwarding keep working, and the user is texted that a key was added. Up to 10 keys: an 11th removes the one unused the longest (never the one that forwards the user's texts when another can go), and the user is texted which. `note` says first what changed, and `retired` lists any key removed: `[{"id": "key_…", "label": "…", "forwarding_stopped": "<host>" | null}]`, usually `[]`.

## Messaging

| Method | Path | Body / query | Notes |
|---|---|---|---|
| POST | `/send` | `{"text": "…"}` | Texts the user. Max 1,600 characters. |
| POST | `/send` | `{"text": "…", "to": "+1…", "recipient_name": "Mom"}` | Texts a contact (Pro). Their replies are forwarded to the user for an hour after the last text to them (yours, or the user's `>` reply). |
| POST | `/messages/wait` | `{"timeout_seconds": 60}` (1–120) | Waits for the user's next text. Returns `{"message": {...} \| null, "timed_out": bool}`. |
| GET | `/messages/recent` | `?after_id=<message id>` (optional) | Texts from the last 5 minutes: `{"messages": [...], "retention_seconds": 300}`. |
| GET | `/stream` | `Accept: text/event-stream` | Server-Sent Events stream of inbound texts. One stream per account; supports `Last-Event-ID`. |

An inbound message looks like `{"id": "<uuid>", "text": "…", "received_at": "…", "channel": "sms", "trust_level": "low", "has_pin": true}`.

The stream can end with an `error` event, `{"code": "…", "message": "…"}`: `server_restarting` (a deploy; reconnect after `retry_after` seconds), `reconnect_required` (reconnect), `evicted` (another stream took over the account; don't reconnect automatically, or the two take turns kicking each other off) or `credential_revoked` (the key was removed; reconnecting gets a 401). Reconnect on any other code. A keepalive comment comes at least every 20 seconds, so a stream that's silent for much longer than that is dead: reconnect.

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
| GET | `/account/connections` | | The account's keys and app sign-ins (see below). |
| DELETE | `/account/connections/{id}` | `{"pin": "4821"}` (only if the user has a PIN) | Disconnect one key or app sign-in. It stops working right away, forwarding it set up stops too, and the user is texted. At most 5 removals an hour and 10 a day. Returns `{"status": "removed", "removed": {"id", "kind", "label"}, "forwarding_stopped": "<host>" \| null, "owner_notified": bool, "was_current": bool}`. |

`GET /account/connections` returns `{"keys": [...], "apps": [...], "forwarding": {"host", "set_by", "set_at"} | null, "max_keys": 10}`. Each entry has `id` (`key_…` or `app_…`), `kind` (`key` or `app`), `label`, `created_at`, `last_used_at` (or null), `current` (the key or sign-in making this request) and `forwarding` (it set up forwarding); keys also have `hint` (the key's last 4 characters, like `...3f9a`), apps have `verified`. Most recently used first. Signing out everything at once is only on the dashboard, aitextaroo.com/dashboard.

## Billing

| Method | Path | Returns |
|---|---|---|
| POST | `/billing/checkout` | `{"checkout_url": "https://checkout.stripe.com/…"}`: send it to the user to start Pro (14-day free trial). |
| POST | `/billing/portal` | `{"portal_url": "…"}` to manage or cancel. |

## Errors

Errors return `{"error": {"code": "…", "message": "…"}}` (authentication failures wrap the same object in `detail`). Common codes:

- `unauthorized` (401): missing or wrong API key, or one that was removed from the account.
- `tier_required` (403): texting contacts needs Pro.
- `pin_required` / `pin_incorrect` (403): this change needs the user's PIN, or the PIN was wrong (wrong PINs count toward the lockout).
- `connection_not_found` (404): no key or app sign-in with that id on this account.
- `rate_limit_exceeded` (429): more than 5 texts in a minute, or too many PIN, webhook or connection changes.
- `daily_limit_reached` (429): resets at midnight UTC; until then texts pause both ways. Texts you send, contacts' replies forwarded to the user and the user's `>` replies count; the user's own texts to you don't. Contacts' replies are forwarded at most 20 an hour and 50 a day per contact, and not at all once 80% of the day's limit is used.
- `pin_locked` (429): too many wrong PIN attempts; try again in a few minutes.
- `temporarily_unavailable` (503): security checks are unavailable right now, so nothing changed; try again in a minute.
