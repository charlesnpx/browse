from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tomllib
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Literal


NO_SUPPORTED_CLIS_MESSAGE = (
    "  No supported CLIs found (claude, codex).\n"
    "  Install Claude Code or Codex CLI first."
)

Target = Literal["claude", "codex", "all"]
Operation = Literal["plan", "install", "uninstall"]


def bundle_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "skill"


def _version() -> str:
    try:
        return importlib_metadata.version("browse")
    except importlib_metadata.PackageNotFoundError:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        try:
            return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        except Exception:
            return "0.0.0"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_path(src: Path, dst: Path) -> None:
    if src.is_dir():
        if dst.exists() or dst.is_symlink():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.copytree(src, dst)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _target_specs(target: Target = "all") -> dict[str, list[tuple[Path, Path]]]:
    bundle = bundle_dir()
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    specs = {
        "claude": [(bundle / "SKILL.md", Path.home() / ".claude" / "skills" / "browse" / "SKILL.md")],
        "codex": [(bundle / "codex", codex_home / "skills" / "browse")],
    }
    if target == "all":
        return specs
    return {target: specs[target]}


def _record_file(path: Path, include_hash: bool) -> dict[str, str]:
    rec = {"path": str(path.resolve())}
    if include_hash and path.exists() and path.is_file():
        rec["sha256"] = _sha256(path)
    return rec


def _records_for_dst(dst: Path, include_hash: bool) -> list[dict[str, str]]:
    if dst.is_dir():
        out = []
        for p in sorted(x for x in dst.rglob("*") if x.is_file()):
            out.append(_record_file(p, include_hash))
        return out
    return [_record_file(dst, include_hash)]


def delegated_result(operation: Operation, target: Target = "all", *, perform: bool = False) -> dict[str, Any]:
    specs = _target_specs(target)
    result: dict[str, Any] = {
        "schema": 1,
        "name": "browse",
        "version": _version(),
        "operation": operation,
        "kind": "delegated",
        "targets": {},
        "warnings": [],
    }

    for target_name, pairs in specs.items():
        if operation == "install" and perform:
            for src, dst in pairs:
                _copy_path(src, dst)
        elif operation == "uninstall" and perform:
            for _src, dst in pairs:
                _remove_path(dst)

        files: list[dict[str, str]] = []
        for _src, dst in pairs:
            if operation == "plan":
                if dst.suffix:
                    files.append({"path": str(dst.expanduser().resolve())})
                else:
                    # Directory payloads are represented by the directory root at plan time.
                    files.append({"path": str(dst.expanduser().resolve())})
            elif operation == "install":
                files.extend(_records_for_dst(dst, include_hash=True))
            else:
                files.append({"path": str(dst.expanduser().resolve())})
        result["targets"][target_name] = {"files": files}
    return result


def install_skills(target: Target = "all", *, json_mode: bool = False) -> list[str]:
    result = delegated_result("install", target, perform=True)
    if json_mode:
        print(json.dumps(result, indent=2))
        return []
    installed: list[str] = []
    for target_name, info in result["targets"].items():
        for f in info["files"]:
            installed.append(f"{target_name.title()} skill -> {f['path']}")
    return installed


def run_install_contract(args: Any) -> int:
    operation: Operation = "install"
    if getattr(args, "plan", False):
        operation = "plan"
    elif getattr(args, "uninstall", False):
        operation = "uninstall"
    result = delegated_result(operation, args.target, perform=operation != "plan")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for target_name, info in result["targets"].items():
            print(f"{operation} {target_name}:", file=sys.stderr)
            for f in info["files"]:
                print(f"  {f['path']}", file=sys.stderr)
    return 0
