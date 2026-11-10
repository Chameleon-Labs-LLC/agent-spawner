"""package_agent.py tests: the zip never carries secrets.

Stdlib-only; run with:  python3 -m unittest discover tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PACKAGER = Path(__file__).parent.parent / "skills" / "agent-spawner" / "scripts" / "package_agent.py"

SECRET_FILES = [
    ".env", ".env.local", ".env.production", "sub/.env.dev",
    ".ENV", ".Env.Local",              # case variants (same file on Windows/macOS)
    ".env.secrets/API_KEY",           # a directory named like a dotenv file
]
SHIPPED_FILES = ["agent.py", ".env.example", ".env.sample", ".env.template", "sub/module.py"]


def package(agent: Path, out: Path) -> set[str]:
    # The packager prints non-ASCII status text; force UTF-8 so a cp1252
    # console (native Windows) cannot turn a successful run into exit 1.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    res = subprocess.run(
        [sys.executable, str(PACKAGER), str(agent), "--output", str(out)],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    if res.returncode != 0:
        raise AssertionError(f"packager failed:\n{res.stdout}\n{res.stderr}")
    with zipfile.ZipFile(out) as z:
        return {n.split("/", 1)[1] for n in z.namelist()}


def write(root: Path, rel: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x\n", encoding="utf-8")


class PackageAgentTest(unittest.TestCase):
    def test_dotenv_files_and_dirs_excluded_templates_ship(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = Path(tmp) / "demo"
            agent.mkdir()
            # On a case-insensitive filesystem `.ENV` and `.env` are one file,
            # so write each name only if it isn't already present.
            for rel in SECRET_FILES + SHIPPED_FILES:
                if not (agent / rel).exists():
                    write(agent, rel)
            names = package(agent, Path(tmp) / "demo.zip")
            lowered = {n.lower() for n in names}
            for rel in SECRET_FILES:
                self.assertNotIn(rel.lower(), lowered, f"{rel} must never be packaged")
            for rel in SHIPPED_FILES:
                self.assertIn(rel, names, f"{rel} should be packaged")

    def test_symlinks_are_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = Path(tmp) / "demo"
            write(agent, "agent.py")
            secret = Path(tmp) / "outside-secret.txt"
            secret.write_text("SECRET\n", encoding="utf-8")
            try:
                os.symlink(secret, agent / "notes.txt")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not permitted on this platform/user")
            names = package(agent, Path(tmp) / "demo.zip")
            self.assertNotIn("notes.txt", names)
            self.assertIn("agent.py", names)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs need a POSIX system")
    def test_non_regular_files_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = Path(tmp) / "demo"
            write(agent, "agent.py")
            os.mkfifo(agent / "runtime.fifo")  # reading it would block forever
            names = package(agent, Path(tmp) / "demo.zip")
            self.assertEqual(names, {"agent.py"})

    @unittest.skipUnless(sys.platform == "win32", "junctions are Windows-only")
    def test_windows_junctions_are_never_followed(self) -> None:
        import _winapi
        with tempfile.TemporaryDirectory() as tmp:
            agent = Path(tmp) / "demo"
            write(agent, "agent.py")
            write(agent, ".env.secrets/API_KEY")
            # `assets` is an allowed name, but it is a junction to the
            # excluded directory; its contents must not ship as assets/API_KEY.
            _winapi.CreateJunction(str(agent / ".env.secrets"), str(agent / "assets"))
            names = package(agent, Path(tmp) / "demo.zip")
            self.assertEqual(names, {"agent.py"})


if __name__ == "__main__":
    unittest.main()
