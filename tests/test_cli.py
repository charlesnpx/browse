from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from browse import cli


class CliParsingTest(unittest.TestCase):
    def test_open_allows_omitting_url(self):
        parser = cli.build_parser()
        args = parser.parse_args(["open"])
        self.assertIsNone(args.url)

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

        self.assertEqual(args.url, "http://localhost:3000")
        self.assertEqual(
            args.actions,
            [
                ("fill", ("#email", "dev@example.com")),
                ("click", "button[type=submit]"),
                ("wait-for", "#home"),
                ("sleep-ms", 500),
            ],
        )

    def test_snapshot_allows_omitting_url(self):
        parser = cli.build_parser()
        args = parser.parse_args(["snapshot", "--output", "/tmp/page.png"])
        self.assertIsNone(args.url)

    @mock.patch("browse.cli.save_config")
    @mock.patch("browse.cli.prompt_for_config")
    @mock.patch("browse.cli.config_exists", return_value=False)
    @mock.patch("browse.cli.install_skills", return_value=["Codex skill       -> /tmp/skill"])
    @mock.patch("browse.cli.install_playwright_chromium")
    def test_init_orchestrates_install_skill_install_and_first_run_config(
        self,
        mock_install,
        mock_install_skills,
        _mock_config_exists,
        mock_prompt_for_config,
        mock_save_config,
    ):
        mock_prompt_for_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:4000",
            chrome_port=9555,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        mock_save_config.return_value = Path("/tmp/config.json")

        result = cli.cmd_init(None)

        mock_install.assert_called_once_with()
        mock_install_skills.assert_called_once_with()
        mock_prompt_for_config.assert_called_once_with(None)
        mock_save_config.assert_called_once()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Ready to use:", result.message)
        self.assertIn("browse open http://localhost:4000", result.message)
        self.assertIn("browse snapshot --output /tmp/page.png", result.message)

    @mock.patch("browse.cli.load_config")
    @mock.patch("browse.cli.config_exists", return_value=True)
    @mock.patch("browse.cli.install_skills", return_value=["Codex skill       -> /tmp/skill"])
    @mock.patch("browse.cli.install_playwright_chromium")
    def test_init_skips_prompt_when_config_exists(
        self,
        mock_install,
        mock_install_skills,
        _mock_config_exists,
        mock_load_config,
    ):
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:3000",
            chrome_port=9222,
            chrome_profile_dir=Path("/tmp/profile"),
        )

        result = cli.cmd_init(None)

        mock_install.assert_called_once_with()
        mock_install_skills.assert_called_once_with()
        mock_load_config.assert_called_once_with()
        self.assertIn("Config already exists. Run `browse config` to update it.", result.message)

    @mock.patch("browse.cli.install_skills", return_value=[])
    def test_install_skills_uses_friendly_no_cli_message(self, _mock_install_skills):
        result = cli.cmd_install_skills(None)
        self.assertEqual(result.message, cli.NO_SUPPORTED_CLIS_MESSAGE)

    @mock.patch("browse.cli.save_config")
    @mock.patch("browse.cli.prompt_for_config")
    @mock.patch("browse.cli.load_config")
    @mock.patch("browse.cli.config_exists", return_value=True)
    def test_config_command_edits_existing_config(
        self,
        _mock_exists,
        mock_load_config,
        mock_prompt_for_config,
        mock_save_config,
    ):
        existing = cli.BrowseConfig(
            base_url="http://localhost:3000",
            chrome_port=9222,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        updated = cli.BrowseConfig(
            base_url="http://localhost:4000",
            chrome_port=9333,
            chrome_profile_dir=Path("/tmp/updated"),
        )
        mock_load_config.return_value = existing
        mock_prompt_for_config.return_value = updated
        mock_save_config.return_value = Path("/tmp/config.json")

        result = cli.cmd_config(None)

        mock_prompt_for_config.assert_called_once_with(existing)
        mock_save_config.assert_called_once_with(updated)
        self.assertIn("Saved browse config: /tmp/config.json", result.message)

    @mock.patch("browse.cli.load_config")
    def test_open_uses_configured_url_and_port(self, mock_load_config):
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:4000",
            chrome_port=9444,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        with mock.patch("browse.cli.open_page", return_value="http://localhost:4000") as mock_open_page:
            result = cli.cmd_open(mock.Mock(url=None, port=None))

        mock_open_page.assert_called_once_with("http://localhost:4000", 9444)
        self.assertIn("Opened http://localhost:4000", result.message)

    @mock.patch("browse.cli.load_config")
    def test_snapshot_cli_args_override_saved_config(self, mock_load_config):
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:4000",
            chrome_port=9444,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        with mock.patch("browse.cli.run_snapshot") as mock_run_snapshot:
            mock_run_snapshot.return_value = mock.Mock(
                screenshot_path="/tmp/page.png",
                log_path="/tmp/page.png.log",
            )
            cli.cmd_snapshot(
                mock.Mock(
                    url="http://localhost:5000",
                    output="/tmp/page.png",
                    actions=[],
                    port=9666,
                    full_page=True,
                )
            )

        mock_run_snapshot.assert_called_once_with("http://localhost:5000", "/tmp/page.png", [], 9666, True)

    @mock.patch("browse.cli.run_snapshot")
    @mock.patch("browse.cli.load_config")
    def test_snapshot_command_reports_output_paths(self, mock_load_config, mock_run_snapshot):
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:3000",
            chrome_port=9222,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        mock_run_snapshot.return_value = mock.Mock(
            screenshot_path="/tmp/page.png",
            log_path="/tmp/page.png.log",
        )

        result = cli.cmd_snapshot(
            mock.Mock(
                url=None,
                output="/tmp/page.png",
                actions=[],
                port=None,
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
