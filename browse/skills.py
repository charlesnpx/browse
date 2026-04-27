from __future__ import annotations

import os
import shutil
from pathlib import Path


NO_SUPPORTED_CLIS_MESSAGE = (
    "  No supported CLIs found (claude, codex).\n"
    "  Install Claude Code or Codex CLI first."
)


def bundle_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "skill"


def install_skills() -> list[str]:
    bundle = bundle_dir()
    installed: list[str] = []

    if shutil.which("claude"):
        claude_dest = Path.home() / ".claude" / "skills" / "browse" / "SKILL.md"
        claude_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / "SKILL.md", claude_dest)
        installed.append(f"Claude Code skill -> {claude_dest}")

    if shutil.which("codex"):
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        codex_dest = codex_home / "skills" / "browse"
        codex_src = bundle / "codex"
        if codex_dest.exists():
            shutil.rmtree(codex_dest)
        shutil.copytree(codex_src, codex_dest)
        installed.append(f"Codex skill       -> {codex_dest}")

    return installed

