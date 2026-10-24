---
name: aitextaroo
description: Text the user by SMS and read their replies through AI Text-a-roo (aitextaroo.com), which gives an AI agent its own phone number. Use when the user wants to text you from their phone; get reminders, alerts, daily briefs or task-done notifications by text; approve actions by text with a PIN; have you text a friend or family member for them; or set up or troubleshoot AI Text-a-roo.
license: MIT
metadata:
  homepage: https://aitextaroo.com
  version: "1.0.0"
---

# AI Text-a-roo

AI Text-a-roo is an SMS gateway for AI agents. The user verifies their phone number once; after that you can text them, they can text you back from any phone (no app), and on the Pro plan you can text other people on their behalf. Message content is never stored by AI Text-a-roo.

## Connect

Use the first option that works in your environment:

1. **MCP tools.** If tools such as `send_text` and `wait_for_reply` are available, use them. The remote MCP server is `https://api.aitextaroo.com/mcp` (OAuth sign-in with the user's phone, or `Authorization: Bearer <API key>`).
2. **The `aitextaroo` command.** If it's installed (`pipx install aitextaroo`), use it: `aitextaroo ask "…"` texts a question and waits for the answer. It finds the key in `AITEXTAROO_API_KEY` or `~/.aitextaroo/credentials.json`.
3. **Script.** If you can run Python 3 but can't install packages, use `scripts/textaroo.py` (standard library only). It reads the key from `AITEXTAROO_API_KEY`.
4. **HTTP.** Call the REST API directly. See [references/api.md](references/api.md).

If the user isn't set up yet, follow [references/setup.md](references/setup.md). Setup needs two things from the user: their phone number and the 6-digit code texted to it.

## Tools at a glance

| Task | MCP tool | Command (`aitextaroo` or `scripts/textaroo.py`) |
|---|---|---|
| Text the user | `send_text` | `send "…"` |
| Ask and wait for the answer | `send_text` + `wait_for_reply` | `ask "…" --timeout 90` (aitextaroo only) |
| Wait for the user's reply | `wait_for_reply` | `wait --timeout 90` |
| Read texts from the last 5 minutes | `get_recent_messages` | `recent` |
| Text a contact for the user (Pro) | `text_contact` | `relay --to +1… --name Mom "…"` |
| Check a PIN the user texted | `verify_pin` | `verify-pin <<< 4821` |
| Set the user's PIN | | `set-pin <<< 4821` |
| Plan, usage and number | `get_account` | `account` |
| Pro upgrade link | `get_upgrade_link` | `upgrade` |

## Writing good texts

- Plain text only: no markdown, tables or code blocks. Up to 1,600 characters, but most texts should be 1–3 short sentences.
- Lead with the point. Say what reply you need: “Reply YES to book it.”
- One question per text. If several decisions are needed, ask the most important first.
- Text when it's worth an interruption: something time-sensitive, a decision only the user can make, or something they asked to hear about. Batch routine updates into one text.
- Respect quiet hours in the user's time zone (roughly 9 PM–8 AM) unless they asked or it's urgent.
- Never text passwords, one-time codes, full card or account numbers, or other secrets, and never ask the user to text them to you. The one exception is the security PIN below.

## Asking and waiting

To get a decision, send the question with `send_text`, then call `wait_for_reply` (60–120 seconds per call). Call it again if it times out and the decision can still wait; after a few tries, continue without the answer or say in your own interface that you're waiting. A pending `wait_for_reply` receives the user's next text before anything else does.

## Security PIN

SMS sender IDs can be spoofed. Before anything sensitive (spending money, sending messages to other people, deleting things, changing settings), ask the user to text their PIN, call `verify_pin`, and continue only if it returns `verified: true`. The `verify_pin` MCP tool keeps the PIN out of the shell entirely. On the command line, `aitextaroo verify-pin` and `scripts/textaroo.py verify-pin` read the PIN from stdin rather than taking it as an argument (`aitextaroo verify-pin <<< 4821 && …`) and exit 2 when it's wrong, so the `&&` only continues on a match. A command with the PIN in it can still be saved to shell history; in an interactive shell, run plain `aitextaroo verify-pin` and type the PIN at its hidden prompt instead. Don't store or repeat the PIN. Three wrong attempts lock verification for five minutes. If `get_account` shows `has_pin: false`, offer to set one: ask the user to choose 4–8 digits, then run `set-pin` (PIN on stdin) or call `POST /v1/account/pin` (see [references/api.md](references/api.md)). Don't keep a copy.

## Texting other people (Pro)

Only text a contact when the user explicitly asks, and say who the message is from. Use E.164 numbers (+12125551234) and pass `recipient_name` so replies are labeled. Replies are forwarded to the user's phone automatically; the user can answer a contact directly by starting a text with `>`. Relays are one-to-one: never use them for bulk or marketing messages.

## Limits

- Free: 10 messages a day. Pro ($5/month, 14-day free trial): 200 a day.
- Up to 5 texts per minute. Limits reset at midnight UTC.
- When the daily limit is hit, sends fail with `daily_limit_reached` and the user gets one heads-up text.

## Troubleshooting

- `401 unauthorized`: the API key is wrong or was regenerated. Ask the user for a new key from the dashboard, or redo setup.
- `daily_limit_reached`: wait until midnight UTC, or offer the upgrade link.
- Relay rejected: texting contacts needs Pro. Offer `get_upgrade_link`.
- The user says texts aren't arriving: check `get_account` for the assigned number and ask them to save it as a contact.
