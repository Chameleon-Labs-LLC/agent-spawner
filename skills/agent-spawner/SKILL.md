---
name: agent-spawner
description: Scaffolds a complete Claude agent — Claude Managed Agents in the cloud, local Agent SDK agents on Linux/Windows, HMAC-signed bridges between them, channel adapters (Telegram/Slack/Discord) with allowlist + PIN security, IDE run configurations for JetBrains and VSCode, and autostart units for systemd and Windows Task Scheduler. Use this skill whenever the user asks to "create an agent", "scaffold a managed agent", "set up a local agent that talks to a managed one", "add a channel-based bot", or wants a deployable agent bundle. Also includes scripts to deploy the bundle to a remote Linux host over SCP/SSH.
---

# agent-spawner

Scaffolds a complete Claude agent — persona, managed/local runtime, verified channel adapters, IDE configs, autostart units, a deployable zip, and an optional SSH/SCP deploy step to a remote Linux host.

**Primary target OS: Linux.** Windows is generated too (the scaffolder emits a Task Scheduler XML), but defaults, docs, and the deploy path assume Linux.

## What this skill produces

Given a single command from the user ("create an ops agent named comms, hybrid, Telegram + Slack channels"), this skill produces an agent folder containing:

```
<agent-name>/
├── persona.json                 # spec card (name, voice, system prompt, tools)
├── managed/
│   └── definition.json          # POST body for Managed Agents API
├── local/
│   ├── agent.py                 # Agent SDK runtime
│   └── bridge.py                # HMAC-verified caller into the managed agent (hybrid only)
├── channels/
│   ├── telegram.py              # bot with chat-ID allowlist + PIN lock
│   ├── slack.py                 # (if requested)
│   └── discord_bot.py           # (if requested)
├── ide/
│   ├── jetbrains-external-tool.xml
│   ├── jetbrains-run-config.xml
│   └── vscode-tasks.json
├── autostart/
│   ├── systemd-user.service     # ~/.config/systemd/user/  (primary)
│   └── windows-task.xml         # schtasks /Create /XML … (secondary)
├── .env.example                 # all secrets, none committed
├── README.md                    # human-readable setup
└── <agent-name>.zip             # everything above, ready to ship
```

## Workflow

### 1. Elicit the spec

If the user hasn't supplied them, ask for (one short batched message):

- **Agent name** — snake_case (e.g. `comms`, `ops`, `intake`)
- **Product / namespace** — free-form string used for folder grouping and the Python package name (e.g. `myapp`, `acme`, `side-project`)
- **Type** — `managed` (cloud, customer-facing), `local` (runs on a dev machine or server), or `hybrid` (local agent that delegates to a managed peer)
- **Channels** — any of `telegram`, `slack`, `discord`, or `none` (backend-only)
- **System prompt / role** — one or two sentences
- **MCP servers** — optional list of HTTPS MCP URLs (managed agents require HTTP, STDIO is not supported — see `references/managed-vs-local.md`)

For **hybrid**, also confirm: which managed agent does the local one delegate to? (name + base URL of the managed agent's session endpoint)

### 2. Read the relevant references

Before generating files, read whichever apply:

- `references/architecture.md` — the layered agent stack. Read once per session.
- `references/managed-vs-local.md` — when to pick each, the HMAC bridge protocol, the `managed-agents-2026-04-01` beta header, MCP constraints. Read for any `managed` or `hybrid` agent.
- `references/channels.md` — the four-ring security model (allowlist → PIN → exfil guard → audit), per-channel quirks. Read for any agent with channels.
- `references/ide-integration.md` — JetBrains External Tools format, VSCode tasks schema. Read when generating IDE configs.
- `references/deploy.md` — how the SCP/SSH deploy scripts work, SSH key discovery, what to verify on the remote host.

### 3. Run the scaffolder

```bash
python scripts/scaffold_agent.py \
  --name <name> \
  --product <namespace> \
  --type <managed|local|hybrid> \
  --channels <comma-separated or 'none'> \
  --system-prompt "<one or two sentences>" \
  --mcp-servers "<comma-separated URLs or empty>" \
  --delegate-to <managed-agent-name> \   # hybrid only
  --delegate-url <https://...> \         # hybrid only
  --output-dir <absolute path>
```

Default `--output-dir`: `~/code/<product>/agents/<name>` on Linux. On Windows the scaffolder accepts forward slashes and normalizes. If the user is in a Claude Code session with a clear repo root, infer from the working directory.

The scaffolder fills templates from `templates/`, generates an HMAC secret for the bridge, writes `.env.example` with every required key, and creates the README.

### 4. Verify and explain

After scaffolding, show the user a tree of what was created and call out:

1. **Secrets to fill in** in `.env` — list them by name (e.g. `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `BRIDGE_HMAC_SECRET`).
2. **The verification handshake** — for hybrid agents, point out that the HMAC secret must match on both ends.
3. **How to launch** — in IDE (import the XML configs) or via `python local/agent.py` / systemd-user.

### 5. Package the zip

```bash
python scripts/package_agent.py <output-dir>
```

Bundles everything except `.env`, `.venv`, and cache directories. Produces `<agent-name>.zip` in the agent folder.

### 6. (Optional) Deploy to a remote Linux host

```bash
scripts/deploy.sh <ip-or-host> <agent-dir> [--user ubuntu] [--key ~/.ssh/id_ed25519]
```

The script:

1. **Discovers an SSH key** — the `--key` the user provided, keys loaded in `ssh-agent`, or `~/.ssh/id_ed25519` / `id_ecdsa` / `id_rsa` in order.
2. **Tests connectivity** — runs `ssh -o BatchMode=yes <user>@<host> true` with each candidate until one works. If all fail, reports the list and suggests `ssh-copy-id`.
3. **Copies the zip** — `scp` the packaged `<agent-name>.zip` into `~/agents/` on the remote host (falls back to SSH-tar if scp is unavailable).
4. **Optional `--setup`** — unzips, creates a venv with `uv`, installs deps. Does not start the agent.
5. **Optional `--enable-systemd`** — installs and enables the systemd-user unit.

This skill does **not** provision VPSs, create cloud accounts, or manage DNS. It only deploys to an existing Linux host you already have SSH access to. See `references/deploy.md`.

## Defaults

When the user doesn't specify, assume:

- **OS** — Linux (systemd-user autostart, `~/code/<product>/agents/<name>` layout). Generate Windows Task Scheduler XML too, because cross-platform costs nothing.
- **Python** — 3.11+ with `uv` for dependency management (`pyproject.toml`, not `requirements.txt`).
- **MCP transport** — HTTP/SSE, never STDIO (required for managed agents; keeping local consistent makes hybrid easier).
- **Telegram** as the default channel when the user says "channels yes" but doesn't pick one — lowest setup friction.

## What this skill explicitly does NOT do

- **Does not provision infrastructure.** No VPS creation, no cloud API calls, no DNS. It deploys to a host you already control via SSH.
- **Does not invent a JetBrains plugin.** Real integration today is via External Tools + Run Configurations.
- **Does not enable voice / war-room layers.** Out of scope.
- **Does not store secrets in generated files.** Everything sensitive goes to `.env`, which is gitignored automatically.

## When to push back

- **Managed agent + STDIO MCP** → explain the constraint. Offer to (a) host the MCP server publicly or (b) make the agent local.
- **Channel with empty allowlist** → refuse. Ring 1 of the security model is non-negotiable.
- **Deploy to an unknown host without a working SSH key** → stop, report which keys were tried, and suggest `ssh-copy-id <user>@<host>` before retrying. Do not silently prompt for passwords.
