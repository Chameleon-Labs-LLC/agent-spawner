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
VALID_TYPE = {"managed", "local", "hybrid"}
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
    rows = ["- `ANTHROPIC_API_KEY`", "- `AGENT_PIN`"]
    if type_ == "hybrid":
        rows.append("- `BRIDGE_HMAC_SECRET` (already populated; **must match managed-side verifier**)")
        rows.append("- `MANAGED_AGENT_ID` (fill in after step 2)")
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


def managed_setup_block(type_: str) -> str:
    if type_ == "local":
        return ""
    return (
        "### 2a. Register the managed agent\n\n"
        "```bash\n"
        "curl -X POST https://api.anthropic.com/v1/managed-agents \\\n"
        "  -H \"Authorization: Bearer $ANTHROPIC_API_KEY\" \\\n"
        "  -H \"anthropic-beta: managed-agents-2026-04-01\" \\\n"
        "  -H \"Content-Type: application/json\" \\\n"
        "  -d @managed/definition.json\n"
        "```\n\n"
        "Take the `id` from the response and set `MANAGED_AGENT_ID=` in `.env`.\n"
    )


def bridge_block(type_: str, delegate_to: str, delegate_url: str) -> str:
    if type_ != "hybrid":
        return ""
    return (
        f"\n### Hybrid bridge\n\n"
        f"This local agent delegates to the managed agent **{delegate_to}** at "
        f"`{delegate_url}`. Calls are signed with HMAC-SHA256 (timestamp + nonce + body hash) "
        f"using `BRIDGE_HMAC_SECRET`. The managed-side verifier **must use the same secret** — "
        f"that's the whole point. The secret was generated for you and lives in `.env`; "
        f"copy it to the managed-side verifier's environment too.\n"
    )


def channel_files_md(channels: list[str]) -> str:
    rows = []
    if "telegram" in channels:
        rows.append("│   ├── telegram.py")
    if "slack" in channels:
        rows.append("│   ├── slack.py")
    if "discord" in channels:
        rows.append("│   └── discord_bot.py")
    return "\n".join(rows)


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
        managed_setup_block=managed_setup_block(args.type),
        bridge_block=bridge_block(args.type, args.delegate_to, args.delegate_url),
        channel_files_md=channel_files_md(channels),
    )

    print(f"\nScaffolding {args.name} → {out}\n")

    # ---- root ----
    write(out / "persona.json", render("persona.json.tmpl", **common))
    write(out / "pyproject.toml", render("pyproject.toml.tmpl", **common))
    write(out / ".env.example", render("env.example.tmpl", **common))
    write(out / "README.md", render("README.md.tmpl", **common))
    write(out / ".gitignore", ".env\n__pycache__/\n*.pyc\n.venv/\n")

    # ---- managed ----
    if args.type in ("managed", "hybrid"):
        write(out / "managed" / "definition.json", render("managed-definition.json.tmpl", **common))

    # ---- local ----
    if args.type in ("local", "hybrid"):
        write(out / "local" / "agent.py", render("local-agent.py.tmpl", **common))
        write(out / "local" / "__init__.py", "")
        if args.type == "hybrid":
            write(out / "local" / "bridge.py", render("bridge.py.tmpl", **common))

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
    print(f"  HMAC secret:    {hmac_secret[:16]}…  (full value in .env.example)")
    print(f"\nNext steps:")
    print(f"  1. cd {out}")
    print(f"  2. cp .env.example .env  &&  fill in tokens")
    print(f"  3. read README.md")
    if args.type in ("managed", "hybrid"):
        print(f"  4. POST managed/definition.json to register the managed agent")


if __name__ == "__main__":
    main()
