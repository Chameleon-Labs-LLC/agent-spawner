#!/usr/bin/env bash
# deploy.sh — ship a scaffolded agent zip to a remote Linux host over SCP/SSH.
#
# Usage:
#   deploy.sh [<ip-or-host>] <agent-dir> [options]
#
# Environment variables (used when flags are omitted):
#   SSH_HOST   Default host (same as the positional argument).
#   SSH_USER   Default remote user.
#   SSH_KEY    Default private-key path.
#   REMOTE_DIR Default remote parent dir (default: ~/agents).
#
# Options:
#   --user <name>      Remote SSH user. Default: $SSH_USER, else probe $USER, ubuntu, root.
#   --key <path>       Explicit private key. Default: $SSH_KEY, else discovery.
#   --remote-dir <p>   Remote parent dir. Default: $REMOTE_DIR or ~/agents
#   --setup            After copy: unzip, create .venv with uv, uv sync.
#   --enable-systemd   After --setup: install + enable systemd-user unit.
#   --dry-run          Print commands; don't execute.
#   -h | --help        Show this block.
#
# This script does NOT provision infrastructure. It assumes you already have
# a Linux host you can SSH into. It does NOT transport .env — populate secrets
# on the remote manually.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die()  { echo "[deploy] ERROR: $*" >&2; exit 1; }
log()  { echo "[deploy] $*" >&2; }
warn() { echo "[deploy] WARN: $*" >&2; }

usage() { sed -n '2,18p' "$0"; exit "${1:-0}"; }

# ---- parse args ----
host="${SSH_HOST:-}"
agent_dir=""
user="${SSH_USER:-}"
key="${SSH_KEY:-}"
remote_dir="${REMOTE_DIR:-~/agents}"
setup=0
enable_systemd=0
dry=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --user) user="$2"; shift 2 ;;
    --key) key="$2"; shift 2 ;;
    --remote-dir) remote_dir="$2"; shift 2 ;;
    --setup) setup=1; shift ;;
    --enable-systemd) enable_systemd=1; shift ;;
    --dry-run) dry=1; shift ;;
    -*) die "unknown option: $1" ;;
    *)
      # Positional: first fills agent_dir if host came from env, else host, then agent_dir.
      if   [[ -z "$host" ]];       then host="$1"
      elif [[ -z "$agent_dir" ]];  then agent_dir="$1"
      else die "unexpected positional: $1"
      fi
      shift
      ;;
  esac
done

[[ -n "$host" && -n "$agent_dir" ]] || usage 1
[[ -d "$agent_dir" ]] || die "not a directory: $agent_dir"

agent_dir="$(cd "$agent_dir" && pwd)"
agent_name="$(basename "$agent_dir")"

run() {
  if (( dry )); then
    echo "+ $*"
  else
    eval "$@"
  fi
}

# ---- ensure the zip exists ----
zip_path="$agent_dir/$agent_name.zip"
if [[ ! -f "$zip_path" ]]; then
  log "zip not found — running packager (always, even in dry-run)"
  packager="$SCRIPT_DIR/package_agent.py"
  [[ -f "$packager" ]] || die "packager missing: $packager"
  python3 "$packager" "$agent_dir"
fi
[[ -f "$zip_path" ]] || die "zip still missing after packaging: $zip_path"

# ---- candidate users ----
user_candidates=()
if [[ -n "$user" ]]; then
  user_candidates=("$user")
else
  [[ -n "${USER:-}" ]] && user_candidates+=("$USER")
  user_candidates+=("ubuntu" "root")
fi

# ---- candidate keys ----
key_candidates=()
if [[ -n "$key" ]]; then
  [[ -f "$key" ]] || die "key file not found: $key"
  key_candidates=("$key")
else
  # ssh-agent keys (via default identity-selection — no explicit -i)
  if [[ -n "${SSH_AUTH_SOCK:-}" ]] && ssh-add -L >/dev/null 2>&1; then
    key_candidates+=("__agent__")
  fi
  for k in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_ecdsa" "$HOME/.ssh/id_rsa"; do
    [[ -f "$k" ]] && key_candidates+=("$k")
  done
