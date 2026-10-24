# Setting up AI Text-a-roo

This guide covers setting up AI Text-a-roo when a user has asked you to. Pick the path that matches your environment. Every path verifies the user's phone with a 6-digit code: that's the only step the user has to do.

## A. Apps with connector settings (Claude, Claude Duet, ChatGPT, Grok Bot)

The user adds a custom connector (an MCP server) and signs in with their phone. No API key is involved.

- Connector URL: `https://api.aitextaroo.com/mcp`
- Claude / Claude Duet: Customize → Connectors → Add custom connector → paste the URL → Connect.
- ChatGPT: Plugins → + → Add custom MCP server → paste the URL → OAuth → Create as a plugin. (On ChatGPT Pro, custom MCP servers are limited to read-only tools.)
- Grok Bot: ask it to "Add a custom MCP server called AI Text-a-roo at https://api.aitextaroo.com/mcp".

During sign-in the user enters their phone number and the code texted to it, then allows access. AI Text-a-roo then texts them that the app connected, so tell them to expect it. Once connected, send a short test text with `send_text`.

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
   - HTTP: `POST https://api.aitextaroo.com/v1/auth/confirm` with `{"phone": "+12125551234", "code": "123456", "label": "Claude on studio-mac"}`
   - `label` names the key on the dashboard and in the text the user gets: 1–40 letters, digits, spaces or `. _ ( ) ' @ # : + -`. `aitextaroo-setup` and the script take `--label`; by default they use "aitextaroo on <computer name>" and "aitextaroo skill on <computer name>".
   - The response contains `api_key`, `key_id`, `assigned_number`, `tier`, a `note` saying what changed, and `retired` (any key removed to stay at 10; usually none).
5. Store the API key somewhere you can read in future sessions (a secrets store, a config file only the user can read, or the `AITEXTAROO_API_KEY` environment variable). It's shown once and can't be retrieved later. Confirming a code for a phone that already has an account adds another key: the account's other keys, app sign-ins and forwarding keep working, and the user gets a text saying a key was added. An account holds up to 10 keys; adding an 11th removes the one unused the longest (never the one that forwards the user's texts), and the user is texted which.
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
- Only one stream per account: starting a second bridge, even with another key, stops the first one. A bridge also stops when its key is removed from the account, or when the API rejects its key (wrong, or removed while the bridge was off); it says to run `aitextaroo-setup --save` for a new one. Either way it exits cleanly instead of reconnecting, so two bridges don't keep kicking each other off and a dead key isn't retried forever.

### Keep it running after a restart

`nohup` stops when the computer restarts. To have the bridge start on its own, run it as a background service. Replace `claude` with your agent (the `--agent` value above). Both snippets record the bridge's full path and the current `PATH` when you run them, so the service can find your agent's command; run them from a shell where `claude` (or your agent) works. Each starts by checking the bridge is installed, and stops if it isn't (run `pipx ensurepath` and open a new shell, then try again).

The service restarts the bridge if it fails, but not after a clean stop (its key was removed or rejected, or another bridge took over); once that's sorted, start it again with the restart command below. A bridge stopped by another one starts again the next time its computer restarts or its user logs in, and then the other one stops. To move the bridge to another computer, turn it off on the old one: `systemctl --user disable --now aitextaroo-bridge` (Linux) or `launchctl bootout gui/$(id -u)/com.aitextaroo.bridge; rm ~/Library/LaunchAgents/com.aitextaroo.bridge.plist` (macOS).

Set up the service before aitextaroo 0.3.0? Its file says `Restart=always` (Linux) or `<key>KeepAlive</key><true/>` (macOS), which restarts the bridge even after a clean stop, so two bridges keep kicking each other off. Run the snippet for your system again; on Linux, then run `systemctl --user restart aitextaroo-bridge` (the macOS snippet restarts it for you).

Linux (systemd user service):

