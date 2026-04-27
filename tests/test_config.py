from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browse.browser import DEFAULT_PORT, BrowseError
from browse.config import (
    BrowseConfig,
    DEFAULT_BASE_URL,
    default_config,
    load_config,
    prompt_for_config,
    save_config,
    validate_base_url,
    validate_port,
    validate_profile_dir,
)


class ConfigTest(unittest.TestCase):
    def test_default_config_matches_expected_defaults(self):
        config = default_config()
        self.assertEqual(config.base_url, DEFAULT_BASE_URL)
        self.assertEqual(config.chrome_port, DEFAULT_PORT)

    def test_validate_base_url_requires_scheme_and_host(self):
        self.assertEqual(validate_base_url("http://localhost:3000"), "http://localhost:3000")
        with self.assertRaisesRegex(BrowseError, "scheme and host"):
            validate_base_url("localhost:3000")

    def test_validate_port_requires_valid_integer_range(self):
        self.assertEqual(validate_port("9222"), 9222)
        with self.assertRaisesRegex(BrowseError, "between 1 and 65535"):
            validate_port("70000")

    def test_validate_profile_dir_expands_user(self):
        expanded = validate_profile_dir("~/browse-profile")
        self.assertTrue(str(expanded).endswith("browse-profile"))

    def test_save_and_load_config_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_config_path = Path(tmpdir) / "config.json"
            config = BrowseConfig(
                base_url="http://localhost:4000",
                chrome_port=9333,
                chrome_profile_dir=Path("~/tmp-profile"),
            )

            with mock.patch("browse.config.DEFAULT_CONFIG_PATH", temp_config_path):
                save_config(config)
                loaded = load_config()

            self.assertEqual(loaded.base_url, "http://localhost:4000")
            self.assertEqual(loaded.chrome_port, 9333)
            self.assertTrue(str(loaded.chrome_profile_dir).endswith("tmp-profile"))

    def test_load_config_reports_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_config_path = Path(tmpdir) / "config.json"
            temp_config_path.write_text("{broken", encoding="utf-8")

            with mock.patch("browse.config.DEFAULT_CONFIG_PATH", temp_config_path):
                with self.assertRaisesRegex(BrowseError, "Run `browse config` to recreate it"):
                    load_config()

    def test_prompt_for_config_reprompts_until_valid(self):
        prompts = iter(
            [
                "localhost:3000",
                "http://localhost:4000",
                "abc",
                "9333",
                "",
            ]
        )
        output = io.StringIO()

        config = prompt_for_config(
            BrowseConfig(
                base_url="http://localhost:3000",
                chrome_port=9222,
                chrome_profile_dir=Path("/tmp/profile"),
            ),
            input_func=lambda _prompt: next(prompts),
            output_func=lambda line: print(line, file=output),
        )

        self.assertEqual(config.base_url, "http://localhost:4000")
        self.assertEqual(config.chrome_port, 9333)
        self.assertEqual(config.chrome_profile_dir, Path("/tmp/profile"))
        self.assertIn("Invalid base url", output.getvalue())
        self.assertIn("Invalid chrome remote debugging port", output.getvalue())


if __name__ == "__main__":
    unittest.main()