fi

[[ ${#key_candidates[@]} -gt 0 ]] || die "no SSH keys found. Pass --key or put one in ~/.ssh/."

# ---- probe connectivity ----
STRICT="${STRICT_HOST_KEY_CHECKING:-accept-new}"
chosen_user=""
chosen_key=""

for u in "${user_candidates[@]}"; do
  for k in "${key_candidates[@]}"; do
    if [[ "$k" == "__agent__" ]]; then
      ssh_cmd=(ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking="$STRICT" "$u@$host" true)
      label="(ssh-agent)"
    else
      ssh_cmd=(ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking="$STRICT" -o IdentitiesOnly=yes -i "$k" "$u@$host" true)
      label="$k"
    fi
    log "probing $u@$host with $label"
    if (( dry )) || "${ssh_cmd[@]}" 2>/dev/null; then
      chosen_user="$u"
      chosen_key="$k"
      break 2
    fi
  done
done

if [[ -z "$chosen_user" ]]; then
  echo "" >&2
  warn "no SSH key could authenticate to $host."
  warn "users tried: ${user_candidates[*]}"
  warn "keys tried:  ${key_candidates[*]}"
  echo "" >&2
  echo "To enroll your key on the remote:" >&2
  echo "  ssh-copy-id -i ~/.ssh/id_ed25519.pub <user>@$host" >&2
  echo "Or pass --key explicitly." >&2
  exit 2
fi

log "authenticated as $chosen_user@$host (key: $chosen_key)"

# ---- build ssh/scp argv ----
ssh_base=(-o StrictHostKeyChecking="$STRICT")
if [[ "$chosen_key" != "__agent__" ]]; then
  ssh_base+=(-o IdentitiesOnly=yes -i "$chosen_key")
fi

SSH()  { run "ssh ${ssh_base[*]} '$chosen_user@$host' $*"; }
SCP()  { run "scp ${ssh_base[*]} '$1' '$chosen_user@$host:$2'"; }

# ---- create remote dir ----
SSH "mkdir -p $remote_dir"

# ---- copy zip (scp, with SSH-tar fallback) ----
log "copying $zip_path → $chosen_user@$host:$remote_dir/"
if command -v scp >/dev/null 2>&1; then
  SCP "$zip_path" "$remote_dir/"
else
  warn "scp not found locally; falling back to SSH-tar"
  run "ssh ${ssh_base[*]} '$chosen_user@$host' 'mkdir -p $remote_dir && cat > $remote_dir/$agent_name.zip' < '$zip_path'"
fi

# ---- optional setup ----
if (( setup )); then
  log "remote setup: unzip + uv sync"
  SSH "set -e; \
    cd $remote_dir && unzip -o $agent_name.zip && cd $agent_name && \
    (command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh) && \
    export PATH=\"\$HOME/.local/bin:\$PATH\" && \
    uv sync && \
    [ -f .env ] || cp .env.example .env"
fi

# ---- optional systemd ----
if (( enable_systemd )); then
  (( setup )) || die "--enable-systemd requires --setup"
  log "installing systemd-user unit on remote"
  unit_name="${agent_name}.service"
  SSH "set -e; \
    mkdir -p ~/.config/systemd/user && \
    cp $remote_dir/$agent_name/autostart/systemd-user.service ~/.config/systemd/user/$unit_name && \
    systemctl --user daemon-reload && \
    systemctl --user enable --now $unit_name && \
    systemctl --user --no-pager status $unit_name | head -n 12 || true"
fi

log "done."
echo "" >&2
echo "Next steps:" >&2
echo "  ssh $chosen_user@$host" >&2
echo "  cd $remote_dir/$agent_name" >&2
echo "  # edit .env to fill in secrets" >&2
if (( enable_systemd )); then
  echo "  systemctl --user restart $agent_name" >&2
else
  echo "  python local/agent.py   # or enable systemd with --enable-systemd" >&2
fi
