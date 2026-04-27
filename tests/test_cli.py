from __future__ import annotations

import io
import json
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

    def test_snapshot_allows_omitting_url(self):
        parser = cli.build_parser()
        args = parser.parse_args(["snapshot", "--output", "/tmp/page.png"])
        self.assertIsNone(args.url)

    def test_new_daemon_commands_parse(self):
        parser = cli.build_parser()
        args = parser.parse_args(["choose", "target-1", "Completed", "--if-version", "4"])
        self.assertEqual(args.target_id, "target-1")
        self.assertEqual(args.text, "Completed")
        self.assertEqual(args.if_version, 4)

    @mock.patch("browse.cli.save_config")
    @mock.patch("browse.cli.prompt_for_config")
    @mock.patch("browse.cli.config_exists", return_value=False)
    @mock.patch("browse.cli.install_skills", return_value=["Codex skill       -> /tmp/skill"])
    @mock.patch("browse.cli.verify_browser_runtime")
    def test_init_orchestrates_install_skill_install_and_first_run_config(
        self,
        mock_verify_runtime,
        mock_install_skills,
        _mock_config_exists,
        mock_prompt_for_config,
        mock_save_config,
    ):
        mock_verify_runtime.return_value = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        mock_prompt_for_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:4000",
            chrome_port=9555,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        mock_save_config.return_value = Path("/tmp/config.json")

        result = cli.cmd_init(mock.Mock(bundled_chromium=False))

        mock_verify_runtime.assert_called_once_with(install_bundled_chromium=False)
        mock_install_skills.assert_called_once_with()
        mock_prompt_for_config.assert_called_once_with(None)
        mock_save_config.assert_called_once()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("browse session start", result.message)
        self.assertIn("browse inspect", result.message)
        self.assertIn("browse open http://localhost:4000", result.message)

    @mock.patch("browse.cli.load_config")
    @mock.patch("browse.cli.config_exists", return_value=True)
    @mock.patch("browse.cli.install_skills", return_value=["Codex skill       -> /tmp/skill"])
    @mock.patch("browse.cli.verify_browser_runtime")
    def test_init_skips_prompt_when_config_exists(
        self,
        mock_verify_runtime,
        mock_install_skills,
        _mock_config_exists,
        mock_load_config,
    ):
        mock_verify_runtime.return_value = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:3000",
            chrome_port=9222,
            chrome_profile_dir=Path("/tmp/profile"),
        )

        result = cli.cmd_init(mock.Mock(bundled_chromium=False))

        mock_verify_runtime.assert_called_once_with(install_bundled_chromium=False)
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

    @mock.patch("browse.cli.send_request")
    @mock.patch("browse.cli.ensure_daemon_running")
    @mock.patch("browse.cli.load_config")
    def test_open_uses_configured_url_and_port(self, mock_load_config, mock_ensure_daemon_running, mock_send_request):
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:4000",
            chrome_port=9444,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        mock_send_request.return_value = {"ok": True, "command": "open", "url": "http://localhost:4000"}

        result = cli.cmd_open(mock.Mock(url=None, port=None, if_version=None))

        mock_ensure_daemon_running.assert_called_once_with(9444)
        mock_send_request.assert_called_once_with(9444, "open", {"url": "http://localhost:4000", "if_version": None})
        self.assertEqual(result.data["command"], "open")

    @mock.patch("browse.cli.send_request")
    @mock.patch("browse.cli.ensure_daemon_running")
    @mock.patch("browse.cli.load_config")
    def test_snapshot_navigates_then_screenshots(self, mock_load_config, mock_ensure_daemon_running, mock_send_request):
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:4000",
            chrome_port=9444,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        mock_send_request.side_effect = [
            {"ok": True, "command": "open", "page_id": "page-1"},
            {"ok": True, "command": "screenshot", "output": "/tmp/page.png"},
        ]

        result = cli.cmd_snapshot(
            mock.Mock(
                url="http://localhost:5000",
                output="/tmp/page.png",
                port=9666,
                full_page=True,
                if_version=7,
            )
        )

        self.assertEqual(result.data["command"], "screenshot")
        self.assertEqual(
            mock_send_request.call_args_list,
            [
                mock.call(9666, "open", {"url": "http://localhost:5000", "if_version": 7}),
                mock.call(9666, "screenshot", {"output": "/tmp/page.png", "full_page": True, "if_version": None}),
            ],
        )
        self.assertEqual(mock_ensure_daemon_running.call_count, 2)

    @mock.patch("browse.cli.send_request", return_value={"ok": True, "command": "status", "pid": 1})
    @mock.patch("browse.cli.ensure_daemon_running", return_value={"ok": True, "command": "status", "pid": 1})
    @mock.patch("browse.cli.load_config")
    def test_main_prints_json_for_daemon_commands(self, mock_load_config, _mock_ensure_daemon_running, _mock_send_request):
        mock_load_config.return_value = cli.BrowseConfig(
            base_url="http://localhost:3000",
            chrome_port=9222,
            chrome_profile_dir=Path("/tmp/profile"),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(["session", "status"])

        self.assertEqual(exit_code, 0)
        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["command"], "status")
        self.assertEqual(parsed["pid"], 1)
        self.assertEqual(stderr.getvalue(), "")

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
