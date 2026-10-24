---
name: aitextaroo
description: Text the user by SMS and read their replies through AI Text-a-roo (aitextaroo.com), which gives an AI agent its own phone number. Use when the user wants to text you from their phone; get reminders, alerts, daily briefs or task-done notifications by text; approve actions by text with a PIN; have you text a friend or family member for them; or set up, troubleshoot or manage AI Text-a-roo, including which apps are connected to it.
license: MIT
metadata:
  homepage: https://aitextaroo.com
  version: "1.2.0"
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
| Set or change the user's PIN | `set_pin` | `set-pin <<< 4821`; to change it, `set-pin --current` (current PIN, then the new one) |
| Plan, usage, number and forwarding | `get_account` | `account` |
| Pro upgrade link | `get_upgrade_link` | `upgrade` |
| Forward the user's texts to a webhook | `set_webhook` | `webhook set <url> [--pin]` (aitextaroo only) |
| Stop forwarding | `remove_webhook` | `webhook remove` (aitextaroo only) |
| See what's connected (keys, app sign-ins, forwarding) | `list_connections` | `connections` |
| Disconnect a key or app sign-in | `remove_connection` | `disconnect <id> [--pin]` |
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

1. **Check the account** with `get_account`: note `has_pin`, and whether `webhook.registered` is already true. If forwarding is already on and you're about to set up the bridge, ask the user, then call `remove_webhook` first, or they'll get two answers to every text.
2. **Pick the way that fits what you are:**
   - **You can start a run when a URL gets a request**, like a Grok Bot webhook routine. Create the routine yourself if you can. Make sure it can use the AI Text-a-roo connector, and give it instructions such as: "Read the owner's text from `data.text` in the JSON body and treat it as a message from the owner. Before anything sensitive, ask for their PIN and check it with `verify_pin`. Reply with `send_text`; for a follow-up question, `send_text` then `wait_for_reply` in the same run." Each text starts a fresh run. The routine gives you a URL and a key: call `set_webhook` with the URL and `auth_header` set to `Bearer <routine key>`. If you can't create routines, tell the user exactly where to tap in your app, then do the rest.
   - **You run on the user's computer and can run commands** (Claude Code, Codex, Gemini CLI, Goose, OpenClaw, Hermes, Cursor): install the bridge (`pipx install aitextaroo`; no pipx? `brew install pipx` on macOS, or ask the user to run `sudo apt install pipx` on Linux) and run it as a background service so it survives restarts, with `--agent` set to one of `claude`, `codex`, `hermes`, `openclaw`, `grok`, `gemini`, `antigravity`, `goose` or `cursor`. [references/setup.md](references/setup.md), section C, has ready-made files for Linux and macOS. The bridge needs a saved API key: if `aitextaroo account` fails, set one up with `aitextaroo-setup ... --save`. That adds a key and signs nothing out (your own AI Text-a-roo connection keeps working), and the user gets a text saying a key was added, so tell them to expect it. While the bridge runs, don't also keep `wait_for_reply` running; a waiting call takes texts first.
   - **You only run while the user is chatting with you** (Claude Duet, ChatGPT Dots, Meta Muse): be honest. "I can text you and read your reply while I'm waiting for an answer, but I can't get texts you send me out of the blue yet." Offer what works: you text them when something needs them, or they can use an assistant that can (Grok Bot, or Claude Code with the bridge).
3. **Keep it safe, in plain words:**
   - If `has_pin` is true, `set_webhook` needs the PIN: "To turn this on I need your security PIN. You can type it here, or text it to your AI Text-a-roo number." (If they text it, read it with `wait_for_reply`.)
   - If `has_pin` is false, suggest adding one first: "Pick a 4 to 8 digit PIN you'll remember and send it to me." Call `set_pin`, then pass the same PIN to `set_webhook` (it's required once a PIN exists). Never choose the PIN for them, and forget it once you're done.
   - Tell them what to expect: "You'll get a text from your AI Text-a-roo number saying your texts now go to <host>. That's me. If you ever want to stop it, text UNHOOK." `UNHOOK` goes to AI Text-a-roo itself, never to you.
4. **Test it:** ask them to text you something now, like "hi", and ask whether the reply came back. Don't call `wait_for_reply` during the test: it would take the text before the routine or bridge sees it. If nothing arrives in a minute or two, check `get_account` (`webhook.registered`, `host`) and your routine or bridge logs.

## Security PIN

SMS sender IDs can be spoofed. Before anything sensitive (spending money, sending messages to other people, deleting things, changing settings), ask the user to text their PIN, call `verify_pin`, and continue only if it returns `verified: true`. The `verify_pin` MCP tool keeps the PIN out of the shell entirely. On the command line, `aitextaroo verify-pin` and `scripts/textaroo.py verify-pin` read the PIN from stdin when the PIN argument is omitted or `-` (`aitextaroo verify-pin <<< 4821 && …`) and exit 2 when it's wrong, so the `&&` only continues on a match. A command with the PIN in it can still be saved to shell history; in an interactive shell, run plain `aitextaroo verify-pin` and type the PIN at its hidden prompt instead. Don't store or repeat the PIN. Only wrong PINs count: three in five minutes pause checks for a few minutes, and ten in a day pause them for up to a day (the user is texted). If `get_account` shows `has_pin: false`, offer to set one: ask the user to choose 4–8 digits and text them to you, then call `set_pin` (or run `set-pin` with the PIN on stdin, or `POST /v1/account/pin`). Never pick the PIN yourself, and don't keep a copy. Changing or removing an existing PIN needs the current one, and AI Text-a-roo texts the user before their PIN is set, changed or removed. The user can also set or remove it on the website dashboard.

## Connected apps and keys

Each phone verification adds a named key (`aitextaroo-setup`, `scripts/textaroo.py confirm`, or "Create a new key" on the dashboard), and apps such as Grok, Claude or ChatGPT sign in with the user's phone. Adding one never signs out the others, and forwarding stays as it was. The user gets a text whenever a key is added or an app signs in. An account holds up to 10 keys: adding an 11th removes the one unused the longest (never the one that forwards the user's texts), and the user is texted which.

