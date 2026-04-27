from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from browse import cli


class CliParsingTest(unittest.TestCase):
    def test_snapshot_preserves_ordered_actions(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "snapshot",
                "http://localhost:3000",
                "--output",
                "/tmp/page.png",
                "--fill",
                "#email",
                "dev@example.com",
                "--click",
                "button[type=submit]",
                "--wait-for",
                "#home",
                "--sleep-ms",
                "500",
            ]
        )

        self.assertEqual(
            args.actions,
            [
                ("fill", ("#email", "dev@example.com")),
                ("click", "button[type=submit]"),
                ("wait-for", "#home"),
                ("sleep-ms", 500),
            ],
        )

    @mock.patch("browse.cli.install_skills", return_value=["Codex skill       -> /tmp/skill"])
    @mock.patch("browse.cli.install_playwright_chromium")
    def test_init_orchestrates_install_and_skill_install(self, mock_install, mock_install_skills):
        result = cli.cmd_init(None)

        mock_install.assert_called_once_with()
        mock_install_skills.assert_called_once_with()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Ready to use:", result.message)
        self.assertIn("browse chrome", result.message)

    @mock.patch("browse.cli.install_skills", return_value=[])
    def test_install_skills_uses_friendly_no_cli_message(self, _mock_install_skills):
        result = cli.cmd_install_skills(None)
        self.assertEqual(result.message, cli.NO_SUPPORTED_CLIS_MESSAGE)

    @mock.patch("browse.cli.run_snapshot")
    def test_snapshot_command_reports_output_paths(self, mock_run_snapshot):
        mock_run_snapshot.return_value = mock.Mock(
            screenshot_path="/tmp/page.png",
            log_path="/tmp/page.png.log",
        )

        result = cli.cmd_snapshot(
            mock.Mock(
                url="http://localhost:3000",
                output="/tmp/page.png",
                actions=[],
                port=9222,
                full_page=True,
            )
        )

        self.assertIn("/tmp/page.png", result.message)
        self.assertIn("/tmp/page.png.log", result.message)

    @mock.patch("browse.cli.cmd_open", side_effect=cli.BrowseError("Run `browse chrome` first."))
    def test_main_returns_nonzero_for_user_facing_errors(self, _mock_cmd_open):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(["open", "http://localhost:3000"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Run `browse chrome` first.", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