```bash
(  # a subshell: stops at the first error without closing your shell
set -e
BRIDGE=$(command -v aitextaroo-bridge) || { echo "aitextaroo-bridge not found on PATH"; exit 1; }
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/aitextaroo-bridge.service <<EOF
[Unit]
Description=AI Text-a-roo SMS bridge

[Service]
ExecStart=$BRIDGE --agent claude
WorkingDirectory=$HOME
Environment="PATH=$PATH"
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now aitextaroo-bridge
loginctl enable-linger "$USER"   # keep it running while logged out
)
```

If `loginctl enable-linger` fails (it can need a password, and an agent's shell can't type one), ask the user to run `sudo loginctl enable-linger $USER` in Terminal. Without it, the bridge runs only while they're logged in. Check it with `systemctl --user status aitextaroo-bridge`; logs: `journalctl --user -u aitextaroo-bridge -n 20`. Restart: `systemctl --user restart aitextaroo-bridge`.

macOS (launchd agent):

```bash
(  # a subshell: stops at the first error without closing your shell
set -e
BRIDGE=$(command -v aitextaroo-bridge) || { echo "aitextaroo-bridge not found on PATH"; exit 1; }
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.aitextaroo.bridge.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.aitextaroo.bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>$BRIDGE</string>
    <string>--agent</string>
    <string>claude</string>
  </array>
  <key>WorkingDirectory</key><string>$HOME</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$PATH</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$HOME/aitextaroo.log</string>
  <key>StandardErrorPath</key><string>$HOME/aitextaroo.log</string>
</dict>
</plist>
EOF
launchctl bootout gui/$(id -u)/com.aitextaroo.bridge 2>/dev/null || true   # unload any older copy first
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.aitextaroo.bridge.plist
)
```

Logs: `tail -20 ~/aitextaroo.log`. Restart: `launchctl kickstart -k gui/$(id -u)/com.aitextaroo.bridge`. Stop until the next login: `launchctl bootout gui/$(id -u)/com.aitextaroo.bridge`; to turn it off for good, also delete `~/Library/LaunchAgents/com.aitextaroo.bridge.plist`.

Then ask the user to text their AI Text-a-roo number and tell you whether the reply came back. Don't call `wait_for_reply` while testing: a waiting call takes the text before the bridge does.

## D. Agents with an inbound webhook URL

To receive the user's texts as HTTP POSTs (for example, to wake a Grok Bot webhook routine), register a webhook. A pending `wait_for_reply` still gets a text first, and a live bridge or `/stream` connection gets it too (see the delivery order in [api.md](api.md)). With the MCP server, call `set_webhook` with `url`, `auth_header` and, if the user has a PIN, `pin`. Over HTTP:

```
POST https://api.aitextaroo.com/v1/webhook
Authorization: Bearer <API key>
{"url": "https://example.com/hook", "auth_header": "Bearer <token the receiver expects>", "pin": "4821"}
```

Leave out `pin` if the user hasn't set one (`get_account` shows `has_pin`). The response includes a signing secret. Each delivery is a JSON body like `{"event": "message.inbound", "data": {"text": "…", "channel": "sms", "trust_level": "low", "has_pin": true}, "timestamp": 1761264000.0}` with an `X-Signature` header (hex HMAC-SHA256 of the body, keyed with the secret) and, if you set `auth_header`, an `Authorization` header with that value.

Forwarding is protected:

- Registering needs the user's PIN if they have one, and changing or removing the PIN needs the current PIN (only the user can skip that, by removing it on the dashboard), so an agent can't remove it first to get around this. Wrong PINs count toward the usual lockouts (3 per 5 minutes, 10 a day).
- Before forwarding starts, AI Text-a-roo texts the user where their texts will go: the host only (never the full URL), and which host it replaces. If that text can't be sent, nothing changes.
- The user can text `UNHOOK` to their AI Text-a-roo number anytime to stop forwarding. AI Text-a-roo handles it first, so it never reaches an agent or a contact.
- The user can also see where their texts go, and stop it, on the dashboard (aitextaroo.com/dashboard). Removing the key or app sign-in that set up forwarding (on the dashboard or with `remove_connection`) stops it too.
- Only public HTTPS URLs with plain-ASCII host names are accepted, and at most 5 webhook changes an hour and 10 a day.

Remove it with `DELETE /v1/webhook` or `remove_webhook`; the user is texted that forwarding is off.