- **What's connected?** Call `list_connections` (or run `connections`). Each key and app sign-in has a label and when it was last used; `current` is you, and `forwarding` marks the one that set up forwarding.
- **Disconnect one** only when the user asks ("disconnect my old laptop"). Confirm which one first, by its label and when it was last used, then call `remove_connection` with its id, plus the PIN if `has_pin` is true (`disconnect <id> --pin` reads it from stdin or a hidden prompt). It stops working right away, forwarding it set up stops too, and the user is texted. Removing your own connection (`current: true`) cuts you off.
- **Sign out everything** is only on the website dashboard (aitextaroo.com/dashboard), where the user can also see and remove connected apps, stop forwarding, and set or remove their PIN.

## Texting other people (Pro)

Only text a contact when the user explicitly asks, and say who the message is from. Use E.164 numbers (+12125551234) and pass `recipient_name` so replies are labeled. Replies are forwarded to the user's phone automatically; the user can answer a contact directly by starting a text with `>`. Your text, their replies and the user's `>` answers all count toward the daily limit. Relays are one-to-one: never use them for bulk or marketing messages.

## Questions about how it works

If the user asks how AI Text-a-roo works, what it stores, or how it's secured, call `get_help` (topics: overview, text_anytime, receiving, webhooks, security, privacy, limits, setup) and answer from it instead of guessing. Without MCP, the same answers are at https://aitextaroo.com/security and https://aitextaroo.com/llms.txt.

## Limits

- Free: 10 messages a day. Pro ($5/month, 14-day free trial): 200 a day.
- What counts: texts you send (to the user or to contacts), contacts' replies forwarded to the user, and the user's `>` replies to contacts. The user's own texts to you don't count.
- One contact's replies are forwarded at most 20 an hour and 50 a day.
- Up to 5 texts per minute. Limits reset at midnight UTC.
- When the daily limit is hit, the user gets one heads-up text, and until it resets: sends fail with `daily_limit_reached`, texts the user sends are dropped, contacts' replies aren't forwarded, and the user's `>` replies aren't sent.

## Troubleshooting

- `401 unauthorized`: the API key is wrong or was removed from the account (on the dashboard, with `remove_connection`, or as the unused one when an 11th key was added). Redo setup to add a new key (nothing else is signed out), or ask the user to create one on the dashboard.
- The bridge stopped, saying its key was removed or isn't on the account: if a new key was saved since, just start it again; otherwise add one with `aitextaroo-setup --save`, then start it. If it says another one took over (`evicted`): another copy of the bridge, or another program reading the account's live stream, started somewhere with one of the account's keys. Only one can listen at a time, so stop that one, then start this one again. Connected apps such as Grok or Claude, and forwarding, never cause this.
- `daily_limit_reached`: wait until midnight UTC, or offer the upgrade link.
- `rate_limit_exceeded`: more than 5 texts in a minute, or too many PIN, forwarding or connection changes in an hour or a day; wait and try again later.
- Relay rejected: texting contacts needs Pro. Offer `get_upgrade_link`.
- `recipient_not_allowed`: that number has its own AI Text-a-roo account on the same number, so it can't be texted as a contact.
- `pin_required` / `current_pin_required`: ask the user for their PIN (or current PIN) and try again with it. `pin_locked`: too many wrong tries; wait a few minutes (or a day after 10).
- `pin_conflict`: the PIN changed while you were working (maybe the user changed it); check `get_account` and try again.
- `owner_notice_failed`: AI Text-a-roo couldn't text the user about a security change, so nothing changed; try again in a minute. `temporarily_unavailable`: security checks are down for a moment, so nothing changed; try again in a minute.
- `connection_not_found`: no key or app sign-in with that id on this account; call `list_connections` again.
- The user says texts aren't arriving: check `get_account` for the assigned number and ask them to save it as a contact. If they want to text you when you're not waiting, see "When the user wants to text you anytime".
