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
   `AITEXTAROO_API_KEY`); it can't be retrieved again. Each confirmation adds a
   key, named "aitextaroo on <computer name>" unless you pass `--label`. If the
   phone already has an account, nothing else is signed out: its other keys,
   connected apps (including OAuth connectors like Grok or Claude) and forwarding
   keep working. An account holds up to 10 keys: adding an 11th removes the one
   unused the longest (never the one that forwards the user's texts), and the
   user is texted which. The user gets a text saying a key was added, so tell
   them to expect it.

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
aitextaroo verify-pin             # asks for the PIN without echoing; exits 2 if wrong
aitextaroo account
aitextaroo connections            # keys and app sign-ins on the account; "current" is you
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

- Supported agents: Claude Code, Codex, Hermes, OpenClaw, Grok, Gemini CLI,
  Antigravity CLI, Goose and Cursor CLI
  (`--agent claude|codex|hermes|openclaw|grok|gemini|antigravity|goose|cursor`;
  default: the first one installed; Cursor only when chosen with `--agent cursor`).
- NanoClaw, or any CLI that takes the prompt as its last argument and prints
  the reply: `--agent-command "pnpm --silent --dir ~/nanoclaw run chat"`.
- History is kept locally in `~/.aitextaroo/sessions/`.
- SMS commands for the user: `/help`, `/new` (fresh conversation), `/status`.
- Check it's running: `pgrep -f aitextaroo-bridge`. Logs: `tail -20 ~/aitextaroo.log`.
- One stream per account: a second bridge, even with another key, stops the
  first. A bridge also stops when its key is removed from the account, or when
  the API rejects its key (wrong, or removed while the bridge was off). Either
  way it says why and exits cleanly (code 0) instead of reconnecting.
- The bridge runs the agent with its own permissions. Some CLIs (for example
  `hermes -z`) auto-approve tool calls in one-shot mode, and a text can't prove
  who sent it, so the bridge tells the agent to ask for the user's PIN before
  anything sensitive.

## D. Agents with an inbound webhook URL (for example, Grok Bot webhook routines)

The user's texts reach an agent only while it's waiting for a reply, or through a
webhook or the bridge (a pending wait still gets a text first). Agents that run only
on demand, like a Grok Bot routine, need a webhook so the user can text them anytime.
With the MCP server, call `set_webhook`. With a shell:

```bash
aitextaroo webhook set https://example.com/hook --auth-header "Bearer <receiver token>"
```

If the user has a PIN (`aitextaroo account` shows `has_pin`), add `--pin`: it reads
the PIN from stdin or a hidden prompt. Each text the user sends is POSTed as JSON
(`{"event": "message.inbound", "data": {"text": …, "channel": "sms", "trust_level": "low", "has_pin": …}, "timestamp": …}`)
with an `X-Signature` header (hex HMAC-SHA256 of the body, keyed with the secret
returned at registration) and, if set, the `Authorization` header.

Forwarding is protected: the PIN is required if the user has one, AI Text-a-roo
texts the user the destination host before forwarding starts (if that text can't
be sent, nothing changes), the user can text `UNHOOK` anytime to stop it, and
webhook changes are limited to 5 an hour. `aitextaroo webhook remove` (or the
`remove_webhook` tool) stops forwarding and texts the user. The user can also
stop it on the dashboard (https://aitextaroo.com/dashboard), and removing the key
or app sign-in that set it up stops it too.

## Good texts

Plain text, short, and say what reply you need. Before sensitive actions, ask
the user to text their PIN and check it (`aitextaroo verify-pin`, which reads
the PIN from stdin and exits 2 when it's wrong, or the `verify_pin` MCP tool).
No PIN yet? Ask the user to pick 4–8 digits and run `aitextaroo set-pin` (or the
`set_pin` MCP tool); never choose it for them. Changing or removing a PIN needs the
current one (`set-pin --current`, `remove-pin`), and the user is texted before any
change. The PIN is the only secret to ask for by text: never ask for passwords or
card numbers.

## Connected apps and keys

The user gets a text whenever a key is added or an app signs in. To see what's
connected, run `aitextaroo connections` (or call the `list_connections` MCP
tool): each key and app sign-in has a label and when it was last used, and
`current` is you. To disconnect one when the user asks ("disconnect my old
laptop"), confirm which one with them first, then run
`aitextaroo disconnect <id>`, adding `--pin` if they have a PIN (it reads the PIN
from stdin or a hidden prompt), or call `remove_connection`. It stops working
right away, forwarding it set up stops too, and the user is texted. "Sign out
everything" is only on the dashboard, https://aitextaroo.com/dashboard, where the
user can also stop forwarding and set or remove their PIN.

## When the user wants to text you anytime

Follow the "When the user wants to text you anytime" section of the
[Agent Skill](skills/aitextaroo/SKILL.md) (or the MCP `get_help` topic
`text_anytime`). In short: agents with webhook routines (Grok Bot) register the
routine with `set_webhook`; agents on the user's computer run the bridge as a
background service ([setup reference](skills/aitextaroo/references/setup.md),
section C); chat-only assistants say honestly that they can't receive surprise
texts yet. Use plain words with the user and finish with a live test text.

## Plans and limits

- Free: 10 messages a day. Pro: $5/month (14-day free trial), 200 a day, plus
  texting the user's contacts with replies forwarded to the user.
- What counts: texts you send (to the user or their contacts), contacts' replies
  forwarded to the user, and the user's `>` replies to them. The user's own texts
  to you don't count. One contact's replies are forwarded at most 20 an hour and
  50 a day.
- Up to 5 texts per minute. Limits reset at midnight UTC.
