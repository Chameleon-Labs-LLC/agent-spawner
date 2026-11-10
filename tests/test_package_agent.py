"""package_agent.py tests: the zip never carries secrets.

Stdlib-only; run with:  python3 -m unittest discover tests
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PACKAGER = Path(__file__).parent.parent / "skills" / "agent-spawner" / "scripts" / "package_agent.py"

SECRET_FILES = [".env", ".env.local", ".env.production", "sub/.env.dev"]
SHIPPED_FILES = ["agent.py", ".env.example", ".env.sample", ".env.template", "sub/module.py"]


class PackageAgentTest(unittest.TestCase):
    def test_dotenv_variants_are_excluded_and_templates_ship(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = Path(tmp) / "demo"
            for rel in SECRET_FILES + SHIPPED_FILES:
                f = agent / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("x\n", encoding="utf-8")
            out = Path(tmp) / "demo.zip"
            res = subprocess.run(
                [sys.executable, str(PACKAGER), str(agent), "--output", str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            with zipfile.ZipFile(out) as z:
                names = {n.removeprefix("demo/") for n in z.namelist()}
            for rel in SECRET_FILES:
                self.assertNotIn(rel, names, f"{rel} must never be packaged")
            for rel in SHIPPED_FILES:
                self.assertIn(rel, names, f"{rel} should be packaged")


if __name__ == "__main__":
    unittest.main()
