#!/usr/bin/env python3
"""
Unit tests for the timeout on ``ethoclient.send_command``.

``device_server.py`` serves one request at a time and asks the listener for its
status on every one. ``send_command`` used to wait on the listener with no
timeout, so a single reply that never came wedged the whole web server: ``/id``
stopped answering, the node marked the device offline and hid it, while the
listener went on tracking. These tests run against real sockets.
"""

import json
import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))

from ethoclient import COMMAND_TIMEOUT, STOP_TIMEOUT, send_command  # noqa: E402


@pytest.fixture
def listener():
    """
    A local TCP server standing in for the device listener.

    Yields:
        callable: ``start(reply)`` binds a server that answers each connection
            with ``reply`` (bytes), or never answers when ``reply`` is None, and
            returns its port.
    """
    sockets = []
    stop = threading.Event()

    def start(reply):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(0.2)
        sockets.append(server)

        def serve():
            while not stop.is_set():
                try:
                    client, _ = server.accept()
                except OSError:
                    continue
                sockets.append(client)
                client.recv(1024)
                if reply is not None:
                    client.sendall(reply)
                    client.close()
                # Reason: with no reply the connection is left open, which is
                # exactly the listener that never answers.

        threading.Thread(target=serve, daemon=True).start()
        return server.getsockname()[1]

    yield start

    stop.set()
    for s in sockets:
        s.close()


def test_returns_the_listener_response(listener):
    """A listener that answers is read as before."""
    port = listener(json.dumps({"response": "running"}).encode())
    assert send_command("status", port=port) == "running"


def test_gives_up_on_a_silent_listener(listener):
    """A listener that never answers raises instead of blocking for ever."""
    port = listener(None)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        send_command("status", port=port, timeout=0.5)
    assert time.monotonic() - started < 3


def test_refused_connection_still_raises(listener):
    """No listener at all is still a plain connection error."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(ConnectionRefusedError):
        send_command("status", port=port)


def test_stop_is_allowed_longer_than_the_listener_join():
    """``stop`` waits up to 30 s on the listener's join, so its timeout must exceed it."""
    from device_listener import commandingThread

    assert STOP_TIMEOUT > commandingThread._STOP_JOIN_TIMEOUT
    assert COMMAND_TIMEOUT < STOP_TIMEOUT
