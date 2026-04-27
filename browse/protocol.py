from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from browse.browser import BrowseError, DEFAULT_PORT

DEFAULT_SESSION_DIR = Path.home() / ".browse"
SOCKET_TEMPLATE = "session-{port}.sock"
DEFAULT_CLIENT_TIMEOUT_SECONDS = 60.0


def _resolve_timeout(timeout: float | None) -> float:
    if timeout is not None:
        return timeout
    raw = os.environ.get("BROWSE_TIMEOUT")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_CLIENT_TIMEOUT_SECONDS


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


def send_request(port: int, command: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
    effective_timeout = _resolve_timeout(timeout)
    socket_path = session_socket_path(port)
    if not socket_path.exists():
        raise DaemonClientError(
            f"No browse session is running for port {port}. Run `browse session start` after `browse chrome`."
        )

    request = DaemonRequest(command=command, params=params or {})

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(effective_timeout)
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
    except ConnectionRefusedError as exc:
        raise DaemonClientError(
            f"The browse session socket exists at port {port} but the daemon is not accepting connections. Run `browse session start`."
        ) from exc
    except socket.timeout as exc:
        raise DaemonClientError(
            f"The browse session did not respond within {effective_timeout:.0f}s on port {port}. "
            "The action may still be running in the daemon — set BROWSE_TIMEOUT=<seconds> to wait longer."
        ) from exc
    except OSError as exc:
        raise DaemonClientError(
            f"Lost connection while talking to the browse session on port {port}: {exc}."
        ) from exc

    raw = b"".join(chunks).splitlines()[0] if chunks else b""
    if not raw:
        raise DaemonClientError(
            f"The browse session on port {port} closed the connection without responding."
        )
    return decode_message(raw)
