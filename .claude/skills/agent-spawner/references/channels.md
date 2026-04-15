# Channel adapters — the four-ring security model

Every channel adapter the scaffolder generates implements all four rings, in order. **Skipping any ring is not optional** — the scaffolder refuses to generate an agent with an empty allowlist or no PIN.

## Ring 1 — Allowlist (the guest list)

Per-channel identifier check. If sender ID isn't on the list, drop the message silently (don't even acknowledge — that leaks existence).

| Channel | Identifier | Env var |
|---|---|---|
| Telegram | numeric chat ID | `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated) |
| Slack | user ID (`U…`) | `SLACK_ALLOWED_USER_IDS` |
| Discord | user ID (snowflake) | `DISCORD_ALLOWED_USER_IDS` |

To find your Telegram chat ID: message `@userinfobot`. Slack: profile → "Copy member ID". Discord: enable Developer Mode → right-click user → "Copy User ID".

## Ring 2 — PIN lock

First message in a session must be `/unlock <PIN>`. The PIN lives in `AGENT_PIN` (env var, 6+ digits). Sessions auto-lock after 30 minutes of inactivity.

The PIN is **per-agent**, not per-channel — the same PIN unlocks the agent regardless of which channel the user is on.

## Ring 3 — Exfil guard

Every outbound message is scanned for patterns that look like leaked secrets before sending:

- `sk-ant-[a-zA-Z0-9_-]{32,}` (Anthropic keys)
- `xoxb-[a-zA-Z0-9-]{10,}` (Slack bot tokens)
- `xapp-[a-zA-Z0-9-]{10,}` (Slack app tokens)
- `[0-9]{8,10}:[a-zA-Z0-9_-]{35}` (Telegram bot tokens)
- The agent's own `BRIDGE_HMAC_SECRET`
- Custom patterns from `EXFIL_DENY_PATTERNS` (env var, comma-separated regexes)

Matches are replaced with `[REDACTED — exfil guard]` and an audit log entry is written.

## Ring 4 — Audit log

Every inbound message and outbound reply is appended to `~/.agents/audit/<agent-name>.jsonl` (override with `AUDIT_DIR`):

```
{"ts": "...", "direction": "in|out", "channel": "telegram", "user": "<id>", "len": 234, "redacted": false}
```

**Content is not logged by default** — only metadata. Set `AUDIT_LOG_CONTENT=1` to log full content (useful for debugging, dangerous for privacy).

## Kill phrase

Any inbound message exactly matching `AGENT_KILL_PHRASE` (env var, default `"emergency stop"`) immediately:
1. Locks the agent (forces re-PIN)
2. Sends a single ACK
3. Drops all queued messages
4. Writes a `KILLED` audit entry

Checked **before** the allowlist — a message from an unknown sender that happens to contain the kill phrase still triggers it. Defense-in-depth tradeoff: slight info leak, large safety win.

## Channel-specific notes

### Telegram
- Long polling, not webhooks, unless you've set up a public HTTPS endpoint
- BotFather privacy mode should be disabled in groups (agents are 1:1 by default)

### Slack
- Socket Mode (no public URL needed) — requires `SLACK_APP_TOKEN` (`xapp-`) in addition to the bot token
- Bot must be added to the channel/DM explicitly

### Discord
- For staging vs prod, use **separate servers** (not just separate channels) — misconfigured bots can't leak between environments
- Bot needs `MESSAGE CONTENT INTENT` enabled in the developer portal
