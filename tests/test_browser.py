from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browse.browser import (
    BrowserLaunchConfig,
    BrowseError,
    build_snapshot_paths,
    connect_over_cdp,
    launch_browser,
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

    @mock.patch("browse.browser.resolve_browser_binary")
    @mock.patch("browse.browser.subprocess.Popen")
    def test_launch_browser_uses_isolated_profile_dir(self, mock_popen, mock_resolve):
        mock_resolve.return_value = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        mock_popen.return_value.pid = 12345

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            result = launch_browser(BrowserLaunchConfig(port=9333, profile_dir=profile_dir))

        self.assertEqual(result.port, 9333)
        self.assertEqual(result.process_id, 12345)
        self.assertIn("--remote-debugging-port=9333", mock_popen.call_args.args[0])
        self.assertIn(f"--user-data-dir={profile_dir.resolve()}", mock_popen.call_args.args[0])

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
