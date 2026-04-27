from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from browse.browser import (
    BrowserLaunchConfig,
    BrowseError,
    DEFAULT_PORT,
    DEFAULT_PROFILE_DIR,
    cleanup_browse_chrome_processes,
    launch_browser,
    profile_dir_status,
    verify_browser_runtime,
)
from browse.config import (
    BrowseConfig,
    config_exists,
    config_path,
    load_config,
    prompt_for_config,
    save_config,
)
from browse.daemon import DEFAULT_IDLE_TIMEOUT_SECONDS, ensure_daemon_running
from browse.protocol import DaemonClientError, send_request
from browse.skills import NO_SUPPORTED_CLIS_MESSAGE, install_skills


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    message: str | None = None
    error: str | None = None
    data: dict[str, Any] | None = None


class JsonCommandParser(argparse.ArgumentParser):
    def error(self, message):  # pragma: no cover - argparse exits immediately
        raise BrowseError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonCommandParser(prog="browse", description="Browser automation CLI for UI verification")
    parser.set_defaults(handler=cmd_help)
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Verify Playwright and browser prerequisites")
    install_parser.add_argument(
        "--bundled-chromium",
        action="store_true",
        help="Install Playwright's bundled Chromium as an explicit fallback when no system Chrome is available.",
    )
    install_parser.set_defaults(handler=cmd_install)

    skills_parser = subparsers.add_parser("install-skills", help="Install Claude/Codex skills")
    skills_parser.set_defaults(handler=cmd_install_skills)

    init_parser = subparsers.add_parser("init", help="Install runtime and skills")
    init_parser.add_argument("--bundled-chromium", action="store_true")
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
    chrome_parser.add_argument(
        "--status",
        action="store_true",
        help="Print profile-directory diagnostics instead of launching Chrome",
    )
    chrome_parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Terminate any orphaned Chrome processes using the browse profile and exit",
    )
    chrome_parser.set_defaults(handler=cmd_chrome)

    session_parser = subparsers.add_parser("session", help="Manage the long-lived browse daemon session")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    for name, handler, help_text in [
        ("start", cmd_session_start, "Start or reuse a browse session daemon"),
        ("status", cmd_session_status, "Show session status"),
        ("stop", cmd_session_stop, "Stop the running session daemon"),
    ]:
        sub = session_subparsers.add_parser(name, help=help_text)
        sub.add_argument("--port", type=int, default=None, help=f"CDP port (default: {DEFAULT_PORT})")
        if name == "start":
            sub.add_argument("--idle-timeout-seconds", type=int, default=DEFAULT_IDLE_TIMEOUT_SECONDS)
        sub.set_defaults(handler=handler)

    pages_parser = subparsers.add_parser("pages", help="List page_ids for the running session")
    pages_parser.add_argument("--port", type=int, default=None)
    pages_parser.set_defaults(handler=cmd_pages)

    select_page_parser = subparsers.add_parser("select-page", help="Select the active page_id for future commands")
    select_page_parser.add_argument("page_id")
    select_page_parser.add_argument("--port", type=int, default=None)
    select_page_parser.set_defaults(handler=cmd_select_page)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect actionable elements grouped by active scope")
    inspect_parser.add_argument("--port", type=int, default=None)
    inspect_parser.add_argument(
        "--include-offscreen",
        action="store_true",
        help="Include elements rendered off-viewport (default: viewport-only).",
    )
    inspect_parser.set_defaults(handler=cmd_inspect)

    click_parser = subparsers.add_parser("click", help="Click a previously inspected target_id")
    click_parser.add_argument("target_id")
    _add_state_flags(click_parser)
    click_parser.set_defaults(handler=cmd_click)

    type_parser = subparsers.add_parser("type", help="Type into a previously inspected target_id")
    type_parser.add_argument("target_id")
    type_parser.add_argument("text")
    _add_state_flags(type_parser)
    type_parser.set_defaults(handler=cmd_type)

    press_parser = subparsers.add_parser("press", help="Press a key on the selected page")
    press_parser.add_argument("key")
    _add_state_flags(press_parser)
    press_parser.set_defaults(handler=cmd_press)

    wait_parser = subparsers.add_parser("wait", help="Wait for a target, URL fragment, or timeout")
    condition_group = wait_parser.add_mutually_exclusive_group(required=True)
    condition_group.add_argument("--target")
    condition_group.add_argument("--url-contains")
    condition_group.add_argument("--milliseconds", type=int)
    wait_parser.add_argument("--port", type=int, default=None)
    _add_if_version(wait_parser)
    wait_parser.set_defaults(handler=cmd_wait)

    screenshot_parser = subparsers.add_parser("screenshot", help="Capture a screenshot from the selected page")
    screenshot_parser.add_argument("--output", required=True)
    screenshot_parser.add_argument("--port", type=int, default=None)
    full_page_group = screenshot_parser.add_mutually_exclusive_group()
    full_page_group.add_argument("--full-page", dest="full_page", action="store_true", default=True)
    full_page_group.add_argument("--no-full-page", dest="full_page", action="store_false")
    _add_if_version(screenshot_parser)
    screenshot_parser.set_defaults(handler=cmd_screenshot)

    console_parser = subparsers.add_parser("console", help="Read recent console/page/network errors")
    console_parser.add_argument("--limit", type=int, default=50)
    console_parser.add_argument("--port", type=int, default=None)
    console_parser.set_defaults(handler=cmd_console)

    url_parser = subparsers.add_parser("url", help="Show the selected page URL and title")
    url_parser.add_argument("--port", type=int, default=None)
    url_parser.set_defaults(handler=cmd_url)

    back_parser = subparsers.add_parser("back", help="Navigate the selected page backward")
    _add_state_flags(back_parser)
    back_parser.set_defaults(handler=cmd_back)

    choose_parser = subparsers.add_parser("choose", help="Drive a combobox/autocomplete selection")
    choose_parser.add_argument("target_id")
    choose_parser.add_argument("text")
    _add_state_flags(choose_parser)
    choose_parser.set_defaults(handler=cmd_choose)

    pick_date_parser = subparsers.add_parser("pick-date", help="Drive a date picker or date input")
    pick_date_parser.add_argument("target_id")
    pick_date_parser.add_argument("iso_date")
    _add_state_flags(pick_date_parser)
    pick_date_parser.set_defaults(handler=cmd_pick_date)

    submit_parser = subparsers.add_parser("submit", help="Click the primary save/submit action")
    _add_state_flags(submit_parser)
    submit_parser.set_defaults(handler=cmd_submit)

    open_parser = subparsers.add_parser("open", help="Open a URL in the selected daemon page")
    open_parser.add_argument("url", nargs="?", help="URL to open")
    open_parser.add_argument("--port", type=int, default=None, help=f"CDP port (default: {DEFAULT_PORT})")
    _add_if_version(open_parser)
    open_parser.set_defaults(handler=cmd_open)

    snapshot_parser = subparsers.add_parser("snapshot", help="Navigate optionally, then capture a screenshot")
    snapshot_parser.add_argument("url", nargs="?", help="URL to open")
    snapshot_parser.add_argument("--output", required=True, help="Screenshot output path, for example /tmp/page.png")
    snapshot_parser.add_argument("--port", type=int, default=None, help=f"CDP port (default: {DEFAULT_PORT})")
    full_page_group = snapshot_parser.add_mutually_exclusive_group()
    full_page_group.add_argument("--full-page", dest="full_page", action="store_true", default=True, help="Capture the full page (default)")
    full_page_group.add_argument("--no-full-page", dest="full_page", action="store_false", help="Capture only the viewport")
    _add_if_version(snapshot_parser)
    snapshot_parser.set_defaults(handler=cmd_snapshot)

    return parser


