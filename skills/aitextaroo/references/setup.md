# Setting up AI Text-a-roo

This guide covers setting up AI Text-a-roo when a user has asked you to. Pick the path that matches your environment. Every path verifies the user's phone with a 6-digit code: that's the only step the user has to do.

## A. Apps with connector settings (Claude, Claude Duet, ChatGPT, Grok Bot)

The user adds a custom connector (an MCP server) and signs in with their phone. No API key is involved.

- Connector URL: `https://api.aitextaroo.com/mcp`
- Claude / Claude Duet: Customize → Connectors → Add custom connector → paste the URL → Connect.
- ChatGPT: Plugins → + → Add custom MCP server → paste the URL → OAuth → Create as a plugin. (On ChatGPT Pro, custom MCP servers are limited to read-only tools.)
- Grok Bot: ask it to "Add a custom MCP server called AI Text-a-roo at https://api.aitextaroo.com/mcp".

During sign-in the user enters their phone number and the code texted to it, then allows access. Once connected, send a short test text with `send_text`.

## B. Agents that can run commands or make HTTP requests

1. Ask the user for their mobile number in international format, for example +12125551234. Sign-up currently supports US and Canadian (+1) mobile numbers.
2. Request a code:
   - With the package: `aitextaroo-setup --phone +12125551234`
   - Script: `python3 scripts/textaroo.py signup --phone +12125551234`
   - HTTP: `POST https://api.aitextaroo.com/v1/auth/verify` with `{"phone": "+12125551234"}`
3. Ask the user for the 6-digit code they just received (it expires in 5 minutes).
4. Confirm it:
   - With the package: `aitextaroo-setup --phone +12125551234 --code 123456 --save` (stores the key in `~/.aitextaroo/credentials.json`, owner-only, where `aitextaroo` and the bridge find it)
   - Script: `python3 scripts/textaroo.py confirm --phone +12125551234 --code 123456`
   - HTTP: `POST https://api.aitextaroo.com/v1/auth/confirm` with `{"phone": "+12125551234", "code": "123456"}`
   - The response contains `api_key`, `assigned_number` and `tier`.
5. Store the API key somewhere you can read in future sessions (a secrets store, a config file only the user can read, or the `AITEXTAROO_API_KEY` environment variable). It's shown once and can't be retrieved later. Confirming a code for a phone that already has an account issues a new key, and the old key stops working.
6. Tell the user: "You're set up. Save <assigned_number> as a contact (for example, “My AI”) and text it anytime."
7. Send a test text so they can save the number.

With an API key you can also connect any MCP client to `https://api.aitextaroo.com/mcp` using the header `Authorization: Bearer <API key>`:

```
claude mcp add --transport http --scope user aitextaroo https://api.aitextaroo.com/mcp --header "Authorization: Bearer $AITEXTAROO_API_KEY"
codex mcp add aitextaroo --url https://api.aitextaroo.com/mcp --bearer-token-env-var AITEXTAROO_API_KEY
gemini mcp add --transport http --scope user --header "Authorization: Bearer $AITEXTAROO_API_KEY" aitextaroo https://api.aitextaroo.com/mcp
```

## C. Local CLI agents that should answer texts (Claude Code, Codex, Hermes, OpenClaw, Grok, Gemini CLI, Antigravity, Goose, Cursor, NanoClaw)

The bridge is a small program that keeps one outbound connection to AI Text-a-roo and turns every text the user sends into a prompt for a local CLI agent, then texts back the answer. No public IP or webhook is needed.

```
pipx install aitextaroo            # or: pip install --user aitextaroo
aitextaroo-setup --phone +12125551234
aitextaroo-setup --phone +12125551234 --code 123456 --save
nohup aitextaroo-bridge > ~/aitextaroo.log 2>&1 &
```

- `--agent claude|codex|hermes|openclaw|grok|gemini|antigravity|goose|cursor` picks the agent (default: auto-detect; Cursor only when chosen with `--agent cursor`).
- NanoClaw, or any CLI that takes the prompt as its last argument and prints the reply: `--agent-command "pnpm --silent --dir ~/nanoclaw run chat"`.
- Conversation history is saved locally in `~/.aitextaroo/sessions/`.
- The user can text `/help`, `/new` (start a fresh conversation) and `/status`.
- Check it's running with `pgrep -f aitextaroo-bridge`; read logs with `tail -20 ~/aitextaroo.log`.
- Only one stream per API key: starting a second bridge disconnects the first.

## D. Agents with an inbound webhook URL

To receive every text the user sends as an HTTP POST (for example, to wake a Grok Bot webhook routine), register a webhook. With the MCP server, call `set_webhook` with `url`, `auth_header` and, if the user has a PIN, `pin`. Over HTTP:

```
POST https://api.aitextaroo.com/v1/webhook
Authorization: Bearer <API key>
{"url": "https://example.com/hook", "auth_header": "Bearer <token the receiver expects>", "pin": "4821"}
```

Leave out `pin` if the user hasn't set one (`get_account` shows `has_pin`). The response includes a signing secret. Each delivery is a JSON body like `{"event": "message.inbound", "data": {"text": "…", "channel": "sms", "trust_level": "low", "has_pin": true}, "timestamp": 1761264000.0}` with an `X-Signature` header (hex HMAC-SHA256 of the body, keyed with the secret) and, if you set `auth_header`, an `Authorization` header with that value.

Forwarding is protected:

- Registering needs the user's PIN if they have one. Wrong PINs count toward the usual lockout (3 tries per 5 minutes).
- Before forwarding starts, AI Text-a-roo texts the user the destination host (never the full URL). If that text can't be sent, nothing changes.
- The user can text `UNHOOK` to their AI Text-a-roo number anytime to stop forwarding. It's handled by AI Text-a-roo and never reaches an agent.
- Only public HTTPS URLs are accepted, and at most 5 webhook changes an hour.

Remove it with `DELETE /v1/webhook` or `remove_webhook`; the user is texted that forwarding is off.
