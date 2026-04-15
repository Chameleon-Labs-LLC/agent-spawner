# agent-spawner

Scaffold, package, and deploy Claude agents — channel adapters (Telegram/Slack/Discord), local + managed + hybrid runtimes, HMAC-verified bridges, and one-command deploy to a Linux host over SSH.

Built as a Claude Code **skill**: when this repo is open in Claude Code, the agent at `.claude/skills/agent-spawner/` is auto-loaded and Claude knows how to drive it. You can also run everything by hand — see [Quickstart](#quickstart) below.

> **Target OS:** Linux (tested on Ubuntu 22.04+ and Debian 12). Windows Task Scheduler files are generated too, but the command-line tooling assumes a POSIX shell. On Windows, use WSL.

---

## What you get

Given one command, the spawner produces a folder like:

```
<agent-name>/
├── persona.json            # name, prompt, tools, voice
├── managed/definition.json # POST body for Anthropic's Managed Agents API
├── local/
│   ├── agent.py            # 8-stage message pipeline using the Agent SDK
│   └── bridge.py           # HMAC-signed call into the managed peer (hybrid)
├── channels/
│   ├── telegram.py / slack.py / discord_bot.py
│   ├── exfil.py            # outbound secret-pattern filter
│   └── audit.py            # per-agent JSONL audit log
├── ide/                    # JetBrains + VSCode run configs
├── autostart/
│   ├── systemd-user.service
│   └── windows-task.xml
├── .env.example            # every secret, documented
├── README.md               # per-agent setup
└── <agent-name>.zip        # ready to scp anywhere
```

Each agent ships with a four-ring security model — **allowlist → PIN → exfil guard → audit log** — plus an emergency kill phrase. The scaffolder refuses to generate an agent with empty security settings.

---

## Requirements

| Tool | Why | Install (Ubuntu/Debian) |
|---|---|---|
| Python 3.11+ | runs the scaffolder and agents | `sudo apt install python3 python3-venv` |
| [`uv`](https://github.com/astral-sh/uv) | fast Python dep manager (inside generated agents) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [`just`](https://just.systems/) | task runner for this repo | `cargo install just` · `brew install just` · or download from releases |
| `ssh`, `scp`, `unzip`, `curl` | deploy + remote setup | `sudo apt install openssh-client unzip curl` |

**Or run one command** to install everything on Ubuntu/Debian:

```bash
just bootstrap-ubuntu
```

(You'll still need to install `just` itself first — one-liner: `cargo install just`, `brew install just`, or grab a binary from https://github.com/casey/just/releases.)

---

## Quickstart

```bash
# 1. Clone and set up env
git clone https://github.com/<you>/agent-spawner.git
cd agent-spawner
just init                       # copies .env.example → .env
$EDITOR .env                    # fill in SSH_HOST / SSH_USER / SSH_KEY

# 2. Confirm prereqs
just doctor                     # reports which tools are missing

# 3. Scaffold an agent
just scaffold comms myapp local telegram "You are the comms agent."
# → creates ~/code/myapp/agents/comms/

# 4. Fill in its .env (Telegram bot token, allowed chat IDs, PIN…)
$EDITOR ~/code/myapp/agents/comms/.env

# 5. Run it locally
cd ~/code/myapp/agents/comms
uv sync
uv run python local/agent.py

# 6. Or deploy it to the host in $SSH_HOST
cd -
just deploy-full ~/code/myapp/agents/comms
```

---

## Configuring deploy (SSH env vars)

The deploy script reads its target from `.env` at the repo root. Create it once with `just init`, then edit the three variables:

```bash
SSH_HOST=203.0.113.7          # the host you want to deploy to
SSH_USER=ubuntu               # optional; defaults probe $USER / ubuntu / root
SSH_KEY=~/.ssh/id_ed25519     # optional; auto-discovered if unset
```

`just` auto-loads `.env` for every recipe (`set dotenv-load := true`). To verify:

```bash
just env-check
```

**Want to set the env vars in your shell too?** Add these lines to `~/.bashrc` or `~/.zshrc` (edit the values first):

```bash
export SSH_HOST=203.0.113.7
export SSH_USER=ubuntu
export SSH_KEY="$HOME/.ssh/id_ed25519"
```

Then `source ~/.bashrc`. Shell-level env vars override `.env`.

**No SSH key yet?** Make one:

```bash
ssh-keygen -t ed25519 -C "you@example.com"        # accept defaults
ssh-copy-id -i ~/.ssh/id_ed25519.pub $SSH_USER@$SSH_HOST
```

`ssh-copy-id` installs your pubkey into the remote's `~/.ssh/authorized_keys` so passwordless login works. After that, the deploy script's first connectivity probe will succeed.

---

## Available `just` recipes

```text
just                 # list everything
just doctor          # check prerequisites
just bootstrap-ubuntu  # one-shot install on apt-based distros
just init            # create .env from template
just env-check       # print the env vars the justfile sees

just scaffold NAME PRODUCT TYPE CHANNELS "PROMPT" [OUTPUT_DIR]
  #   example: just scaffold comms myapp local telegram "You are the comms agent."

just package AGENT_DIR      # build the shippable .zip
just smoke                  # end-to-end sanity test (no remote needed)

just deploy AGENT_DIR [host=IP]        # copy zip to $SSH_HOST
just deploy-setup AGENT_DIR [host=IP]  # + unzip + uv sync on remote
just deploy-full  AGENT_DIR [host=IP]  # + enable systemd-user service
just deploy-dry   AGENT_DIR [host=IP]  # show what would happen
```

Any recipe that takes `host=...` also works with `SSH_HOST` from `.env`; the CLI arg wins when both are set.

---

## How the deploy works

1. **Discovers a key.** Tries `SSH_KEY` / `--key`, then `ssh-agent` keys, then `~/.ssh/id_ed25519` → `id_ecdsa` → `id_rsa`. First one that authenticates wins.
2. **Probes connectivity** with `ssh -o BatchMode=yes` so a bad key fails fast instead of prompting for a password.
3. **Copies the zip** with `scp` (falls back to SSH-tar if `scp` is unavailable on the remote).
4. `--setup` → unzips, installs `uv`, runs `uv sync`, seeds `.env` from `.env.example`.
5. `--enable-systemd` → drops the `systemd-user.service` unit and `systemctl --user enable --now`s it.

The script **never transports `.env`**. Secrets live on the remote only, populated manually after the first deploy. Re-running a deploy preserves the remote's `.env`.

See [`.claude/skills/agent-spawner/references/deploy.md`](./.claude/skills/agent-spawner/references/deploy.md) for the full deploy reference including troubleshooting.

---

## Security model (per-agent)

Every generated channel adapter enforces, in order:

1. **Allowlist** — numeric chat/user IDs in env vars like `TELEGRAM_ALLOWED_CHAT_IDS`. Unknown senders are dropped silently.
2. **PIN lock** — first message in a session must be `/unlock <PIN>`. Idle auto-lock after 30 minutes.
3. **Exfil guard** — outbound messages are scanned for `sk-ant-…`, Slack tokens, Telegram tokens, the agent's own HMAC secret, and any `EXFIL_DENY_PATTERNS` regexes. Matches become `[REDACTED — exfil guard]`.
4. **Audit log** — `~/.agents/audit/<name>.jsonl`, metadata only unless `AUDIT_LOG_CONTENT=1`.

Plus a **kill phrase** (env var `AGENT_KILL_PHRASE`, default `"emergency stop"`) that works from anyone, locks all sessions, drops queued messages.

For hybrid agents, the local→managed call is HMAC-SHA256-signed with a shared secret generated at scaffold time.

---

## Using as a Claude Code skill

Open the repo in [Claude Code](https://claude.com/claude-code). The skill at `.claude/skills/agent-spawner/` loads automatically. Say:

> "Create a local agent named `ops` for my project `myapp`, Telegram channel, that triages incoming pager alerts."

Claude will elicit missing bits, run the scaffolder, show you the tree, and list which secrets you need to fill in.

---

## Layout of this repo

```
agent-spawner/
├── .claude/skills/agent-spawner/   # the skill itself
│   ├── SKILL.md                    # instructions loaded by Claude
│   ├── references/                 # architecture, channels, deploy, etc.
│   ├── scripts/                    # scaffold_agent.py, package_agent.py, deploy.sh
│   └── templates/                  # Jinja-like templates filled in by the scaffolder
├── justfile                        # task runner entrypoint
├── .env.example                    # repo-level env template
├── LICENSE
└── README.md                       # this file
```

---

## License

MIT — see [LICENSE](./LICENSE).

## Contributing

Issues and PRs welcome. When adding a new channel or runtime mode, update:
- the relevant reference in `.claude/skills/agent-spawner/references/`
- the template(s) in `.claude/skills/agent-spawner/templates/`
- the scaffolder's validation in `scripts/scaffold_agent.py`
- this README if it changes the public CLI surface