def _add_if_version(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--if-version", type=int, default=None)


def _add_state_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=None)
    _add_if_version(parser)


def cmd_help(args) -> CommandResult:
    parser = build_parser()
    parser.print_help()
    return CommandResult(exit_code=0)


def cmd_install(args) -> CommandResult:
    browser_path = verify_browser_runtime(install_bundled_chromium=args.bundled_chromium)
    base = "Playwright + Chromium are installed and ready for `browse chrome`."
    if browser_path is None:
        return CommandResult(exit_code=0, message=base)
    return CommandResult(
        exit_code=0,
        message=f"{base}\nSystem browser also detected (informational, not used): {browser_path}",
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


def cmd_init(args) -> CommandResult:
    lines = []
    install_result = cmd_install(argparse.Namespace(bundled_chromium=args.bundled_chromium))
    if install_result.message:
        lines.append(install_result.message)
    skills_result = cmd_install_skills(None)
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
            "  browse session start",
            "  browse inspect",
            f"  browse open {resolved.base_url}",
            "  browse screenshot --output /tmp/page.png",
        ]
    )
    return CommandResult(exit_code=0, message="\n".join(lines))


def cmd_chrome(args) -> CommandResult:
    resolved = _resolve_effective_config(args)
    profile_dir = (
        Path(args.profile_dir).expanduser()
        if args.profile_dir is not None
        else resolved.chrome_profile_dir
    )
    if getattr(args, "status", False):
        info = profile_dir_status(profile_dir)
        return CommandResult(exit_code=0, data={"command": "chrome-status", **info})
    if getattr(args, "cleanup", False):
        result = cleanup_browse_chrome_processes(profile_dir)
        return CommandResult(exit_code=0, data={"command": "chrome-cleanup", **result})
    browser_config = BrowserLaunchConfig(
        port=args.port if args.port is not None else resolved.chrome_port,
        profile_dir=profile_dir,
    )
    sys.stderr.write(
        f"Launching Chromium with persistent profile at {profile_dir}\n"
        f"CDP debug port: {browser_config.port}\n"
        "Keep this terminal open. Close the Chromium window or press Ctrl+C to stop.\n"
    )
    launch_browser(browser_config)
    return CommandResult(exit_code=0, message="Chromium closed.")


