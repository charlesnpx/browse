from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
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


def ensure_playwright_importable() -> None:
    try:
        __import__("playwright.sync_api")
    except ImportError as exc:
        raise BrowseError(
            "Playwright is not installed in this Python environment. Reinstall `browse` first."
        ) from exc


def resolve_browser_binary() -> Path:
    for candidate in BROWSER_CANDIDATES:
        if candidate.exists():
            return candidate
    raise BrowseError(
        "Could not find Google Chrome or Chromium in standard macOS locations. "
        "Install Chrome/Chromium in /Applications, or run `browse install --bundled-chromium` as a fallback."
    )


def verify_browser_runtime(*, install_bundled_chromium: bool = False) -> Path | None:
    """Ensure Playwright + Chromium are ready for `browse chrome`.

    Always installs Playwright's bundled Chromium (idempotent) — that's what
    `browse chrome` launches via `launch_persistent_context`, so we can't rely
    on the user's installed Chrome.app. The `install_bundled_chromium` flag is
    kept for back-compat but is now a no-op (Chromium is always installed).

    Returns the path to a system Chrome/Chromium if one is present (purely
    informational — the system browser isn't used by `browse chrome` anymore).
    """
    del install_bundled_chromium
    ensure_playwright_importable()
    install_playwright_chromium()
    try:
        return resolve_browser_binary()
    except BrowseError:
        return None


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


