from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from browse.browser import BrowseError, DEFAULT_PORT, DEFAULT_PROFILE_DIR


DEFAULT_BASE_URL = "http://localhost:3000"
DEFAULT_CONFIG_PATH = Path.home() / ".browse" / "config.json"


@dataclass(frozen=True)
class BrowseConfig:
    base_url: str = DEFAULT_BASE_URL
    chrome_port: int = DEFAULT_PORT
    chrome_profile_dir: Path = DEFAULT_PROFILE_DIR


def config_path() -> Path:
    return DEFAULT_CONFIG_PATH


def config_exists() -> bool:
    return config_path().exists()


def validate_base_url(value: str) -> str:
    candidate = value.strip()
    parsed = urlparse(candidate)
    if not parsed.scheme or not parsed.netloc:
        raise BrowseError("Base URL must include a scheme and host, for example `http://localhost:3000`.")
    return candidate


def validate_port(value: int | str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise BrowseError("Chrome port must be an integer.") from exc

    if not (1 <= port <= 65535):
        raise BrowseError("Chrome port must be between 1 and 65535.")
    return port


def validate_profile_dir(value: str | Path) -> Path:
    text = str(value).strip()
    if not text:
        raise BrowseError("Chrome profile dir cannot be empty.")
    return Path(text).expanduser()


def default_config() -> BrowseConfig:
    return BrowseConfig()


def load_config() -> BrowseConfig:
    path = config_path()
    if not path.exists():
        return default_config()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrowseError(
            f"Could not read browse config at {path}. Run `browse config` to recreate it."
        ) from exc

    if not isinstance(data, dict):
        raise BrowseError(f"Browse config at {path} is invalid. Run `browse config` to recreate it.")

    try:
        return BrowseConfig(
            base_url=validate_base_url(data.get("base_url", DEFAULT_BASE_URL)),
            chrome_port=validate_port(data.get("chrome_port", DEFAULT_PORT)),
            chrome_profile_dir=validate_profile_dir(data.get("chrome_profile_dir", str(DEFAULT_PROFILE_DIR))),
        )
    except BrowseError as exc:
        raise BrowseError(f"Browse config at {path} is invalid: {exc} Run `browse config` to fix it.") from exc


def save_config(config: BrowseConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": validate_base_url(config.base_url),
        "chrome_port": validate_port(config.chrome_port),
        "chrome_profile_dir": str(validate_profile_dir(config.chrome_profile_dir)),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def prompt_for_config(existing: BrowseConfig | None = None, input_func=input, output_func=print) -> BrowseConfig:
    current = existing or default_config()

    base_url = _prompt_until_valid(
        "Base URL",
        current.base_url,
        validate_base_url,
        input_func=input_func,
        output_func=output_func,
    )
    chrome_port = _prompt_until_valid(
        "Chrome remote debugging port",
        str(current.chrome_port),
        validate_port,
        input_func=input_func,
        output_func=output_func,
    )
    chrome_profile_dir = _prompt_until_valid(
        "Chrome profile dir",
        str(current.chrome_profile_dir),
        validate_profile_dir,
        input_func=input_func,
        output_func=output_func,
    )

    return BrowseConfig(
        base_url=base_url,
        chrome_port=chrome_port,
        chrome_profile_dir=chrome_profile_dir,
    )


def _prompt_until_valid(label: str, default_value: str, validator, *, input_func=input, output_func=print):
    while True:
        raw = input_func(f"{label} [{default_value}]: ").strip()
        candidate = raw or default_value
        try:
            return validator(candidate)
        except BrowseError as exc:
            output_func(f"Invalid {label.lower()}: {exc}")

