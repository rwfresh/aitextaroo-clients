# AI Text-a-roo

Give any AI agent a phone number. In 60 seconds.

```
pip install aitextaroo
```

## What is this?

[AI Text-a-roo](https://aitextaroo.com) is an SMS gateway for AI agents. You sign up, get a phone number, and your agent can send and receive text messages.

This library connects your agent to the gateway. No webhook, no public IP, no server setup — just one outbound HTTPS connection.

## Setup

### Let your agent do it

Tell your agent:

> Go to aitextaroo.com and set up SMS for me.

Your agent will find the setup instructions and handle everything.

### Or use the CLI

```bash
# 1. Install
pip install aitextaroo

# 2. Verify your phone (sends a 6-digit code)
aitextaroo-setup --phone +12125551234

# 3. Enter the code, get your API key
aitextaroo-setup --phone +12125551234 --code 123456

# 4. Start the bridge
aitextaroo-bridge --api-key YOUR_KEY
```

The bridge auto-detects your AI agent and starts piping SMS through it.

Supported agents: `claude` (Claude Code), `hermes`, `openclaw`, `nanoclaw`.

## How it works

```
Your phone                AI Text-a-roo              Your machine
    │                         │                          │
    ├── SMS "hey" ──────────► │                          │
    │                         ├── SSE stream ──────────► │
    │                         │                          ├── Agent processes
    │                         │   POST /v1/send ◄────────┤   the message
    │  ◄── SMS "hello!" ──────┤                          │
    │                         │                          │
```

1. User texts your assigned number
2. AI Text-a-roo pushes the message via SSE (Server-Sent Events)
3. Your agent processes it and replies via `client.send()`
4. The reply is delivered as SMS

No polling. No webhooks. No public IP. Works behind NAT, firewalls, VPNs.

## Features

### Conversation history

The bridge keeps conversation context in memory so your agent can have
coherent multi-turn conversations over SMS. History is local — nothing
is stored on our servers.

### SMS formatting

Agent responses are automatically cleaned for SMS — markdown bold,
italic, code blocks, and headers are stripped to plain text.

### SMS commands

Your user can text these commands:

| Command   | What it does                           |
|-----------|----------------------------------------|
| `/help`   | List available commands                |
| `/new`    | Start a fresh conversation             |
| `/status` | Show agent name, uptime, message count |

## Python API

### TextarooClient

```python
import asyncio
from aitextaroo import TextarooClient

async def main():
    client = TextarooClient(api_key="your-key")

    async for message in client.listen():
        print(f"Got: {message.text}")
        await client.send(f"You said: {message.text}")

asyncio.run(main())
```

#### `listen(auto_reconnect=True)` → `AsyncIterator[InboundMessage]`

Opens an SSE stream and yields messages as they arrive. Handles reconnection automatically.

#### `send(text)` → `str`

Send an SMS to the registered user. Returns the message ID.

#### `account()` → `dict`

Get account info (tier, assigned number, usage).

#### `close()`

Release resources.

### Signup API (static methods)

```python
# Send verification code
await TextarooClient.request_verification(phone="+12125551234")

# Confirm and get API key
result = await TextarooClient.confirm_verification(phone="+12125551234", code="123456")
print(result["api_key"])
print(result["assigned_number"])
```

### InboundMessage

| Field         | Type   | Description              |
|---------------|--------|--------------------------|
| `id`          | `str`  | Unique message ID (UUID) |
| `text`        | `str`  | Message body             |
| `received_at` | `str`  | ISO 8601 timestamp       |
| `channel`     | `str`  | Always `"sms"`           |
| `has_pin`     | `bool` | Whether sender has a PIN |

## Privacy

- Messages pass through and disappear — nothing is stored on our servers
- Conversation history lives in your bridge process memory only
- When the bridge stops, history is gone
- Your phone number is hashed and encrypted at rest

## Environment Variables

| Variable              | Description                              |
|-----------------------|------------------------------------------|
| `AITEXTAROO_API_KEY`  | Your API key (alternative to `--api-key`) |
| `AITEXTAROO_BASE_URL` | Custom API URL (for self-hosted)          |

## License

MIT