def find_chrome_pids_using_profile(profile_dir: Path) -> list[int]:
    profile_str = str(profile_dir)
    try:
        result = subprocess.run(
            ["pgrep", "-af", f"user-data-dir={profile_str}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        )
    except Exception:
        return []
    stdout = getattr(result, "stdout", "") or ""
    pids: list[int] = []
    for line in stdout.splitlines():
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            pids.append(int(parts[0]))
        except ValueError:
            continue
    return pids


def profile_dir_status(profile_dir: Path) -> dict[str, object]:
    resolved = profile_dir.expanduser().resolve()
    info: dict[str, object] = {
        "profile_dir": str(resolved),
        "exists": resolved.exists(),
    }
    if resolved.exists():
        cookies = resolved / "Default" / "Cookies"
        info["cookies_path"] = str(cookies)
        info["cookies_exists"] = cookies.exists()
        if cookies.exists():
            try:
                stat = cookies.stat()
                info["cookies_size"] = stat.st_size
                info["cookies_mtime"] = stat.st_mtime
            except OSError:
                pass
    info["chrome_pids"] = find_chrome_pids_using_profile(resolved)
    return info


def launch_browser(config: BrowserLaunchConfig) -> BrowserLaunchResult:
    """Launch Chromium via Playwright's persistent context and block until it closes.

    Returns a `BrowserLaunchResult` only after the browser has exited cleanly. Use
    `launch_persistent_context_handle` if you need non-blocking access to the
    context object (e.g. tests).
    """
    handle = launch_persistent_context_handle(config)
    try:
        handle.wait_until_closed()
    except KeyboardInterrupt:
        pass
    finally:
        handle.close()
    return BrowserLaunchResult(
        executable=Path("chromium"),
        port=config.port,
        profile_dir=handle.profile_dir,
        process_id=handle.process_id,
    )


@dataclass
class _PersistentContextHandle:
    playwright: object
    context: object
    profile_dir: Path
    config: BrowserLaunchConfig
    process_id: int | None = None
    _closed: bool = False

    def wait_until_closed(self) -> None:
        closed_event = {"flag": False}

        def _on_close(_ctx) -> None:
            closed_event["flag"] = True

        try:
            self.context.on("close", _on_close)
        except Exception:
            pass

        try:
            while not closed_event["flag"]:
                try:
                    _ = self.context.pages
                except Exception:
                    break
                time.sleep(0.5)
        finally:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.context.close()
        except Exception:
            pass
        try:
            self.playwright.stop()
        except Exception:
            pass


def launch_persistent_context_handle(
    config: BrowserLaunchConfig,
    *,
    sync_playwright_factory: Callable[[], object] | None = None,
) -> _PersistentContextHandle:
    profile_dir = config.profile_dir.expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    existing_pids = find_chrome_pids_using_profile(profile_dir)
    if existing_pids:
        sys.stderr.write(
            f"warning: A browser is already running with profile {profile_dir} "
            f"(PID(s): {', '.join(str(p) for p in existing_pids)}). "
            "Run `browse chrome --cleanup` to terminate it, then retry.\n"
        )

    if sync_playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowseError(
                "Playwright is not importable. Reinstall `browse` and rerun `browse install`."
            ) from exc
        sync_playwright_factory = sync_playwright

    playwright = None
    try:
        playwright = sync_playwright_factory().start()
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport=DEFAULT_VIEWPORT,
            ignore_default_args=["--remote-debugging-pipe"],
            args=[
                f"--remote-debugging-port={config.port}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=ProfilePicker,SigninFlowFollowsUITheme",
                "--password-store=basic",
            ],
        )
    except Exception as exc:
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        detail = str(exc).strip() or exc.__class__.__name__
        hint = ""
        if "Executable doesn't exist" in detail or "playwright install" in detail.lower():
            hint = "\nRun `browse install` (or `python -m playwright install chromium`) to download Playwright's Chromium."
        raise BrowseError(
            f"Could not launch Chromium via Playwright: {detail}{hint}"
        ) from exc

    if not context.pages:
        try:
            context.new_page()
        except Exception:
            pass

    process_id: int | None = None
    try:
        browser_proc = getattr(getattr(context, "browser", None), "process", None)
        if browser_proc is not None:
            process_id = getattr(browser_proc, "pid", None)
    except Exception:
        process_id = None

    return _PersistentContextHandle(
        playwright=playwright,
        context=context,
        profile_dir=profile_dir,
        config=config,
        process_id=process_id,
    )


def cleanup_browse_chrome_processes(profile_dir: Path) -> dict[str, object]:
    """SIGTERM (then SIGKILL) any Chrome processes referencing the browse profile."""
    import signal as _signal

    profile_dir = profile_dir.expanduser().resolve()
    pids = find_chrome_pids_using_profile(profile_dir)
    terminated: list[int] = []
    failed: list[dict[str, object]] = []

    for pid in pids:
        try:
            os.kill(pid, _signal.SIGTERM)
            terminated.append(pid)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            failed.append({"pid": pid, "error": str(exc)})

    if terminated:
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if not find_chrome_pids_using_profile(profile_dir):
                break
            time.sleep(0.2)

    remaining = find_chrome_pids_using_profile(profile_dir)
    for pid in remaining:
        try:
            os.kill(pid, _signal.SIGKILL)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            failed.append({"pid": pid, "error": str(exc)})

    final = find_chrome_pids_using_profile(profile_dir)
    return {
        "profile_dir": str(profile_dir),
        "terminated_pids": terminated,
        "remaining_pids": final,
        "failed": failed,
    }


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
    ensure_playwright_importable()
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BrowseError("`playwright install chromium` failed.") from exc
    if sys.platform == "darwin":
        _dequarantine_playwright_chromium()


def _dequarantine_playwright_chromium() -> None:
    """Remove macOS Gatekeeper quarantine from Playwright's Chromium binary.

    Without this, the first launch is SIGTRAP-killed by the OS before Playwright
    can take ownership; the dialog "open or ignore?" appears and even after
    clicking Reopen, the process is dead and Playwright bails with EPERM. We
    strip `com.apple.quarantine` recursively from the ms-playwright cache so
    every Chromium launch is clean.
    """
    cache_root = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache_root.exists():
        return
    try:
        subprocess.run(
            ["xattr", "-dr", "com.apple.quarantine", str(cache_root)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
        )
    except Exception:
        pass
