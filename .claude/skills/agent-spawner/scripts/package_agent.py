#!/usr/bin/env python3
"""
package_agent.py — zip a scaffolded agent for shipping.

Excludes: .env, .venv, __pycache__, .git, *.pyc

Usage:
  package_agent.py <path-to-agent-folder> [--output <path-to-zip>]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

EXCLUDE_NAMES = {".env", ".venv", "__pycache__", ".git", ".idea", ".vscode", ".DS_Store"}
EXCLUDE_SUFFIXES = {".pyc"}


def should_skip(p: Path) -> bool:
    if p.name in EXCLUDE_NAMES:
        return True
    if p.suffix in EXCLUDE_SUFFIXES:
        return True
    if any(part in EXCLUDE_NAMES for part in p.parts):
        return True
    return False


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
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in agent_dir.rglob("*"):
            if p == out:
                continue
            if should_skip(p):
                if p.is_file():
                    skipped += 1
                continue
            if p.is_file():
                arcname = Path(agent_name) / p.relative_to(agent_dir)
                z.write(p, arcname)
                files_added += 1

    print(f"✓ wrote {out}")
    print(f"  {files_added} files added, {skipped} skipped (excluded patterns)")
    print(f"  size: {out.stat().st_size / 1024:.1f} KB")
    return out


if __name__ == "__main__":
    main()
