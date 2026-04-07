# AI Text-a-roo — Agent Setup Guide

**You are an AI agent.** Your user wants to text you. Follow these steps
to give yourself a phone number. The whole process takes about 2 minutes.

## What you're setting up

AI Text-a-roo gives you a real phone number. Your user texts that number,
you receive the message, you reply, they get your reply as a text. No app
to install, no account to create — it's just SMS.

## Prerequisites

- You can run shell commands (terminal access)
- Python 3.10+ is available
- Your user is present (they need to receive a verification code on their phone)

## Step 1 — Install

```bash
pip install aitextaroo
```

## Step 2 — Verify your user's phone number

Ask your user: "What's your phone number? I need it in international format,
like +12125551234."

Then send the verification code:

```bash
aitextaroo-setup --phone +12125551234
```

Output: `Verification code sent to +12125551234`

Tell your user: "I just sent a verification code to your phone.
What's the 6-digit code?"

## Step 3 — Get your API key

Once they give you the code:

```bash
aitextaroo-setup --phone +12125551234 --code 123456
```

Output:
```
Setup complete!

  Assigned number: +18085550402
  Tier:            free

  API Key: abc123...

  IMPORTANT: Save this API key now. It cannot be retrieved again.
```

**Save the API key** to your environment or config file:

```bash
echo 'AITEXTAROO_API_KEY=abc123...' >> ~/.env
```

## Step 4 — Start the bridge

```bash
aitextaroo-bridge --api-key abc123...
```

Or if you saved it to the environment:

```bash
AITEXTAROO_API_KEY=abc123... aitextaroo-bridge
```

The bridge auto-detects which agent you are and starts listening.

Tell your user: "You're all set! Text +18085550402 to reach me."

## Keeping it running

The bridge needs to stay running for you to receive texts.

**Background:**
```bash
nohup aitextaroo-bridge > ~/aitextaroo.log 2>&1 &
```

**Systemd service (Linux):**
```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/aitextaroo.service << 'EOF'
[Unit]
Description=AI Text-a-roo Bridge
After=network.target

[Service]
Environment=AITEXTAROO_API_KEY=your_key_here
ExecStart=aitextaroo-bridge
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now aitextaroo
```

## SMS Commands

Your user can text these commands:

| Command   | What it does                          |
|-----------|---------------------------------------|
| `/help`   | List available commands               |
| `/new`    | Start a fresh conversation            |
| `/status` | Show agent name, uptime, message count|

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "rate_limit_exceeded" | Wait 60 seconds between verification attempts |
| Bridge exits immediately | Check API key is correct. Run with `-v` for verbose logs |
| No response to texts | Make sure bridge is running. User must text from the verified phone |
| "Agent timed out" | Agent took >120s to respond. Check your agent process |

## Quick reference

```
Install:     pip install aitextaroo
Setup:       aitextaroo-setup --phone PHONE
Confirm:     aitextaroo-setup --phone PHONE --code CODE
Run:         aitextaroo-bridge --api-key KEY
Env var:     AITEXTAROO_API_KEY
Commands:    /help  /new  /status
Docs:        https://aitextaroo.com
Source:      https://github.com/rwfresh/aitextaroo-clients
```
