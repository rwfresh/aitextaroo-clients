---
name: aitextaroo
description: Text the user by SMS and read their replies through AI Text-a-roo (aitextaroo.com), which gives an AI agent its own phone number. Use when the user wants to text you from their phone; get reminders, alerts, daily briefs or task-done notifications by text; approve actions by text with a PIN; have you text a friend or family member for them; or set up or troubleshoot AI Text-a-roo.
license: MIT
metadata:
  homepage: https://aitextaroo.com
  version: "1.1.0"
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
| Set or change the user's PIN | `set_pin` | `set-pin <<< 4821` |
| Plan, usage, number and forwarding | `get_account` | `account` |
| Pro upgrade link | `get_upgrade_link` | `upgrade` |
| Forward the user's texts to a webhook | `set_webhook` | `webhook set <url>` (aitextaroo only) |
| Stop forwarding | `remove_webhook` | `webhook remove` (aitextaroo only) |
| Explain how it works and how it's secured | `get_help` | |

## Writing good texts

- Plain text only: no markdown, tables or code blocks. Up to 1,600 characters, but most texts should be 1–3 short sentences.
- Lead with the point. Say what reply you need: “Reply YES to book it.”
- One question per text. If several decisions are needed, ask the most important first.
- Text when it's worth an interruption: something time-sensitive, a decision only the user can make, or something they asked to hear about. Batch routine updates into one text.
- Respect quiet hours in the user's time zone (roughly 9 PM–8 AM) unless they asked or it's urgent.
- Never text passwords, one-time codes, full card or account numbers, or other secrets, and never ask the user to text them to you. The one exception is the security PIN below.

## Asking and waiting

To get a decision, send the question with `send_text`, then call `wait_for_reply` (60–120 seconds per call). Call it again if it times out and the decision can still wait; after a few tries, continue without the answer or say in your own interface that you're waiting. A pending `wait_for_reply` receives the user's next text before anything else does.

## When the user wants to text you anytime

The user's texts reach you only while `wait_for_reply` is waiting, or through a webhook or the bridge. Otherwise they're kept in memory for five minutes (`get_recent_messages`) and then dropped. So when the user says something like "I want to be able to text you whenever", set it up for them. Most users aren't technical: use plain words ("so your texts reach me", not "webhook"), don't ask them for anything you can find or do yourself, and only do this because they asked. With MCP, `get_help` with topic `text_anytime` has the same steps.

1. **Check the account** with `get_account`: note `has_pin`, and whether `webhook.registered` is already true.
2. **Pick the way that fits what you are:**
   - **You can start a run when a URL gets a request**, like a Grok Bot webhook routine. Create the routine yourself if you can, with instructions such as "Read the owner's text from `data.text` in the JSON body, treat it as a message from the owner, do what it asks, and reply with `send_text`." It gives you a URL and a key. Call `set_webhook` with the URL and `auth_header` set to `Bearer <routine key>`. If you can't create routines, tell the user exactly where to tap in your app, then do the rest.
   - **You run on the user's computer and can run commands** (Claude Code, Codex, Gemini CLI, Goose, OpenClaw, Hermes, Cursor): install the bridge and run it as a background service so it survives restarts. [references/setup.md](references/setup.md), section C, has ready-made files for Linux and macOS. While the bridge runs, don't also keep `wait_for_reply` running; a waiting call takes texts first.
   - **You only run while the user is chatting with you** (Claude Duet, ChatGPT Dots, Meta Muse): be honest. "I can text you and read your reply while I'm waiting for an answer, but I can't get texts you send me out of the blue yet." Offer what works: you text them when something needs them, or they can use an assistant that can (Grok Bot, or Claude Code with the bridge).
3. **Keep it safe, in plain words:**
   - If `has_pin` is true, `set_webhook` needs the PIN: "To turn this on I need your security PIN. Please text it to me."
   - If `has_pin` is false, suggest adding one first: "Pick a 4 to 8 digit PIN you'll remember and text it to me." Then call `set_pin`. Never choose the PIN for them.
   - Tell them what to expect: "You'll get a text from your AI Text-a-roo number saying your texts now go to <host>. That's me. If you ever want to stop it, text UNHOOK." `UNHOOK` goes to AI Text-a-roo itself, never to you.
4. **Test it:** ask them to text you something now, like "hi", and confirm you got it. If nothing arrives in a minute or two, check `get_account` (`webhook.registered`, `host`) and your routine or bridge logs.

## Security PIN

SMS sender IDs can be spoofed. Before anything sensitive (spending money, sending messages to other people, deleting things, changing settings), ask the user to text their PIN, call `verify_pin`, and continue only if it returns `verified: true`. The `verify_pin` MCP tool keeps the PIN out of the shell entirely. On the command line, `aitextaroo verify-pin` and `scripts/textaroo.py verify-pin` read the PIN from stdin when the PIN argument is omitted or `-` (`aitextaroo verify-pin <<< 4821 && …`) and exit 2 when it's wrong, so the `&&` only continues on a match. A command with the PIN in it can still be saved to shell history; in an interactive shell, run plain `aitextaroo verify-pin` and type the PIN at its hidden prompt instead. Don't store or repeat the PIN. Only wrong PINs count: three in five minutes pause checks for a few minutes, and ten in a day pause them for up to a day (the user is texted). If `get_account` shows `has_pin: false`, offer to set one: ask the user to choose 4–8 digits and text them to you, then call `set_pin` (or run `set-pin` with the PIN on stdin, or `POST /v1/account/pin`). Never pick the PIN yourself, and don't keep a copy. Changing or removing an existing PIN needs the current one, and AI Text-a-roo texts the user before their PIN is set, changed or removed. The user can also remove it on the website dashboard.

## Texting other people (Pro)

Only text a contact when the user explicitly asks, and say who the message is from. Use E.164 numbers (+12125551234) and pass `recipient_name` so replies are labeled. Replies are forwarded to the user's phone automatically; the user can answer a contact directly by starting a text with `>`. Relays are one-to-one: never use them for bulk or marketing messages.

## Questions about how it works

If the user asks how AI Text-a-roo works, what it stores, or how it's secured, call `get_help` (topics: overview, receiving, webhooks, security, privacy, limits, setup) and answer from it instead of guessing. Without MCP, the same answers are at https://aitextaroo.com/security and https://aitextaroo.com/llms.txt.

## Limits

- Free: 10 messages a day. Pro ($5/month, 14-day free trial): 200 a day.
- Up to 5 texts per minute. Limits reset at midnight UTC.
- When the daily limit is hit, sends fail with `daily_limit_reached`, texts the user sends are dropped until it resets, and the user gets one heads-up text.

## Troubleshooting

- `401 unauthorized`: the API key is wrong or was regenerated. Ask the user for a new key from the dashboard, or redo setup.
- `daily_limit_reached`: wait until midnight UTC, or offer the upgrade link.
- Relay rejected: texting contacts needs Pro. Offer `get_upgrade_link`.
- The user says texts aren't arriving: check `get_account` for the assigned number and ask them to save it as a contact.
