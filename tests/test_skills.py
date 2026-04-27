from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browse.skills import install_skills


class SkillInstallTest(unittest.TestCase):
    @mock.patch("browse.skills.shutil.which")
    @mock.patch("browse.skills.Path.home")
    def test_install_skills_copies_claude_and_codex_assets(self, mock_home, mock_which):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            codex_home = Path(tmpdir) / "codex"
            home.mkdir(parents=True, exist_ok=True)
            codex_home.mkdir(parents=True, exist_ok=True)

            mock_home.return_value = home
            mock_which.side_effect = lambda name: f"/usr/local/bin/{name}" if name in {"claude", "codex"} else None

            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=False):
                installed = install_skills()

            self.assertEqual(len(installed), 2)
            self.assertTrue((home / ".claude" / "skills" / "browse" / "SKILL.md").exists())
            self.assertTrue((codex_home / "skills" / "browse" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()

