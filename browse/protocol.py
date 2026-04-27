from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from browse.browser import BrowseError, DEFAULT_PORT

DEFAULT_SESSION_DIR = Path.home() / ".browse"
SOCKET_TEMPLATE = "session-{port}.sock"


@dataclass(frozen=True)
class DaemonRequest:
    command: str
    params: dict[str, Any]


@dataclass(frozen=True)
class DaemonResponse:
    ok: bool
    command: str
    page_id: str | None = None
    state_version: int | None = None
    message: str | None = None
    error: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "ok": self.ok,
            "command": self.command,
        }
        if self.page_id is not None:
            data["page_id"] = self.page_id
        if self.state_version is not None:
            data["state_version"] = self.state_version
        if self.message is not None:
            data["message"] = self.message
        if self.error is not None:
            data["error"] = self.error
        if self.payload is not None:
            data.update(self.payload)
        return data


class DaemonClientError(BrowseError):
    """Raised when the CLI cannot talk to a running browse daemon."""


def session_socket_path(port: int = DEFAULT_PORT) -> Path:
    return DEFAULT_SESSION_DIR / SOCKET_TEMPLATE.format(port=port)


def encode_message(data: dict[str, Any]) -> bytes:
    return (json.dumps(data) + "\n").encode("utf-8")


def decode_message(data: bytes) -> dict[str, Any]:
    return json.loads(data.decode("utf-8"))


def json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return {key: json_safe(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {key: json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def send_request(port: int, command: str, params: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
    socket_path = session_socket_path(port)
    if not socket_path.exists():
        raise DaemonClientError(
            f"No browse session is running for port {port}. Run `browse session start` after `browse chrome`."
        )

    request = DaemonRequest(command=command, params=params or {})

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path))
            sock.sendall(encode_message(json_safe(asdict(request))))
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
    except FileNotFoundError as exc:
        raise DaemonClientError(
            f"No browse session is running for port {port}. Run `browse session start` after `browse chrome`."
        ) from exc
    except (socket.timeout, ConnectionError, OSError) as exc:
        raise DaemonClientError(
            f"Could not reach the browse session on port {port}. Run `browse session start` after `browse chrome`."
        ) from exc

    raw = b"".join(chunks).splitlines()[0] if chunks else b""
    if not raw:
        raise DaemonClientError("The browse session returned an empty response.")
    return decode_message(raw)
