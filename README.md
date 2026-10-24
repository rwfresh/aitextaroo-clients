# AI Text-a-roo

Give any AI agent a phone number, in about two minutes.

[AI Text-a-roo](https://aitextaroo.com) is an SMS gateway for AI agents. You verify your
phone once; then you can text your agent from any phone (no app), and it can text you back,
or first, when something needs you. This repo has everything an agent needs to use it: an
[Agent Skill](skills/aitextaroo/SKILL.md), plugin manifests for Claude, Codex, Cursor and
Gemini CLI, the `aitextaroo` command, a Python SDK, and an SMS bridge for CLI agents.

## Install in your agent

| Agent | One step |
|---|---|
| Claude Code | `claude plugin install aitextaroo --marketplace rwfresh/aitextaroo-clients`, or in a session `/plugin marketplace add rwfresh/aitextaroo-clients` then `/plugin install aitextaroo@aitextaroo` |
| Claude, Claude Desktop, Claude Duet | Customize → Plugins → Add marketplace → `rwfresh/aitextaroo-clients`, or Customize → Connectors → Add custom connector → `https://api.aitextaroo.com/mcp` |
| ChatGPT and Dots | Plugins → + → Add custom MCP server → `https://api.aitextaroo.com/mcp` → OAuth |
| Codex | `codex plugin marketplace add rwfresh/aitextaroo-clients`, then `codex plugin add aitextaroo@aitextaroo` |
| Gemini CLI | `gemini extensions install https://github.com/rwfresh/aitextaroo-clients` |
| Grok Bot | Say: "Add a custom MCP server called AI Text-a-roo at https://api.aitextaroo.com/mcp" |
| Cursor | Add the MCP server to `~/.cursor/mcp.json` (run `aitextaroo connect cursor`) |
| Any skills-aware agent | `npx skills add rwfresh/aitextaroo-clients` |
| Claude Code, Codex, Hermes, OpenClaw, Grok, Gemini, Antigravity, Goose, Cursor (answer texts from your phone) | `pipx install aitextaroo`, then `aitextaroo-bridge` |

The plugins bundle the skill and the remote MCP server. They sign in with OAuth: you enter
your phone number and the 6-digit code we text you, so there's no API key to copy. Setup
guides for each agent: <https://aitextaroo.com/agents>.

Or just tell your agent:

> Set me up with AI Text-a-roo so I can text you. Instructions: aitextaroo.com/llms.txt

## Quick start from a terminal

```bash
pipx install aitextaroo                                      # or: pip install --user aitextaroo
aitextaroo-setup --phone +12125551234                        # texts you a 6-digit code
aitextaroo-setup --phone +12125551234 --code 123456 --save   # saves the key (owner-only)
aitextaroo send "Hello from my agent!"
```

`--save` stores the API key in `~/.aitextaroo/credentials.json` with owner-only permissions.
`aitextaroo` and `aitextaroo-bridge` find it there, or in `AITEXTAROO_API_KEY`, or in `--api-key`.

## The `aitextaroo` command

Made for agents with a shell. Output is JSON; errors go to stderr with exit code 1.
`aitextaroo verify-pin` exits 2 when the PIN is wrong, so `aitextaroo verify-pin <<< 4821 && …`
only continues on a match. `verify-pin` and `set-pin` read the PIN from stdin when it isn't
an argument. At a terminal they ask for it without echoing, which keeps it out of your shell
history (a command with the PIN written in it, like the `<<<` form, can still be saved there).

```bash
aitextaroo send "Build finished: 318 tests passing."
aitextaroo ask "Deploy to production? Reply YES or NO" --timeout 120   # text, then wait for the answer
aitextaroo wait --timeout 60                                            # wait for the next text
aitextaroo recent                                                       # texts from the last 5 minutes
aitextaroo relay --to +12125550100 --name Mom "Happy birthday!"        # Pro: text a contact
aitextaroo verify-pin                                                   # check a PIN (hidden prompt)
aitextaroo set-pin                                                      # set the user's PIN (4-8 digits)
aitextaroo account
aitextaroo upgrade                                                      # Stripe link for Pro
aitextaroo webhook set https://example.com/hook --auth-header "Bearer <token>" --pin   # --pin if a PIN is set
aitextaroo connect [claude-code|codex|gemini|cursor|muse-code|claude|chatgpt|grok]
```

## SMS bridge

The bridge holds one outbound connection to AI Text-a-roo. Each text you send becomes a
prompt for a CLI agent on your machine, and its answer is texted back. No webhook, no public
IP: it works behind NAT, firewalls and VPNs.

```bash
aitextaroo-bridge                       # auto-detects an installed agent
aitextaroo-bridge --agent codex
aitextaroo-bridge --agent-command "pnpm --silent --dir ~/nanoclaw run chat"   # any other CLI
```

| `--agent` | Runs |
|---|---|
| `claude` | `claude -p "<prompt>"` |
| `codex` | `codex exec --skip-git-repo-check --color never -o <file> "<prompt>"` |
| `hermes` | `hermes -z "<prompt>"` |
| `openclaw` | `openclaw agent exec "<prompt>"` |
| `grok` | `grok --no-auto-update -p "<prompt>"` |
| `gemini` | `gemini -p "<prompt>"` |
| `antigravity` | `agy -p "<prompt>"` |
| `goose` | `goose run -q --no-session -t "<prompt>"` |
| `cursor` | `cursor-agent -p --trust "<prompt>"`, or `agent` if that's all there is (explicit only: Grok Build also installs an `agent` binary, and the bridge refuses it) |

Auto-detect tries them in this order. `--agent-command` runs any CLI that takes the prompt
as its last argument and prints the reply.

Conversation history is saved locally in `~/.aitextaroo/sessions/` and survives restarts.
Text `/help`, `/new` (fresh conversation) or `/status`. Use `--no-persist` for memory-only
history. Responses are stripped of markdown for SMS.

```text
aitextaroo-bridge [OPTIONS]
  --api-key KEY          API key (default: AITEXTAROO_API_KEY or the saved credentials)
  --agent NAME           auto, claude, codex, hermes, openclaw, grok, gemini, antigravity, goose, cursor
  --agent-command CMD    Any other CLI agent (overrides --agent)
  --sessions-dir PATH    Session files (default ~/.aitextaroo/sessions/)
  --no-persist           Keep history in memory only
  --base-url URL         Custom API URL
  -v, --verbose          Debug logging
```

## Python SDK

```python
import asyncio
from aitextaroo import TextarooClient

async def main():
    client = TextarooClient(api_key="YOUR_KEY")
    await client.send("All tests pass. Open a PR? Reply YES or NO.")
    reply = await client.wait_for_reply(timeout_seconds=90)
    print(reply.text if reply else "No answer yet")
    await client.close()

asyncio.run(main())
```

| Method | What it does |
|---|---|
| `send(text)` | Text the user. Returns the message ID. |
| `wait_for_reply(timeout_seconds=60)` | Wait up to 120 s for the user's next text (or one that arrived since your last send). Returns an `InboundMessage` or `None`. |
| `recent_messages(after_id=None)` | Texts from the last five minutes. |
| `listen()` | Async iterator over inbound texts via SSE, with automatic reconnect and replay. |
| `text_contact(to, text, recipient_name=None)` | Pro: text someone else; their replies go to the user's phone. |
| `verify_pin(pin)` | Check a PIN the user texted: `{"verified": bool, "attempts_remaining": int \| None}`. |
| `set_pin(pin)` / `remove_pin()` | Set, change or remove the user's security PIN (4–8 digits). |
| `set_webhook(url, auth_header=None, pin=None)` / `remove_webhook()` | Forward inbound texts to a URL (signed with `X-Signature`). `pin` is required if the user has one; the user is texted where their texts go and can reply `UNHOOK` to stop it. |
| `account()` | Plan, assigned number, usage and daily limit. |
| `upgrade_link()` | Stripe checkout link for Pro. |
| `TextarooClient.request_verification(phone)` / `confirm_verification(phone, code)` | Sign-up, no key needed. |

`InboundMessage` has `id`, `text`, `received_at`, `channel` (`"sms"`), `trust_level` and
`has_pin`. See [`examples/`](examples/) for an echo bot, a listener and an ask-and-wait flow.

## MCP server

`https://api.aitextaroo.com/mcp` (streamable HTTP). Tools: `send_text`, `wait_for_reply`,
`get_recent_messages`, `text_contact`, `verify_pin`, `get_account`, `get_upgrade_link`,
`set_webhook`, `remove_webhook`, and `get_help` (how it works and how it's secured, for
answering the user's questions). Clients sign in with OAuth, or send
`Authorization: Bearer <API key>`:

```bash
claude mcp add --transport http --scope user aitextaroo https://api.aitextaroo.com/mcp \
  --header "Authorization: Bearer $AITEXTAROO_API_KEY"
```

Run `aitextaroo connect` for every client's exact setup. Reference: <https://aitextaroo.com/docs/mcp>.

## Plans

| | Free ($0) | Pro ($5/mo, 14-day free trial) |
|---|---|---|
| Messages per day | 10 | 200 |
| Two-way texting, MCP, skill, SDK, bridge | ✓ | ✓ |
| Security PIN | ✓ | ✓ |
| Text your contacts, with replies forwarded | | ✓ |

Up to 5 texts per minute. Limits reset at midnight UTC.

## Privacy and security

- Message content is never written to AI Text-a-roo's database. Texts are held in memory
  for at most five minutes so an agent can catch up after a dropped connection.
- Phone numbers are encrypted at rest; PINs are stored as bcrypt hashes.
- The bridge's history and the saved credentials live only on your machine.
- SMS isn't end-to-end encrypted, and sender IDs can be spoofed. The bridge tells every agent
  to ask for your PIN before anything sensitive, because some CLIs (for example `hermes -z`)
  auto-approve their own tool calls in one-shot mode. Run the bridge with an agent whose
  permissions you're comfortable exposing to your phone number.

Details: <https://aitextaroo.com/security>.

## Environment variables

| Variable | Description |
|---|---|
| `AITEXTAROO_API_KEY` | API key (alternative to `--api-key` and the saved credentials) |
| `AITEXTAROO_BASE_URL` | Custom API URL |

## Releasing

Bump the version in `pyproject.toml`, `aitextaroo/__init__.py`, `plugin.json`,
`.claude-plugin/plugin.json` and `gemini-extension.json`, merge to `main`, then push a
matching tag: `git tag v0.2.2 && git push origin v0.2.2`. The
[Release workflow](.github/workflows/release.yml) tests, builds and publishes to PyPI with
Trusted Publishing.

## License

MIT
