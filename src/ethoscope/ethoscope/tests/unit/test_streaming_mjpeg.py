"""
Unit tests for the device-side MJPEG-over-HTTP streamer in ``record.py``.

The streamer serves a standard ``multipart/x-mixed-replace`` response so any HTTP client
(browser, OpenCV/Bonsai, the node proxy) can read frames with no Python-specific decoding.
These tests cover the encode-once/fan-out broadcast and the accept/serve socket flow,
without instantiating a real camera.
"""

import os
import queue
import socket
import threading
import time

import pytest

try:
    from ethoscope.control.record import (
        STREAM_BOUNDARY,
        STREAM_HTTP_HEADER,
        cameraCaptureThread,
    )
except ImportError:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
    from ethoscope.control.record import (
        STREAM_BOUNDARY,
        STREAM_HTTP_HEADER,
        cameraCaptureThread,
    )


def _make_streamer():
    """Build a cameraCaptureThread without running its camera-dependent __init__."""
    obj = cameraCaptureThread.__new__(cameraCaptureThread)
    obj.stop_camera_activity = False
    obj._stream = True
    obj._stream_server_socket = None
    obj._stream_clients = []
    obj._stream_lock = threading.Lock()
    return obj


def _make_mjpeg_part(jpg=b"\xff\xd8\xff\xd9"):
    """Build one MJPEG part exactly as the streamer does."""
    return (
        b"--"
        + STREAM_BOUNDARY
        + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
        + str(len(jpg)).encode()
        + b"\r\n\r\n"
        + jpg
        + b"\r\n"
    )


class TestBroadcast:
    """Frame fan-out semantics."""

    def test_broadcast_fans_out_to_all_clients(self):
        s = _make_streamer()
        q1, q2 = queue.Queue(maxsize=10), queue.Queue(maxsize=10)
        s._stream_clients = [(object(), q1), (object(), q2)]

        s._broadcast_stream_frame(b"chunk")

        assert q1.get_nowait() == b"chunk"
        assert q2.get_nowait() == b"chunk"

    def test_broadcast_drops_frame_for_full_queue(self):
        """A slow client (full queue) drops the frame instead of stalling the loop."""
        s = _make_streamer()
        full = queue.Queue(maxsize=1)
        full.put(b"old")
        s._stream_clients = [(object(), full)]

        s._broadcast_stream_frame(b"new")  # must not raise

        assert full.get_nowait() == b"old"  # the new frame was dropped
        assert full.empty()


class TestServerEndToEnd:
    """Accept + serve over a real loopback socket."""

    def test_client_receives_http_header_and_frame(self):
        s = _make_streamer()

        # Bind an ephemeral port ourselves to avoid the fixed STREAMING_PORT in tests.
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        port = server.getsockname()[1]
        s._stream_server_socket = server

        acceptor = threading.Thread(target=s._accept_stream_clients, daemon=True)
        acceptor.start()

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(5)
        try:
            client.connect(("127.0.0.1", port))
            client.sendall(b"GET / HTTP/1.0\r\n\r\n")

            # Wait for the client to be registered by the acceptor thread.
            deadline = time.time() + 5
            while not s._stream_clients and time.time() < deadline:
                time.sleep(0.01)
            assert s._stream_clients, "client was not registered"

            chunk = _make_mjpeg_part()
            s._broadcast_stream_frame(chunk)

            received = b""
            deadline = time.time() + 5
            while chunk not in received and time.time() < deadline:
                try:
                    data = client.recv(4096)
                except TimeoutError:
                    break
                if not data:
                    break
                received += data

            # Valid HTTP MJPEG response header...
            assert received.startswith(b"HTTP/1.0 200 OK")
            assert b"multipart/x-mixed-replace; boundary=" + STREAM_BOUNDARY in received
            # ...followed by the frame, with a real JPEG start-of-image marker.
            assert chunk in received
            assert b"\xff\xd8" in received
        finally:
            s.stop_camera_activity = True
            s._stop_stream_server()
            client.close()

    def test_stop_server_signals_clients_and_closes_socket(self):
        s = _make_streamer()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        s._stream_server_socket = server

        sentinel_q = queue.Queue(maxsize=10)
        s._stream_clients = [(object(), sentinel_q)]

        s._stop_stream_server()

        # Each client writer is told to stop via the None sentinel...
        assert sentinel_q.get_nowait() is None
        # ...and the server socket is released.
        assert s._stream_server_socket is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
