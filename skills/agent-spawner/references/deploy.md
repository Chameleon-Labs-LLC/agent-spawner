# Deploy reference — SCP/SSH to a remote Linux host

The scaffolder produces a zip. `scripts/deploy.sh` ships it to an existing Linux host you already have SSH access to. **It does not provision infrastructure** — no VPS creation, no cloud API calls, no DNS. Bring your own box.

## Usage

```bash
scripts/deploy.sh <ip-or-host> <agent-dir> [options]
```

Required:
- `<ip-or-host>` — IPv4/IPv6 address or a resolvable hostname (e.g. `203.0.113.7`, `agent.example.com`, an `/etc/hosts` alias, or a Tailscale/Nebula/NordVPN Meshnet hostname).
- `<agent-dir>` — path to the scaffolded agent folder. The script looks for `<agent-name>.zip` inside it, running the packager if needed.

Options:
- `--user <name>` — remote SSH user. Default: `$USER`, then `ubuntu`, then `root` (tried in order during connectivity probe).
- `--key <path>` — explicit private key path. If omitted, key discovery runs (see below).
- `--remote-dir <path>` — where to place the unpacked agent on the remote host. Default: `~/agents`.
- `--setup` — after copying, run `unzip`, create `.venv` with `uv`, and install deps on the remote.
- `--enable-systemd` — after `--setup`, copy `autostart/systemd-user.service` to `~/.config/systemd/user/` and `systemctl --user enable --now` it.
- `--dry-run` — print every command without executing.

## SSH key discovery

The deploy script looks for a key in this order and stops at the first that successfully authenticates against `<user>@<host>`:

1. `--key <path>` if provided (no fallback if it fails — exit with an error)
2. Keys loaded in `ssh-agent` (`ssh-add -L`), if the agent is running
3. `~/.ssh/id_ed25519`
4. `~/.ssh/id_ecdsa`
5. `~/.ssh/id_rsa`
6. `~/.ssh/id_dsa` (last resort; warn)

For each candidate, the script runs:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    -i <candidate> <user>@<host> true
```

`BatchMode=yes` prevents password prompts — if a key can't authenticate, it fails fast instead of hanging. `accept-new` auto-trusts a first-time host (trade-off: convenience over strict-TOFU). Override with `STRICT_HOST_KEY_CHECKING=yes` in the environment if you want the old behavior.

If all keys fail, the script exits with instructions:

```
No SSH key could authenticate to <user>@<host>.
Tried: <list>
To enroll an existing key on the remote:
  ssh-copy-id -i ~/.ssh/id_ed25519.pub <user>@<host>
Or pass --key explicitly.
```

## SCP vs SSH-tar

The default transport is `scp`. On modern OpenSSH (≥ 9.0), `scp` uses the SFTP protocol under the hood, so there's no reason to prefer `rsync` for a one-shot zip copy.

If `scp` is unavailable on either end (rare), the script falls back to:

```bash
ssh <user>@<host> "mkdir -p <remote-dir> && cat > <remote-dir>/<name>.zip" < <local-zip>
```

## What gets copied

Only the zip produced by `package_agent.py`. That excludes `.env`, `.venv`, `__pycache__`, `.git`, `.idea`, `.vscode`, and any `*.pyc`. The user **must populate `.env` on the remote host manually** — the script does not transport secrets.

## Post-deploy checklist (`--setup`)

When `--setup` is passed, the script runs on the remote:

```bash
cd <remote-dir> \
  && unzip -o <name>.zip \
  && cd <name> \
  && (command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh) \
  && uv sync \
  && [ -f .env ] || cp .env.example .env
```

It does **not** start the agent. The user must fill in `.env`, then either `python local/agent.py` or `--enable-systemd`.

## Idempotency

Re-running `deploy.sh` against the same host overwrites the zip and re-runs `uv sync`. It will **not** overwrite an existing `.env` on the remote. That's intentional — secrets on the remote should survive redeploys.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Permission denied (publickey)` | Remote user's `~/.ssh/authorized_keys` doesn't contain your pubkey. Run `ssh-copy-id`. |
| `Host key verification failed` | First-time host, and `STRICT_HOST_KEY_CHECKING=yes` is set. Run `ssh-keyscan <host> >> ~/.ssh/known_hosts` or accept on first connect. |
| `scp: command not found` on remote | OpenSSH server is present but client/scp isn't. The script falls back to SSH-tar automatically. |
| `uv: command not found` after `--setup` | `uv` install step failed (usually no `curl` on the remote). `apt install curl` or install uv manually. |
| Systemd unit doesn't start | `EnvironmentFile` points at a `.env` that doesn't exist yet. Fill in `.env` first, then `systemctl --user restart`. |
