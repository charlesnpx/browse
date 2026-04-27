from __future__ import annotations

import socket
import unittest
from unittest import mock

from browse import protocol
from browse.protocol import DaemonClientError


class FakeSocket:
    def __init__(self, *, raise_on_connect=None, raise_on_send=None, response: bytes = b""):
        self._raise_on_connect = raise_on_connect
        self._raise_on_send = raise_on_send
        self._response = response
        self._sent = b""
        self.timeout: float | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, _addr):
        if self._raise_on_connect:
            raise self._raise_on_connect

    def sendall(self, data):
        if self._raise_on_send:
            raise self._raise_on_send
        self._sent += data

    def recv(self, _size):
        return self._response


class ProtocolTimeoutTest(unittest.TestCase):
    def setUp(self):
        socket_path = protocol.session_socket_path(9222)
        self._patch_exists = mock.patch.object(protocol.Path, "exists", return_value=True)
        self._patch_exists.start()
        self.addCleanup(self._patch_exists.stop)

    def test_socket_timeout_message_distinguishes_from_session_down(self):
        fake = FakeSocket(raise_on_send=socket.timeout())
        with mock.patch.object(protocol.socket, "socket", return_value=fake):
            with self.assertRaises(DaemonClientError) as exc:
                protocol.send_request(9222, "click", {}, timeout=2.5)

        self.assertIn("did not respond within", str(exc.exception))
        self.assertIn("BROWSE_TIMEOUT", str(exc.exception))

    def test_connection_refused_message_indicates_daemon_not_accepting(self):
        fake = FakeSocket(raise_on_connect=ConnectionRefusedError())
        with mock.patch.object(protocol.socket, "socket", return_value=fake):
            with self.assertRaises(DaemonClientError) as exc:
                protocol.send_request(9222, "click", {})

        self.assertIn("not accepting connections", str(exc.exception))

    def test_default_timeout_is_60s(self):
        self.assertEqual(protocol._resolve_timeout(None), 60.0)

    def test_browse_timeout_env_var_overrides_default(self):
        with mock.patch.dict("os.environ", {"BROWSE_TIMEOUT": "12"}, clear=False):
            self.assertEqual(protocol._resolve_timeout(None), 12.0)

    def test_browse_timeout_env_var_ignores_invalid_value(self):
        with mock.patch.dict("os.environ", {"BROWSE_TIMEOUT": "not-a-number"}, clear=False):
            self.assertEqual(protocol._resolve_timeout(None), 60.0)


if __name__ == "__main__":
    unittest.main()
