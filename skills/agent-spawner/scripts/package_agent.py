#!/usr/bin/env python3
"""
package_agent.py — zip a scaffolded agent for shipping.

Excludes: every .env* file or directory (any case) except
.env.example/.env.sample/.env.template, symlinks, .venv, __pycache__, .git,
*.pyc

Usage:
  package_agent.py <path-to-agent-folder> [--output <path-to-zip>]
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

# All names are compared lower-cased: Windows and macOS filesystems are
# case-insensitive, so `.ENV` is the same file as `.env` there.
EXCLUDE_NAMES = {".venv", "__pycache__", ".git", ".idea", ".vscode", ".ds_store"}
EXCLUDE_SUFFIXES = {".pyc"}
# Dotenv templates hold placeholders only, so they ship. Every other `.env*`
# name (.env, .env.local, .env.production, ...) may hold real secrets, and
# neither a file nor a directory by that name is ever packaged.
DOTENV_TEMPLATES = {".env.example", ".env.sample", ".env.template"}


def is_secret_dotenv(name: str) -> bool:
    n = name.lower()
    return n.startswith(".env") and n not in DOTENV_TEMPLATES


def should_skip(rel: Path) -> bool:
    """`rel` is relative to the agent folder; any excluded component skips it."""
    for part in rel.parts:
        if part.lower() in EXCLUDE_NAMES or is_secret_dotenv(part):
            return True
    return rel.suffix.lower() in EXCLUDE_SUFFIXES


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent_dir", type=Path)
    ap.add_argument("--output", type=Path, default=None,
                    help="output zip path (default: <agent_dir>/<agent_name>.zip)")
    args = ap.parse_args()

    agent_dir = args.agent_dir.resolve()
    if not agent_dir.is_dir():
        sys.exit(f"{agent_dir} is not a directory")

    agent_name = agent_dir.name
    out = args.output or (agent_dir / f"{agent_name}.zip")
    out = out.resolve()

    files_added = 0
    skipped = 0
    links = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # os.walk with followlinks=False, and excluded directories pruned so
        # nothing beneath them is ever visited.
        for root, dirs, files in os.walk(agent_dir, followlinks=False):
            rootp = Path(root)
            kept = []
            for d in dirs:
                dp = rootp / d
                if dp.is_symlink():
                    links += 1
                elif should_skip(dp.relative_to(agent_dir)):
                    skipped += 1
                else:
                    kept.append(d)
            dirs[:] = kept
            for f in files:
                fp = rootp / f
                if fp == out:
                    continue
                # A symlink with an allowed name could point at a secret file,
                # and ZipFile.write follows it. Never package symlinks.
                if fp.is_symlink():
                    links += 1
                    continue
                rel = fp.relative_to(agent_dir)
                if should_skip(rel):
                    skipped += 1
                    continue
                z.write(fp, Path(agent_name) / rel)
                files_added += 1

    print(f"✓ wrote {out}")
    print(f"  {files_added} files added, {skipped} skipped (excluded patterns), {links} symlinks skipped")
    print(f"  size: {out.stat().st_size / 1024:.1f} KB")
    return out


if __name__ == "__main__":
    main()