def cmd_session_start(args) -> CommandResult:
    port = _resolve_port(args)
    result = ensure_daemon_running(port, idle_timeout_seconds=args.idle_timeout_seconds)
    return CommandResult(exit_code=0, data=result)


def cmd_session_status(args) -> CommandResult:
    port = _resolve_port(args)
    return CommandResult(exit_code=0, data=send_request(port, "status", {}))


def cmd_session_stop(args) -> CommandResult:
    port = _resolve_port(args)
    return CommandResult(exit_code=0, data=send_request(port, "stop", {}))


def cmd_pages(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "pages", {}))


def cmd_select_page(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "select-page", {"page_id": args.page_id}))


def cmd_inspect(args) -> CommandResult:
    params: dict[str, Any] = {}
    if getattr(args, "include_offscreen", False):
        params["include_offscreen"] = True
    return CommandResult(exit_code=0, data=_daemon_call(args, "inspect", params))


def cmd_click(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "click", {"target_id": args.target_id, "if_version": args.if_version}))


def cmd_type(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "type", {"target_id": args.target_id, "text": args.text, "if_version": args.if_version}))


def cmd_press(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "press", {"key": args.key, "if_version": args.if_version}))


def cmd_wait(args) -> CommandResult:
    return CommandResult(
        exit_code=0,
        data=_daemon_call(
            args,
            "wait",
            {
                "target_id": args.target,
                "url_contains": args.url_contains,
                "milliseconds": args.milliseconds,
                "if_version": args.if_version,
            },
        ),
    )


def cmd_screenshot(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "screenshot", {"output": args.output, "full_page": args.full_page, "if_version": args.if_version}))


def cmd_console(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "console", {"limit": args.limit}))


def cmd_url(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "url", {}))


def cmd_back(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "back", {"if_version": args.if_version}))


def cmd_choose(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "choose", {"target_id": args.target_id, "text": args.text, "if_version": args.if_version}))


def cmd_pick_date(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "pick-date", {"target_id": args.target_id, "iso_date": args.iso_date, "if_version": args.if_version}))


def cmd_submit(args) -> CommandResult:
    return CommandResult(exit_code=0, data=_daemon_call(args, "submit", {"if_version": args.if_version}))


def cmd_open(args) -> CommandResult:
    resolved = _resolve_effective_config(args)
    url = args.url or resolved.base_url
    if not url:
        raise BrowseError("No URL provided and no configured base URL found. Run `browse config` first.")
    return CommandResult(exit_code=0, data=_daemon_call(args, "open", {"url": url, "if_version": args.if_version}))


def cmd_snapshot(args) -> CommandResult:
    resolved = _resolve_effective_config(args)
    port = _resolve_port(args)
    url = args.url or resolved.base_url
    if url:
        _ensure_session(port)
        open_result = send_request(port, "open", {"url": url, "if_version": args.if_version})
        if not open_result.get("ok", False):
            return CommandResult(exit_code=1, data=open_result)
    screenshot_result = _daemon_call(args, "screenshot", {"output": args.output, "full_page": args.full_page, "if_version": None})
    return CommandResult(exit_code=0, data=screenshot_result)


def _resolve_effective_config(_args) -> BrowseConfig:
    return load_config()


def _resolve_port(args) -> int:
    resolved = _resolve_effective_config(args)
    return args.port if getattr(args, "port", None) is not None else resolved.chrome_port


def _ensure_session(port: int) -> dict[str, Any]:
    return ensure_daemon_running(port)


def _daemon_call(args, command: str, params: dict[str, Any]) -> dict[str, Any]:
    port = _resolve_port(args)
    _ensure_session(port)
    return send_request(port, command, params)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = args.handler(args)
    except (BrowseError, DaemonClientError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130

    if result.data is not None:
        print(json.dumps(result.data, indent=2))
    if result.message:
        print(result.message)
    if result.error:
        print(result.error, file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
