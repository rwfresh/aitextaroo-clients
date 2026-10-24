# AI Text-a-roo: setup guide for AI agents

AI Text-a-roo is an SMS gateway for AI agents. It gives an agent its own phone
number: the user texts it from any phone (no app), and the agent can text the
user back, or first. Message content is never stored.

Setup needs two things from the user: their US or Canadian mobile number, and
the 6-digit code that AI Text-a-roo texts to it. The agent can do the rest.
Pick the path that matches the environment.

- Agent Skill: [`skills/aitextaroo/SKILL.md`](skills/aitextaroo/SKILL.md) (also at https://aitextaroo.com/skills/aitextaroo/SKILL.md)
- Overview for agents: https://aitextaroo.com/llms.txt
- Plain-text version of this guide: https://api.aitextaroo.com/v1/agent-setup

## A. Apps with connector settings (Claude, Claude Duet, ChatGPT, Grok Bot)

Add the remote MCP server as a custom connector and sign in with the user's
phone (OAuth). No API key is needed.

```
https://api.aitextaroo.com/mcp
```

- Claude / Claude Duet: Customize → Connectors → Add custom connector.
- ChatGPT: Plugins → + → Add custom MCP server → OAuth → Create as a plugin.
  On ChatGPT Pro, custom MCP servers are limited to read-only tools.
- Grok Bot: "Add a custom MCP server called AI Text-a-roo at https://api.aitextaroo.com/mcp".

## B. Agents that can run commands

1. Install the package (pipx keeps it isolated; it also handles PEP 668 on modern Linux):

   ```bash
   pipx install aitextaroo        # or: pip install --user aitextaroo
   ```

2. Ask the user for their mobile number in international format (for example +12125551234), then request a code:

   ```bash
   aitextaroo-setup --phone +12125551234
   ```

3. Ask the user for the 6-digit code they received (valid for 5 minutes), then confirm it and save the key:

   ```bash
   aitextaroo-setup --phone +12125551234 --code 123456 --save
   ```

   `--save` stores the API key in `~/.aitextaroo/credentials.json` with owner-only
   permissions, where `aitextaroo` and `aitextaroo-bridge` find it in later
   sessions. Without `--save`, store the printed key yourself (for example as
   `AITEXTAROO_API_KEY`); it can't be retrieved again. Confirming a code for a
   phone that already has an account issues a new key, and the old key stops working.

4. Tell the user their AI's number (`assigned_number`) and suggest saving it as a
   contact such as "My AI". Then send a test text:

   ```bash
   aitextaroo send "Hi! Save this number as My AI and text me anytime."
   ```

Everyday commands (JSON output):

```bash
aitextaroo send "Build finished: 318 tests passing."
aitextaroo ask "Deploy to production? Reply YES or NO" --timeout 120   # text, then wait for the answer
aitextaroo recent                                                       # texts from the last 5 minutes
aitextaroo relay --to +12125550100 --name Mom "Happy birthday!"        # Pro
aitextaroo verify-pin 4821
aitextaroo account
aitextaroo connect          # how to add the MCP server to Claude Code, Codex, Gemini CLI, Cursor…
```

No package install possible? The Agent Skill includes `scripts/textaroo.py`,
which needs only Python 3, and the REST API works with any HTTP client (see
[`skills/aitextaroo/references/api.md`](skills/aitextaroo/references/api.md)).

## C. Local CLI agents that should answer texts

The bridge keeps one outbound connection to AI Text-a-roo, turns each text the
user sends into a prompt for a local CLI agent, and texts back the answer. No
public IP or webhook is needed.

```bash
nohup aitextaroo-bridge > ~/aitextaroo.log 2>&1 &
```

- Supported agents: Claude Code, Codex, Hermes, OpenClaw, NanoClaw and Grok
  (`--agent claude|codex|hermes|openclaw|nanoclaw|grok`; default: the first one installed).
- History is kept locally in `~/.aitextaroo/sessions/`.
- SMS commands for the user: `/help`, `/new` (fresh conversation), `/status`.
- Check it's running: `pgrep -f aitextaroo-bridge`. Logs: `tail -20 ~/aitextaroo.log`.
- One stream per API key: a second bridge disconnects the first.
- The bridge runs the agent with its own permissions. Some CLIs (for example
  `hermes -z`) auto-approve tool calls in one-shot mode, and a text can't prove
  who sent it, so the bridge tells the agent to ask for the user's PIN before
  anything sensitive.

## D. Agents with an inbound webhook URL (for example, Grok Bot webhook routines)

```bash
aitextaroo webhook set https://example.com/hook --auth-header "Bearer <receiver token>"
```

Each text the user sends is POSTed as JSON
(`{"event": "message.inbound", "data": {"text": …, "channel": "sms", "trust_level": "low", "has_pin": …}, "timestamp": …}`)
with an `X-Signature` header (hex HMAC-SHA256 of the body, keyed with the secret
returned at registration) and, if set, the `Authorization` header.

## Good texts

Plain text, short, and say what reply you need. Before sensitive actions, ask
the user to text their PIN and check it (`aitextaroo verify-pin`, or the
`verify_pin` MCP tool). Never ask the user to text passwords or card numbers.

## Plans and limits

- Free: 10 messages a day. Pro: $5/month (14-day free trial), 200 a day, plus
  texting the user's contacts with replies forwarded to the user.
- Up to 5 texts per minute. Limits reset at midnight UTC.
