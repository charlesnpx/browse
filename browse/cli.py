from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from browse.browser import (
    BrowserLaunchConfig,
    BrowseError,
    DEFAULT_PORT,
    DEFAULT_PROFILE_DIR,
    install_playwright_chromium,
    launch_browser,
    open_page,
    run_snapshot,
)
from browse.config import (
    BrowseConfig,
    config_exists,
    config_path,
    load_config,
    prompt_for_config,
    save_config,
)
from browse.skills import NO_SUPPORTED_CLIS_MESSAGE, install_skills


class OrderedAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        actions = getattr(namespace, "actions", None)
        if actions is None:
            actions = []
            setattr(namespace, "actions", actions)

        if option_string == "--fill":
            payload = (values[0], values[1])
            actions.append(("fill", payload))
        elif option_string == "--click":
            actions.append(("click", values))
        elif option_string == "--wait-for":
            actions.append(("wait-for", values))
        elif option_string == "--sleep-ms":
            actions.append(("sleep-ms", values))
        else:  # pragma: no cover - parser constrains action names
            raise argparse.ArgumentError(self, f"Unsupported ordered action: {option_string}")


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    message: str | None = None
    error: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browse", description="Browser automation CLI for UI verification")
    parser.set_defaults(handler=cmd_help)
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Install Playwright Chromium runtime")
    install_parser.set_defaults(handler=cmd_install)

    skills_parser = subparsers.add_parser("install-skills", help="Install Claude/Codex skills")
    skills_parser.set_defaults(handler=cmd_install_skills)

    init_parser = subparsers.add_parser("init", help="Install runtime and skills")
    init_parser.set_defaults(handler=cmd_init)

    config_parser = subparsers.add_parser("config", help="Create or update saved browse defaults")
    config_parser.set_defaults(handler=cmd_config)

    chrome_parser = subparsers.add_parser("chrome", help="Launch a visible Chrome/Chromium session for CDP attachment")
    chrome_parser.add_argument("--port", type=int, default=None, help=f"Remote debugging port (default: {DEFAULT_PORT})")
    chrome_parser.add_argument(
        "--profile-dir",
        default=None,
        help=f"Dedicated browser profile directory (default: {DEFAULT_PROFILE_DIR})",
    )
    chrome_parser.set_defaults(handler=cmd_chrome)

    open_parser = subparsers.add_parser("open", help="Open a URL in the running CDP browser")
    open_parser.add_argument("url", nargs="?", help="URL to open")
    open_parser.add_argument("--port", type=int, default=None, help=f"CDP port (default: {DEFAULT_PORT})")
    open_parser.set_defaults(handler=cmd_open)

    snapshot_parser = subparsers.add_parser("snapshot", help="Capture a screenshot from the running CDP browser")
    snapshot_parser.add_argument("url", nargs="?", help="URL to open")
    snapshot_parser.add_argument("--output", required=True, help="Screenshot output path, for example /tmp/page.png")
    snapshot_parser.add_argument("--port", type=int, default=None, help=f"CDP port (default: {DEFAULT_PORT})")
    snapshot_parser.add_argument("--click", action=OrderedAction, dest="actions", metavar="SELECTOR")
    snapshot_parser.add_argument("--fill", action=OrderedAction, dest="actions", nargs=2, metavar=("SELECTOR", "VALUE"))
    snapshot_parser.add_argument("--wait-for", action=OrderedAction, dest="actions", metavar="SELECTOR")
    snapshot_parser.add_argument("--sleep-ms", action=OrderedAction, dest="actions", type=int, metavar="MILLISECONDS")
    full_page_group = snapshot_parser.add_mutually_exclusive_group()
    full_page_group.add_argument("--full-page", dest="full_page", action="store_true", default=True, help="Capture the full page (default)")
    full_page_group.add_argument("--no-full-page", dest="full_page", action="store_false", help="Capture only the viewport")
    snapshot_parser.set_defaults(handler=cmd_snapshot)

    return parser


