from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browse.browser import (
    BrowserLaunchConfig,
    BrowseError,
    build_snapshot_paths,
    cleanup_browse_chrome_processes,
    connect_over_cdp,
    launch_persistent_context_handle,
    resolve_browser_binary,
    verify_browser_runtime,
)


class BrowserHelpersTest(unittest.TestCase):
    def test_build_snapshot_paths_appends_log_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = build_snapshot_paths(Path(tmpdir) / "page.png")
            self.assertTrue(str(artifacts.screenshot_path).endswith("page.png"))
            self.assertEqual(str(artifacts.log_path), f"{artifacts.screenshot_path}.log")

    @mock.patch("browse.browser.BROWSER_CANDIDATES", [Path("/missing/browser")])
    def test_resolve_browser_binary_raises_friendly_error(self):
        with self.assertRaises(BrowseError) as exc:
            resolve_browser_binary()

        self.assertIn("Could not find Google Chrome or Chromium", str(exc.exception))

    @mock.patch("browse.browser.find_chrome_pids_using_profile", return_value=[])
    def test_launch_persistent_context_uses_user_data_dir_and_pipe_transport(self, _mock_pids):
        fake_context = mock.Mock()
        fake_context.pages = []
        fake_chromium = mock.Mock()
        fake_chromium.launch_persistent_context.return_value = fake_context
        fake_pw = mock.Mock(chromium=fake_chromium)
        fake_pw_handle = mock.Mock()
        fake_pw_handle.start.return_value = fake_pw

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            handle = launch_persistent_context_handle(
                BrowserLaunchConfig(port=9333, profile_dir=profile_dir),
                sync_playwright_factory=mock.Mock(return_value=fake_pw_handle),
            )

        kwargs = fake_chromium.launch_persistent_context.call_args.kwargs
        self.assertEqual(kwargs["user_data_dir"], str(profile_dir.resolve()))
        self.assertFalse(kwargs["headless"])
        # No --remote-debugging-port: Playwright drives via its default pipe transport;
        # the daemon attaches in-process via the persistent context, not via CDP TCP.
        self.assertFalse(any("remote-debugging-port" in arg for arg in kwargs["args"]))
        fake_context.new_page.assert_called_once_with()
        self.assertIs(handle.context, fake_context)

    @mock.patch("browse.browser.find_chrome_pids_using_profile", return_value=[7777])
    def test_launch_persistent_context_warns_when_existing_chrome_uses_profile(self, _mock_pids):
        fake_context = mock.Mock()
        fake_context.pages = []
        fake_chromium = mock.Mock()
        fake_chromium.launch_persistent_context.return_value = fake_context
        fake_pw = mock.Mock(chromium=fake_chromium)
        fake_pw_handle = mock.Mock()
        fake_pw_handle.start.return_value = fake_pw

        captured: list[str] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            with mock.patch("sys.stderr") as fake_stderr:
                fake_stderr.write.side_effect = lambda s: captured.append(s)
                launch_persistent_context_handle(
                    BrowserLaunchConfig(port=9333, profile_dir=profile_dir),
                    sync_playwright_factory=mock.Mock(return_value=fake_pw_handle),
                )

        self.assertTrue(any("7777" in s and "--cleanup" in s for s in captured))

    @mock.patch("browse.browser.time.sleep", return_value=None)
    @mock.patch("browse.browser.os.kill")
    @mock.patch("browse.browser.find_chrome_pids_using_profile")
    def test_cleanup_browse_chrome_processes_terminates_then_kills_remaining(self, mock_find, mock_kill, _mock_sleep):
        # 1: initial scan; 2: post-SIGTERM still has 200; 3: still 200 → break;
        # 4: SIGKILL loop scan; 5: final scan after kill.
        call_results = [
            [100, 200, 300],
            [200],
            [],
            [200],
            [],
        ]
        mock_find.side_effect = lambda _profile_dir: call_results.pop(0) if call_results else []

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            profile_dir.mkdir()
            result = cleanup_browse_chrome_processes(profile_dir)

        sigterm_calls = [c for c in mock_kill.call_args_list if c.args[1] == 15]
        sigkill_calls = [c for c in mock_kill.call_args_list if c.args[1] == 9]
        self.assertEqual({c.args[0] for c in sigterm_calls}, {100, 200, 300})
        self.assertEqual({c.args[0] for c in sigkill_calls}, {200})
        self.assertEqual(result["terminated_pids"], [100, 200, 300])
        self.assertEqual(result["remaining_pids"], [])

    def test_connect_over_cdp_raises_friendly_error(self):
        manager = mock.Mock()
        manager.__enter__ = mock.Mock(return_value=mock.Mock(chromium=mock.Mock(connect_over_cdp=mock.Mock(side_effect=RuntimeError("boom")))))
        manager.__exit__ = mock.Mock(return_value=False)

        with self.assertRaises(BrowseError) as exc:
            connect_over_cdp(9222, sync_playwright_factory=mock.Mock(return_value=manager))

        self.assertIn("Run `browse chrome`", str(exc.exception))

    @mock.patch("browse.browser.install_playwright_chromium")
    @mock.patch("browse.browser.resolve_browser_binary", side_effect=BrowseError("missing"))
    @mock.patch("browse.browser.ensure_playwright_importable")
    def test_verify_browser_runtime_can_install_bundled_chromium(
        self,
        mock_importable,
        _mock_resolve,
        mock_install,
    ):
        result = verify_browser_runtime(install_bundled_chromium=True)
        self.assertIsNone(result)
        mock_importable.assert_called_once_with()
        mock_install.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
