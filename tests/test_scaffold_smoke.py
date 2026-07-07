"""Scaffolder smoke tests.

Scaffolds representative agent configurations into a tmpdir and asserts the
rendered bundle is internally consistent: every .py file compiles, and every
`channels.*` module the agent imports was actually written by the scaffolder.

Stdlib-only; run with:  python3 -m unittest discover tests
"""
from __future__ import annotations

import py_compile
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCAFFOLDER = Path(__file__).parent.parent / "skills" / "agent-spawner" / "scripts" / "scaffold_agent.py"

CHANNELS_IMPORT = re.compile(r"^\s*from\s+channels\.(\w+)\s+import|^\s*import\s+channels\.(\w+)", re.M)


def scaffold(out: Path, *, type_: str, channels: str, extra: list[str] | None = None) -> None:
    cmd = [
        sys.executable, str(SCAFFOLDER),
        "--name", "smoketest",
        "--product", "smoke",
        "--type", type_,
        "--channels", channels,
        "--system-prompt", "smoke-test agent",
        "--output-dir", str(out),
        "--force", "--no-repo",
    ] + (extra or [])
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise AssertionError(f"scaffold failed:\n{res.stdout}\n{res.stderr}")


class ScaffoldSmokeTest(unittest.TestCase):
    def check_bundle(self, out: Path) -> None:
        py_files = sorted(out.rglob("*.py"))
        self.assertTrue(py_files, f"no .py files rendered in {out}")
        for f in py_files:
            py_compile.compile(str(f), doraise=True)

        # Static import check: only assert channel-adapter imports for adapters
        # that were scaffolded; core imports (exfil, telemetry) must always
        # resolve in any bundle that contains local/agent.py.
        agent = out / "local" / "agent.py"
        if agent.exists():
            for m in CHANNELS_IMPORT.finditer(agent.read_text()):
                mod = m.group(1) or m.group(2)
                if mod in ("telegram", "slack", "discord_bot"):
                    continue  # adapter imports are guarded by PERSONA["channels"]
                self.assertTrue(
                    (out / "channels" / f"{mod}.py").exists(),
                    f"local/agent.py imports channels.{mod} but channels/{mod}.py was not scaffolded",
                )

    def test_local_without_channels(self):
        """--type local --channels none must produce a bundle whose
        handle_message imports all resolve (PR #2 review, blocking issue 1)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "smoketest"
            scaffold(out, type_="local", channels="none")
            self.check_bundle(out)
            self.assertTrue((out / "channels" / "telemetry.py").exists())
            self.assertTrue((out / "channels" / "exfil.py").exists())

    def test_local_with_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "smoketest"
            scaffold(out, type_="local", channels="telegram")
            self.check_bundle(out)
            self.assertTrue((out / "channels" / "telegram.py").exists())
            self.assertTrue((out / "channels" / "audit.py").exists())

    def test_hybrid_without_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "smoketest"
            scaffold(
                out, type_="hybrid", channels="none",
                extra=["--delegate-to", "peer", "--delegate-url", "https://example.com/api"],
            )
            self.check_bundle(out)
            self.assertTrue((out / "channels" / "telemetry.py").exists())