def cmd_help(args) -> CommandResult:
    parser = build_parser()
    parser.print_help()
    return CommandResult(exit_code=0)


def cmd_install(_args) -> CommandResult:
    install_playwright_chromium()
    return CommandResult(
        exit_code=0,
        message="Playwright Chromium is installed and ready for `browse chrome`.",
    )


def cmd_install_skills(_args) -> CommandResult:
    installed = install_skills()
    if not installed:
        return CommandResult(exit_code=0, message=NO_SUPPORTED_CLIS_MESSAGE)

    lines = ["Installed skill assets:"]
    lines.extend(f"  {item}" for item in installed)
    return CommandResult(exit_code=0, message="\n".join(lines))


def cmd_config(_args) -> CommandResult:
    existing = load_config() if config_exists() else None
    configured = prompt_for_config(existing)
    path = save_config(configured)
    return CommandResult(
        exit_code=0,
        message=(
            f"Saved browse config: {path}\n"
            f"Base URL: {configured.base_url}\n"
            f"Chrome port: {configured.chrome_port}\n"
            f"Chrome profile dir: {configured.chrome_profile_dir}"
        ),
    )


def cmd_init(_args) -> CommandResult:
    install_result = cmd_install(None)
    skills_result = cmd_install_skills(None)
    lines = []
    if install_result.message:
        lines.append(install_result.message)
    if skills_result.message:
        lines.append(skills_result.message)
    if config_exists():
        resolved = load_config()
        lines.append("Config already exists. Run `browse config` to update it.")
    else:
        configured = prompt_for_config(None)
        save_config(configured)
        resolved = configured
        lines.append(f"Saved browse config: {config_path()}")
    lines.extend(
        [
            "",
            "Ready to use:",
            "  browse chrome",
            f"  browse open {resolved.base_url}",
            "  browse snapshot --output /tmp/page.png",
        ]
    )
    return CommandResult(exit_code=0, message="\n".join(lines))


def cmd_chrome(args) -> CommandResult:
    resolved = _resolve_effective_config(args)
    browser_config = BrowserLaunchConfig(
        port=args.port if args.port is not None else resolved.chrome_port,
        profile_dir=Path(args.profile_dir).expanduser() if args.profile_dir is not None else resolved.chrome_profile_dir,
    )
    launched = launch_browser(browser_config)
    return CommandResult(
        exit_code=0,
        message=(
            f"Launched {launched.executable.name} with CDP at {launched.cdp_url}\n"
            f"Profile: {launched.profile_dir}\n"
            "Keep this browser window open and sign in there if your app needs authentication."
        ),
    )


def cmd_open(args) -> CommandResult:
    resolved = _resolve_effective_config(args)
    url = args.url or resolved.base_url
    port = args.port if args.port is not None else resolved.chrome_port
    if not url:
        raise BrowseError("No URL provided and no configured base URL found. Run `browse config` first.")
    final_url = open_page(url, port)
    return CommandResult(exit_code=0, message=f"Opened {final_url} in the attached browser.")


def cmd_snapshot(args) -> CommandResult:
    resolved = _resolve_effective_config(args)
    url = args.url or resolved.base_url
    port = args.port if args.port is not None else resolved.chrome_port
    if not url:
        raise BrowseError("No URL provided and no configured base URL found. Run `browse config` first.")
    artifacts = run_snapshot(
        url,
        args.output,
        args.actions or [],
        port,
        args.full_page,
    )
    return CommandResult(
        exit_code=0,
        message=(
            f"Wrote screenshot: {artifacts.screenshot_path}\n"
            f"Wrote log: {artifacts.log_path}"
        ),
    )


def _resolve_effective_config(_args) -> BrowseConfig:
    return load_config()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = args.handler(args)
    except BrowseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130

    if result.message:
        print(result.message)
    if result.error:
        print(result.error, file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
