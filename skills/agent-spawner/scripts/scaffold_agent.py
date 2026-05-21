#!/usr/bin/env python3
"""
scaffold_agent.py — generate a complete Chameleon Labs agent.

Reads templates from ../templates/ (relative to this script), substitutes
variables, generates secrets, writes everything to --output-dir.

Usage:
  scaffold_agent.py \
    --name comms \
    --product realtyshield \
    --type hybrid \
    --channels telegram,slack \
    --system-prompt "You are Comms, RealtyShield's outbound communications agent." \
    --mcp-servers https://mcp.example.com/sse \
    --delegate-to managed_comms \
    --delegate-url https://agents.chameleonlabs.ai/v1/agents/agt_abc \
    --output-dir D:/Documents/Code/GitHub/realtyshield/agents/comms
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from pathlib import Path

VALID_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
VALID_PRODUCT = re.compile(r"^[a-z][a-z0-9_\-]{0,30}$")  # free-form namespace
VALID_TYPE = {"managed", "local", "hybrid", "orchestrator"}
VALID_CHANNEL = {"telegram", "slack", "discord"}

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


# ---------- helpers ----------

def render(tmpl_name: str, **vars) -> str:
    text = (TEMPLATE_DIR / tmpl_name).read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    leftover = re.search(r"\{\{[a-z_]+\}\}", text)
    if leftover:
        raise ValueError(f"unfilled placeholder {leftover.group()} in {tmpl_name}")
    return text


def write(path: Path, content: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)
    print(f"  + {path.relative_to(path.anchor) if path.is_absolute() else path}")


def channel_env_block(channels: list[str]) -> str:
    parts = []
    if "telegram" in channels:
        parts.append(
            "# Telegram\n"
            "TELEGRAM_BOT_TOKEN=\n"
            "TELEGRAM_ALLOWED_CHAT_IDS=     # comma-separated numeric IDs from @userinfobot\n"
        )
    if "slack" in channels:
        parts.append(
            "# Slack (Socket Mode)\n"
            "SLACK_BOT_TOKEN=xoxb-...\n"
            "SLACK_APP_TOKEN=xapp-...\n"
            "SLACK_ALLOWED_USER_IDS=        # comma-separated U... IDs\n"
        )
    if "discord" in channels:
        parts.append(
            "# Discord\n"
            "DISCORD_BOT_TOKEN=\n"
            "DISCORD_ALLOWED_USER_IDS=      # comma-separated snowflake IDs\n"
        )
    return "\n".join(parts) if parts else "# (no channels configured)\n"


def channel_deps(channels: list[str]) -> str:
    deps = []
    if "telegram" in channels:
        deps.append('  "python-telegram-bot>=21.0",')
    if "slack" in channels:
        deps.append('  "slack-bolt>=1.20.0",')
    if "discord" in channels:
        deps.append('  "discord.py>=2.4.0",')
    return "\n".join(deps)


def required_env_keys_md(type_: str, channels: list[str]) -> str:
    rows = ["- `ANTHROPIC_API_KEY`"]
    if channels:
        rows.append("- `AGENT_PIN` (already populated in `.env`)")
    if type_ == "hybrid":
        rows.append("- `BRIDGE_HMAC_SECRET` (already populated; **must match your verifier proxy** — see references/managed-vs-local.md → Hybrid gotcha)")
        rows.append("- `DELEGATE_URL` (your verifier proxy URL, NOT api.anthropic.com)")
        rows.append("- `AGENT_ID` (fill in after step 2b)")
        rows.append("- `ENVIRONMENT_ID` (fill in after step 2a)")
    if type_ == "managed":
        rows.append("- `AGENT_ID` (fill in after step 2b)")
        rows.append("- `ENVIRONMENT_ID` (fill in after step 2a)")
    if type_ == "orchestrator":
        rows.append("- `AGENT_ID` (fill in after step 2b)")
        rows.append("- `ENVIRONMENT_ID` (fill in after step 2a)")
        rows.append("- `BRIDGE_HMAC_SECRET` (already populated; **must match every Worker**)")
        rows.append("- `WORKER_BASE_URL` (orchestrator dispatches `agent.custom_tool_use` events here)")
    if "telegram" in channels:
        rows += ["- `TELEGRAM_BOT_TOKEN`", "- `TELEGRAM_ALLOWED_CHAT_IDS`"]
    if "slack" in channels:
        rows += ["- `SLACK_BOT_TOKEN`", "- `SLACK_APP_TOKEN`", "- `SLACK_ALLOWED_USER_IDS`"]
    if "discord" in channels:
        rows += ["- `DISCORD_BOT_TOKEN`", "- `DISCORD_ALLOWED_USER_IDS`"]
    return "\n".join(rows)


def channel_setup_md(channels: list[str]) -> str:
    blocks = []
    if "telegram" in channels:
        blocks.append(
            "**Telegram:** create a bot via @BotFather, paste the token into `.env`. "
            "Message `@userinfobot` to get your chat ID and add it to `TELEGRAM_ALLOWED_CHAT_IDS`."
        )
    if "slack" in channels:
        blocks.append(
            "**Slack:** at api.slack.com/apps create an app, enable Socket Mode, generate an app-level token "
            "(`xapp-`), install the bot to your workspace, copy the bot token (`xoxb-`)."
        )
    if "discord" in channels:
        blocks.append(
            "**Discord:** at discord.com/developers create an app, add a bot, enable **Message Content Intent**, "
            "invite to your **staging** server (not a channel — separate server, per the team convention)."
        )
    return "\n\n".join(blocks) if blocks else "_No channels configured. This agent is callable from code only._"


def managed_setup_block(type_: str, name: str, product: str) -> str:
    if type_ == "local":
        return ""
    blocks = [
        "### 2a. Create an Environment (once per workspace)\n\n"
        "```bash\n"
        "curl -sS -X POST https://api.anthropic.com/v1/environments \\\n"
        "  -H \"x-api-key: $ANTHROPIC_API_KEY\" \\\n"
        "  -H \"anthropic-version: 2023-06-01\" \\\n"
        "  -H \"anthropic-beta: managed-agents-2026-04-01\" \\\n"
        "  -H \"Content-Type: application/json\" \\\n"
        f"  -d '{{\"name\":\"{product}-{name}-env\",\"config\":{{\"type\":\"cloud\"}}}}'\n"
        "```\n\n"
        "Capture the `id` and set `ENVIRONMENT_ID=` in `.env`.\n\n"
        "### 2b. Register the agent\n\n"
        "```bash\n"
        "curl -sS -X POST https://api.anthropic.com/v1/agents \\\n"
        "  -H \"x-api-key: $ANTHROPIC_API_KEY\" \\\n"
        "  -H \"anthropic-version: 2023-06-01\" \\\n"
        "  -H \"anthropic-beta: managed-agents-2026-04-01\" \\\n"
        "  -H \"Content-Type: application/json\" \\\n"
        "  -d @managed/definition.json\n"
        "```\n\n"
        "Capture the `id` (and `version`) and set `AGENT_ID=` in `.env`. "
        "To change the agent's behavior later, POST to `/v1/agents/{id}` — each update creates a new version, "
        "and existing sessions keep their pinned version.\n"
    ]
    if type_ == "orchestrator":
        blocks.append(
            "\n### 2c. Deploy Workers to each host\n\n"
            "Each remote host runs `worker/worker.py`. Workers need:\n\n"
            "- The same `BRIDGE_HMAC_SECRET` as the orchestrator (lift from a secrets manager)\n"
            "- A unique `WORKER_HOST_ID` (e.g. the EC2 instance ID from IMDSv2)\n"
            "- Open inbound HTTPS on `WORKER_PORT` (default 8080) reachable from the orchestrator\n\n"
            "Sample launch:\n\n"
            "```bash\n"
            "export BRIDGE_HMAC_SECRET=$(aws ssm get-parameter --name /your/bridge-secret \\\n"
            "  --with-decryption --query Parameter.Value --output text)\n"
            "export WORKER_HOST_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)\n"
            "python worker/worker.py\n"
            "```\n\n"
            "Add custom tools by extending `TOOL_REGISTRY` in `worker/worker.py`.\n"
        )
    return "".join(blocks)


def bridge_block(type_: str, delegate_to: str, delegate_url: str) -> str:
    if type_ == "hybrid":
        return (
            f"\n### Hybrid bridge\n\n"
            f"This local agent delegates to the managed agent **{delegate_to}** via your verifier "
            f"proxy at `{delegate_url}`. Calls are signed with HMAC-SHA256 (timestamp + nonce + "
            f"body hash) using `BRIDGE_HMAC_SECRET`. **Anthropic does not verify HMAC headers** — "
            f"if `DELEGATE_URL` points at api.anthropic.com directly, the bridge headers are "
            f"decorative. For real protection, run a small verifier (Lambda Function URL, API "
            f"Gateway) that owns the secret and forwards to Anthropic with your API key. See "
            f"`references/managed-vs-local.md` → Hybrid gotcha. If you find yourself building "
            f"that verifier, you probably want `--type orchestrator`.\n"
        )
    if type_ == "orchestrator":
        return (
            f"\n### Orchestrator → Worker bridge\n\n"
            f"The orchestrator (`orchestrator/orchestrator.py`) holds the SSE stream with the "
            f"managed agent. When the agent emits an `agent.custom_tool_use` event, the "
            f"orchestrator HMAC-signs the request and POSTs to `${{WORKER_BASE_URL}}/execute`. "
            f"Each Worker (`worker/worker.py`) verifies the signature, runs the tool, and "
            f"returns JSON. Both sides read `BRIDGE_HMAC_SECRET` from the environment — keep them "
            f"in sync via a secrets manager. See `references/orchestrator-pattern.md` and "
            f"`references/auth-and-identity.md` for the user-identity-passthrough patterns.\n"
        )
    return ""


def channel_files_md(channels: list[str]) -> str:
    rows = []
    if "telegram" in channels:
        rows.append("│   ├── telegram.py")
    if "slack" in channels:
        rows.append("│   ├── slack.py")
    if "discord" in channels:
        rows.append("│   └── discord_bot.py")
    return "\n".join(rows)


def run_block(type_: str) -> str:
    if type_ == "orchestrator":
        return (
            "**Orchestrator** (your client, holds the SSE stream with the managed agent):\n\n"
            "```bash\n"
            "python orchestrator/orchestrator.py \"What's the status of host i-0abc...?\"\n"
            "```\n\n"
            "**Worker** (deploy to each host you want to dispatch to):\n\n"
            "```bash\n"
            "python worker/worker.py    # listens on $WORKER_PORT (default 8080)\n"
            "```\n\n"
            "Extend `TOOL_REGISTRY` in `worker/worker.py` to add new dispatchable operations. "
            "Declare matching custom-tool entries in `managed/definition.json` under `tools[]`, then "
            "re-`POST /v1/agents/{id}` to bump the agent version.\n"
        )
    if type_ == "managed":
        return (
            "This is a definition-only scaffold — you write the client elsewhere "
            "(Lambda, web server, CLI). See `managed/definition.json` for the agent config "
            "and `references/orchestrator-pattern.md` for the recommended client shape.\n"
        )
    if type_ == "hybrid":
        return (
            "```bash\n"
            "python local/agent.py\n"
            "```\n\n"
            "When the local agent needs to escalate, it calls `local/bridge.py` → your verifier "
            "proxy → managed twin. In another terminal, message the bot via your channel and "
            "start with `/unlock <PIN>` (the PIN is in your `.env`).\n"
        )
    return (
        "```bash\n"
        "python local/agent.py\n"
        "```\n\n"
        "In another terminal, message the bot via your channel and start with `/unlock <PIN>` "
        "(the PIN is in your `.env`).\n"
    )


def files_tree(type_: str, name: str, channel_files: str) -> str:
    if type_ == "orchestrator":
        return (
            "```\n"
            f"{name}/\n"
            "├── persona.json                    # spec card — name, prompt, tools, voice\n"
            "├── pyproject.toml                  # uv-managed deps\n"
            "├── .env.example                   # placeholders; committed\n"
            "├── .env                            # real secrets; gitignored\n"
            "├── managed/\n"
            "│   └── definition.json             # POST body for /v1/agents\n"
            "├── orchestrator/\n"
            "│   ├── orchestrator.py             # SSE-stream client + custom-tool dispatcher\n"
            "│   └── bridge.py                   # HMAC signing primitive\n"
            "├── worker/\n"
            "│   └── worker.py                   # FastAPI HMAC-verified tool runner (deploy per host)\n"
            "├── ide/\n"
            "│   ├── jetbrains-external-tool.xml\n"
            "│   ├── jetbrains-run-config.xml\n"
            "│   └── vscode-tasks.json\n"
            "├── autostart/\n"
            "│   ├── systemd-user.service        # Linux (primary)\n"
            "│   └── windows-task.xml            # Windows (secondary)\n"
            "└── README.md (this file)\n"
            "```\n"
        )
    if type_ == "managed":
        return (
            "```\n"
            f"{name}/\n"
            "├── persona.json\n"
            "├── pyproject.toml\n"
            "├── .env.example                   # placeholders; committed\n"
            "├── .env                            # real secrets; gitignored\n"
            "├── managed/\n"
            "│   └── definition.json             # POST body for /v1/agents\n"
            "├── ide/\n"
            "├── autostart/\n"
            "└── README.md (this file)\n"
            "```\n"
        )
    lines = [
        "```",
        f"{name}/",
        "├── persona.json                    # spec card — name, prompt, tools, voice",
        "├── pyproject.toml                  # uv-managed deps",
        "├── .env.example                   # placeholders; committed",
        "├── .env                            # real secrets; gitignored",
    ]
    if type_ in ("local", "hybrid"):
        lines += [
            "├── local/",
            "│   ├── agent.py                    # 8-stage pipeline runtime",
        ]
        if type_ == "hybrid":
            lines.append("│   └── bridge.py                   # HMAC-signed call to your verifier proxy")
    if type_ == "hybrid":
        lines += [
            "├── managed/",
            "│   └── definition.json             # POST body for /v1/agents",
        ]
    if channel_files:
        lines += [
            "├── channels/",
            "│   ├── exfil.py                    # ring 3",
            "│   ├── audit.py                    # ring 4",
            channel_files,
        ]
    lines += [
        "├── ide/",
        "├── autostart/",
        "└── README.md (this file)",
        "```",
    ]
    return "\n".join(lines) + "\n"


def managed_env_block(type_: str) -> str:
    if type_ in ("managed", "hybrid"):
        return (
            "# --- Managed agent (fill in after creating an environment + agent) ---\n"
            "# See README.md step 2a/2b for the curl commands.\n"
            "AGENT_ID=\n"
            "ENVIRONMENT_ID=\n"
        )
    if type_ == "orchestrator":
        return (
            "# --- Managed agent (fill in after creating an environment + agent) ---\n"
            "# See README.md step 2a/2b for the curl commands.\n"
            "AGENT_ID=\n"
            "ENVIRONMENT_ID=\n"
            "\n"
            "# --- Orchestrator -> Worker dispatch ---\n"
            "# Base URL of your Worker fleet. The orchestrator POSTs custom-tool calls to\n"
            "# ${WORKER_BASE_URL}/execute, signed with BRIDGE_HMAC_SECRET.\n"
            "WORKER_BASE_URL=\n"
            "\n"
            "# --- Worker-only (set per host; not used by the orchestrator) ---\n"
            "# WORKER_HOST_ID=i-0abc...        # IMDSv2 instance ID or similar\n"
            "# WORKER_PORT=8080\n"
        )
    return "# (no managed agent or bridge env vars for this type)\n"


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--product", required=True, help="free-form namespace, e.g. 'myapp'")
    ap.add_argument("--type", required=True, choices=sorted(VALID_TYPE))
    ap.add_argument("--channels", required=True, help="comma-separated or 'none'")
    ap.add_argument("--system-prompt", required=True)
    ap.add_argument("--mcp-servers", default="", help="comma-separated HTTPS URLs (managed agents require HTTP, not STDIO)")
    ap.add_argument("--delegate-to", default="", help="hybrid only: name of managed peer")
    ap.add_argument("--delegate-url", default="", help="hybrid only: base URL of managed peer's session API")
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--force", action="store_true", help="overwrite if output dir exists")
    args = ap.parse_args()

    # ---- validate ----
    if not VALID_NAME.match(args.name):
        sys.exit(f"--name must match {VALID_NAME.pattern}")
    if not VALID_PRODUCT.match(args.product):
        sys.exit(f"--product must match {VALID_PRODUCT.pattern}")
    channels = [] if args.channels == "none" else [c.strip() for c in args.channels.split(",") if c.strip()]
    bad = set(channels) - VALID_CHANNEL
    if bad:
        sys.exit(f"unknown channels: {bad}")
    mcp_urls = [u.strip() for u in args.mcp_servers.split(",") if u.strip()]
    if args.type in ("managed", "hybrid"):
        for u in mcp_urls:
            if not u.startswith("https://"):
                sys.exit(f"managed/hybrid agents require HTTPS MCP URLs; got {u!r}. "
                         f"See references/managed-vs-local.md.")
    if args.type == "hybrid" and not (args.delegate_to and args.delegate_url):
        sys.exit("--delegate-to and --delegate-url are required for hybrid agents")
    if args.type == "orchestrator" and args.channels:
        # Orchestrators are headless services driven by code (a Lambda, a web backend);
        # the channel-PIN model doesn't fit. Channels live on local/hybrid types.
        print("warning: --channels is ignored for --type orchestrator", file=sys.stderr)
        channels = []

    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()) and not args.force:
        sys.exit(f"{out} already exists and is non-empty. Use --force to overwrite.")
    out.mkdir(parents=True, exist_ok=True)

    # ---- generate secrets ----
    hmac_secret = secrets.token_hex(32)
    pin = "".join(secrets.choice("0123456789") for _ in range(8))

    # ---- common vars ----
    # Linux-primary: default to "bin". User can edit the generated files for Windows.
    venv_bin = "bin"
    mcp_servers_json = json.dumps(
        [{"type": "url", "url": u, "name": u.split("/")[-2] if "/" in u else "mcp"} for u in mcp_urls],
        indent=2,
    )
    channels_json = json.dumps(channels)
    delegate_json = json.dumps(
        {"to": args.delegate_to, "url": args.delegate_url} if args.type == "hybrid" else None
    )

    common = dict(
        name=args.name,
        product=args.product,
        type=args.type,
        system_prompt=args.system_prompt.replace('"', '\\"'),
        system_prompt_short=args.system_prompt[:80].replace('"', '\\"'),
        mcp_servers_json=mcp_servers_json,
        channels_json=channels_json,
        channels_human=", ".join(channels) if channels else "none (callable from code only)",
        delegate_json=delegate_json,
        delegate_to=args.delegate_to or "",
        delegate_url=args.delegate_url or "",
        venv_bin=venv_bin,
        generated_hmac=hmac_secret,
        generated_pin=pin,
        channel_env_block=channel_env_block(channels),
        channel_deps=channel_deps(channels),
        required_env_keys_md=required_env_keys_md(args.type, channels),
        channel_setup_md=channel_setup_md(channels),
        managed_setup_block=managed_setup_block(args.type, args.name, args.product),
        bridge_block=bridge_block(args.type, args.delegate_to, args.delegate_url),
        channel_files_md=channel_files_md(channels),
        managed_env_block=managed_env_block(args.type),
        run_block=run_block(args.type),
        files_tree=files_tree(args.type, args.name, channel_files_md(channels)),
    )

    print(f"\nScaffolding {args.name} → {out}\n")

    # ---- root ----
    write(out / "persona.json", render("persona.json.tmpl", **common))
    write(out / "pyproject.toml", render("pyproject.toml.tmpl", **common))
    env_example = render("env.example.tmpl", **common)
    write(out / ".env.example", env_example)
    # Also write a real .env (gitignored) with the generated secrets pre-populated,
    # so users can run immediately without having to copy + paste the secrets.
    env_real = env_example.replace("BRIDGE_HMAC_SECRET=", f"BRIDGE_HMAC_SECRET={hmac_secret}", 1)
    env_real = env_real.replace("AGENT_PIN=", f"AGENT_PIN={pin}", 1)
    write(out / ".env", env_real)
    write(out / "README.md", render("README.md.tmpl", **common))
    write(out / ".gitignore", ".env\n__pycache__/\n*.pyc\n.venv/\n")

    # ---- managed ----
    if args.type in ("managed", "hybrid", "orchestrator"):
        write(out / "managed" / "definition.json", render("managed-definition.json.tmpl", **common))

    # ---- local ----
    if args.type in ("local", "hybrid"):
        write(out / "local" / "agent.py", render("local-agent.py.tmpl", **common))
        write(out / "local" / "__init__.py", "")
        if args.type == "hybrid":
            write(out / "local" / "bridge.py", render("bridge.py.tmpl", **common))

    # ---- orchestrator (managed-agent client + workers) ----
    if args.type == "orchestrator":
        write(out / "orchestrator" / "__init__.py", "")
        write(out / "orchestrator" / "orchestrator.py", render("orchestrator.py.tmpl", **common))
        write(out / "orchestrator" / "bridge.py", render("bridge.py.tmpl", **common))
        write(out / "worker" / "__init__.py", "")
        write(out / "worker" / "worker.py", render("worker.py.tmpl", **common))

    # ---- channels ----
    if channels:
        write(out / "channels" / "__init__.py", "")
        write(out / "channels" / "exfil.py", render("exfil.py.tmpl", **common))
        write(out / "channels" / "audit.py", render("audit.py.tmpl", **common))
        if "telegram" in channels:
            write(out / "channels" / "telegram.py", render("channel-telegram.py.tmpl", **common))
        if "slack" in channels:
            write(out / "channels" / "slack.py", render("channel-slack.py.tmpl", **common))
        if "discord" in channels:
            write(out / "channels" / "discord_bot.py", render("channel-discord.py.tmpl", **common))

    # ---- IDE ----
    write(out / "ide" / "jetbrains-external-tool.xml", render("jetbrains-external-tool.xml.tmpl", **common))
    write(out / "ide" / "jetbrains-run-config.xml", render("jetbrains-run-config.xml.tmpl", **common))
    write(out / "ide" / "vscode-tasks.json", render("vscode-tasks.json.tmpl", **common))

    # ---- autostart ----
    write(out / "autostart" / "windows-task.xml", render("windows-task.xml.tmpl", **common))
    write(out / "autostart" / "systemd-user.service", render("systemd-user.service.tmpl", **common))

    print(f"\n✓ {args.name} scaffolded.")
    print(f"  Generated PIN:  {pin}")
    print(f"  HMAC secret:    {hmac_secret[:16]}…  (full value in .env, NOT .env.example)")
    print(f"\nNext steps:")
    print(f"  1. cd {out}")
    print(f"  2. read README.md")
    if args.type in ("managed", "hybrid", "orchestrator"):
        print(f"  3. Create the Environment, then POST managed/definition.json to register the agent")
        print(f"     Fill in AGENT_ID and ENVIRONMENT_ID in .env")
    if args.type == "orchestrator":
        print(f"  4. Deploy worker/worker.py to each host you want to dispatch to")
        print(f"  5. Run orchestrator/orchestrator.py wherever (Lambda, ECS, local)")


if __name__ == "__main__":
    main()
