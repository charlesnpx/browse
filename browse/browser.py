from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DEFAULT_PORT = 9222
DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
DEFAULT_PROFILE_DIR = Path.home() / ".browse" / "chrome-profile"
DEFAULT_CDP_HOST = "127.0.0.1"
LOG_SUFFIX = ".log"
BROWSER_CANDIDATES = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    Path.home() / "Applications/Chromium.app/Contents/MacOS/Chromium",
]


class BrowseError(RuntimeError):
    """User-facing runtime error."""


@dataclass(frozen=True)
class BrowserLaunchConfig:
    port: int = DEFAULT_PORT
    profile_dir: Path = DEFAULT_PROFILE_DIR

    @property
    def cdp_url(self) -> str:
        return f"http://{DEFAULT_CDP_HOST}:{self.port}"


@dataclass(frozen=True)
class BrowserLaunchResult:
    executable: Path
    port: int
    profile_dir: Path
    process_id: int | None

    @property
    def cdp_url(self) -> str:
        return f"http://{DEFAULT_CDP_HOST}:{self.port}"


@dataclass(frozen=True)
class SnapshotArtifactPaths:
    screenshot_path: Path
    log_path: Path


@dataclass(frozen=True)
class PreparedPage:
    context: object
    page: object
    owns_context: bool


def resolve_browser_binary() -> Path:
    for candidate in BROWSER_CANDIDATES:
        if candidate.exists():
            return candidate
    raise BrowseError(
        "Could not find Google Chrome or Chromium in standard macOS locations. "
        "Install Chrome/Chromium in /Applications, then retry `browse chrome`."
    )


def build_snapshot_paths(output: str | Path) -> SnapshotArtifactPaths:
    screenshot_path = Path(output).expanduser().resolve()
    return SnapshotArtifactPaths(
        screenshot_path=screenshot_path,
        log_path=Path(f"{screenshot_path}{LOG_SUFFIX}"),
    )


def is_port_open(port: int, host: str = DEFAULT_CDP_HOST, timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def launch_browser(config: BrowserLaunchConfig) -> BrowserLaunchResult:
    executable = resolve_browser_binary()
    profile_dir = config.profile_dir.expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = [
        str(executable),
        f"--remote-debugging-port={config.port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "about:blank",
    ]

    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return BrowserLaunchResult(
        executable=executable,
        port=config.port,
        profile_dir=profile_dir,
        process_id=process.pid,
    )


def connect_over_cdp(
    port: int,
    *,
    sync_playwright_factory: Callable[[], object] | None = None,
):
    if sync_playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowseError(
                "Playwright is not importable. Reinstall `browse` and rerun `browse install`."
            ) from exc

        sync_playwright_factory = sync_playwright

    cdp_url = f"http://{DEFAULT_CDP_HOST}:{port}"
    manager = None
    try:
        manager = sync_playwright_factory()
        playwright = manager.__enter__()
        browser = playwright.chromium.connect_over_cdp(cdp_url)
    except Exception as exc:  # pragma: no cover - exercised through unit tests with mocks
        if manager is not None:
            manager.__exit__(*sys.exc_info())
        raise BrowseError(
            f"Could not connect to Chrome DevTools at {cdp_url}. "
            "Run `browse chrome`, keep that browser window open, then retry."
        ) from exc

    return manager, browser


def prepare_page(browser, url: str) -> PreparedPage:
    owns_context = not browser.contexts
    context = browser.contexts[0] if browser.contexts else browser.new_context(viewport=DEFAULT_VIEWPORT)
    page = context.new_page()
    page.set_viewport_size(DEFAULT_VIEWPORT)
    page.goto(url, wait_until="networkidle")
    return PreparedPage(context=context, page=page, owns_context=owns_context)


def cleanup_prepared_page(prepared_page: PreparedPage) -> None:
    if prepared_page.owns_context:
        prepared_page.context.close()
    else:
        prepared_page.page.close()


def open_page(url: str, port: int) -> str:
    manager, browser = connect_over_cdp(port)
    try:
        prepared_page = prepare_page(browser, url)
        return prepared_page.page.url
    finally:
        manager.__exit__(None, None, None)


def _log_event(log_lines: list[str], kind: str, message: str) -> None:
    log_lines.append(f"[{kind}] {message}")


def run_snapshot(url: str, output: str | Path, actions: list[tuple[str, object]], port: int, full_page: bool) -> SnapshotArtifactPaths:
    artifact_paths = build_snapshot_paths(output)
    artifact_paths.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = [f"[info] URL: {url}", f"[info] Output: {artifact_paths.screenshot_path}"]

    manager, browser = connect_over_cdp(port)
    prepared_page = None
    try:
        _log_event(log_lines, "step", f"0. goto {url}")
        prepared_page = prepare_page(browser, url)
        page = prepared_page.page

        page.on("console", lambda msg: _log_event(log_lines, f"console:{msg.type}", msg.text))
        page.on("pageerror", lambda exc: _log_event(log_lines, "pageerror", str(exc)))
        page.on(
            "requestfailed",
            lambda request: _log_event(
                log_lines,
                "requestfailed",
                f"{request.method} {request.url} -> {request.failure.error_text if request.failure else 'unknown error'}",
            ),
        )

        for index, (action_name, payload) in enumerate(actions, start=1):
            _log_event(log_lines, "step", f"{index}. {action_name} {payload}")
            try:
                if action_name == "wait-for":
                    page.wait_for_selector(str(payload))
                elif action_name == "click":
                    page.locator(str(payload)).click()
                elif action_name == "fill":
                    selector, value = payload
                    page.locator(str(selector)).fill(str(value))
                elif action_name == "sleep-ms":
                    page.wait_for_timeout(int(payload))
                else:  # pragma: no cover - parser constrains action names
                    raise BrowseError(f"Unsupported action: {action_name}")
            except Exception as exc:
                _log_event(log_lines, "error", f"Step {index} failed: {exc}")
                raise BrowseError(f"Snapshot action failed at step {index}: {action_name} {payload}") from exc

        page.screenshot(path=str(artifact_paths.screenshot_path), full_page=full_page)
        _log_event(log_lines, "info", f"Wrote screenshot to {artifact_paths.screenshot_path}")
    except Exception:
        artifact_paths.log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        raise
    else:
        artifact_paths.log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        return artifact_paths
    finally:
        if prepared_page is not None:
            cleanup_prepared_page(prepared_page)
        manager.__exit__(None, None, None)


def install_playwright_chromium() -> None:
    try:
        __import__("playwright")
    except ImportError as exc:
        raise BrowseError(
            "Playwright is not installed in this Python environment. Reinstall `browse` first."
        ) from exc

    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BrowseError("`playwright install chromium` failed.") from exc
