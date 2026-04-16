# agent-spawner — task runner.
# Install `just`: https://just.systems/  (or `cargo install just`, `brew install just`, `apt install just`)
# Loads variables from .env at the repo root. `cp .env.example .env` and edit.

set dotenv-load := true
set shell := ["bash", "-euo", "pipefail", "-c"]

SKILL_DIR := justfile_directory() / ".claude-plugin/skills/agent-spawner"
SCRIPTS   := SKILL_DIR / "scripts"

# Default recipe: list everything.
default:
    @just --list

# --- setup ---

# Install system prerequisites (Ubuntu/Debian). Prompts for sudo.
bootstrap-ubuntu:
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv openssh-client unzip curl just
    @echo "Installing uv (user-local)..."
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
    @echo "Done. Open a new shell so ~/.local/bin is on PATH."

# Copy .env.example to .env so you can fill it in.
init:
    @[ -f .env ] || { cp .env.example .env && echo "created .env — edit it before running deploy/scaffold"; }
    @[ -f .env ] && echo ".env exists"

# Print the env vars the justfile sees (useful for debugging).
env-check:
    @echo "SSH_HOST=${SSH_HOST:-<unset>}"
    @echo "SSH_USER=${SSH_USER:-<unset>}"
    @echo "SSH_KEY=${SSH_KEY:-<unset>}"
    @echo "REMOTE_DIR=${REMOTE_DIR:-~/agents}"
    @echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+<set>}${ANTHROPIC_API_KEY:-<unset>}"

# --- scaffold / package ---

# Scaffold a new agent. Example:
#   just scaffold comms myapp local telegram "You are the comms agent."
scaffold name product type channels prompt output_dir="":
    #!/usr/bin/env bash
    set -euo pipefail
    out="{{output_dir}}"
    [[ -z "$out" ]] && out="$HOME/code/{{product}}/agents/{{name}}"
    python3 "{{SCRIPTS}}/scaffold_agent.py" \
        --name "{{name}}" \
        --product "{{product}}" \
        --type "{{type}}" \
        --channels "{{channels}}" \
        --system-prompt "{{prompt}}" \
        --output-dir "$out"
    echo ""
    echo "Agent scaffolded at: $out"

# Package an agent folder into a shippable zip.
package agent_dir:
    python3 "{{SCRIPTS}}/package_agent.py" "{{agent_dir}}"

# --- deploy ---

# Deploy an agent to the host in $SSH_HOST (or override with host=...).
# Example:
#   just deploy ~/code/myapp/agents/comms
#   just deploy ~/code/myapp/agents/comms host=1.2.3.4
deploy agent_dir host="":
    #!/usr/bin/env bash
    set -euo pipefail
    h="{{host}}"; [[ -z "$h" ]] && h="${SSH_HOST:-}"
    [[ -n "$h" ]] || { echo "set SSH_HOST in .env or pass host=<ip>"; exit 1; }
    bash "{{SCRIPTS}}/deploy.sh" "$h" "{{agent_dir}}"

# Deploy + run remote setup (unzip, uv sync, copy .env.example).
deploy-setup agent_dir host="":
    #!/usr/bin/env bash
    set -euo pipefail
    h="{{host}}"; [[ -z "$h" ]] && h="${SSH_HOST:-}"
    [[ -n "$h" ]] || { echo "set SSH_HOST in .env or pass host=<ip>"; exit 1; }
    bash "{{SCRIPTS}}/deploy.sh" "$h" "{{agent_dir}}" --setup

# Deploy + setup + enable the systemd-user unit on the remote.
deploy-full agent_dir host="":
    #!/usr/bin/env bash
    set -euo pipefail
    h="{{host}}"; [[ -z "$h" ]] && h="${SSH_HOST:-}"
    [[ -n "$h" ]] || { echo "set SSH_HOST in .env or pass host=<ip>"; exit 1; }
    bash "{{SCRIPTS}}/deploy.sh" "$h" "{{agent_dir}}" --setup --enable-systemd

# Show what deploy would do without executing.
deploy-dry agent_dir host="":
    #!/usr/bin/env bash
    set -euo pipefail
    h="{{host}}"; [[ -z "$h" ]] && h="${SSH_HOST:-}"
    [[ -n "$h" ]] || { echo "set SSH_HOST in .env or pass host=<ip>"; exit 1; }
    bash "{{SCRIPTS}}/deploy.sh" "$h" "{{agent_dir}}" --dry-run --setup --enable-systemd

# --- housekeeping ---

# End-to-end smoke test: scaffold a throwaway agent, package it, clean up.
smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    python3 "{{SCRIPTS}}/scaffold_agent.py" \
      --name demo --product smoke --type local --channels telegram \
      --system-prompt "smoke-test agent" \
      --output-dir "$tmp/demo" --force
    python3 "{{SCRIPTS}}/package_agent.py" "$tmp/demo"
    ls -la "$tmp/demo/demo.zip"
    rm -rf "$tmp"
    echo "OK"

# Check prerequisites are installed.
doctor:
    @echo -n "python3: "; command -v python3 || echo MISSING
    @echo -n "uv:      "; command -v uv      || echo MISSING
    @echo -n "ssh:     "; command -v ssh     || echo MISSING
    @echo -n "scp:     "; command -v scp     || echo MISSING
    @echo -n "unzip:   "; command -v unzip   || echo MISSING
    @echo -n "just:    "; command -v just    || echo MISSING
