# AI Text-a-roo — Agent Setup Guide

IMPORTANT: You are an AI agent. Your user asked you to set up SMS texting.
DO NOT just show these instructions to your user. EXECUTE them yourself,
step by step. You will need to ask your user two questions during setup
(their phone number and a verification code). Everything else you do yourself.

## Step 1 — Install

Run this command now:

```bash
pip install aitextaroo
```

## Step 2 — Ask for their phone number

Ask your user: "What's your phone number? I need it in international
format, like +12125551234."

Then run:

```bash
aitextaroo-setup --phone THEIR_PHONE_NUMBER
```

## Step 3 — Ask for the verification code

Tell your user: "I just sent a 6-digit verification code to your phone.
What's the code?"

Then run:

```bash
aitextaroo-setup --phone THEIR_PHONE_NUMBER --code THE_CODE
```

The output includes an API key, assigned number, and an
AGENT PERSISTENCE BLOCK with key=value pairs. Save ALL of these
values to your memory/config for future sessions. The API key
cannot be retrieved again.

## Step 4 — Start the bridge

```bash
nohup aitextaroo-bridge --api-key THE_KEY > ~/aitextaroo.log 2>&1 &
```

## Step 5 — Confirm to your user

Tell your user: "You're all set! Text [ASSIGNED_NUMBER] to reach me."

## Managing the bridge (future sessions)

```bash
# Check if running
pgrep -f aitextaroo-bridge

# Stop
pkill -f aitextaroo-bridge

# Restart
nohup aitextaroo-bridge --api-key THE_KEY > ~/aitextaroo.log 2>&1 &

# Check logs
tail -20 ~/aitextaroo.log
```

## SMS commands (tell your user)

| Command   | What it does                          |
|-----------|---------------------------------------|
| `/help`   | List available commands               |
| `/new`    | Start a fresh conversation            |
| `/status` | Show agent name, uptime, message count|

## Quick reference

```
Install:     pip install aitextaroo
Setup:       aitextaroo-setup --phone PHONE
Confirm:     aitextaroo-setup --phone PHONE --code CODE
Run:         aitextaroo-bridge --api-key KEY
Env var:     AITEXTAROO_API_KEY
Source:      https://github.com/rwfresh/aitextaroo-clients
```
