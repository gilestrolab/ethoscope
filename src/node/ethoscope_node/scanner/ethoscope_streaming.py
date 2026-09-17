"""
Ethoscope streaming management module.

This module provides connection sharing and multi-client streaming capabilities
for Ethoscope devices using a simple, HTTP-compatible approach.
"""

import errno
import logging
import queue
import socket
import time
from collections.abc import Iterator
from threading import RLock, Thread

# Import the streaming port constant
STREAMING_PORT = 8887


class StreamUnavailable(RuntimeError):
    """
    The device is not serving a stream this node can relay.

    Raised while opening the connection, so the caller can answer the browser
    with a readable reason instead of a response that never produces a frame.
    """


class EthoscopeStreamManager:
    """
    Manages shared streaming connection for an Ethoscope device.

    Provides multi-client streaming support by maintaining a single TCP connection
    to the device and broadcasting frames to multiple HTTP clients via queues.
    """

    def __init__(self, device_ip: str, device_id: str):
        """
        Initialize stream manager for an Ethoscope device.

        Args:
            device_ip: IP address of the Ethoscope device
            device_id: Unique identifier for the device
        """
        self.device_ip = device_ip
        self.device_id = device_id

        # Connection state
        self._shared_socket = None
        self._streaming_clients = {}  # client_id -> queue
        self._streaming_thread = None
        self._streaming_lock = RLock()
        self._streaming_running = False
        self._next_client_id = 0

        # Logging
        self._logger = logging.getLogger(f"StreamManager_{device_id}")

    def get_stream_for_client(self) -> Iterator[bytes]:
        """
        Open the shared connection and return a frame iterator for one client.

        The connection is opened here rather than inside the generator so that a
        device which cannot be streamed fails now, while the caller can still turn
        it into a readable HTTP error. Left inside the generator, the failure only
        surfaced once the response had already been committed, and the browser got
        a stream that simply never produced a frame.

        Returns:
            Iterator[bytes]: the MJPEG body, chunk by chunk.

        Raises:
            StreamUnavailable: the device is not serving a stream we can relay.
        """
        self._ensure_streaming_connection()
        client_id, client_queue = self._add_streaming_client()
        self._logger.info(f"New streaming client {client_id} connected")
        return self._client_frames(client_id, client_queue)

    def _client_frames(
        self, client_id: int, client_queue: queue.Queue
    ) -> Iterator[bytes]:
        """Yield queued frames to one client until the stream ends."""
        try:
            while True:
                try:
                    # Get frame from queue (blocks until frame available)
                    frame_data = client_queue.get(timeout=30)  # 30 second timeout

                    # None signals end of stream
                    if frame_data is None:
                        break

                    yield frame_data

                except queue.Empty:
                    # Timeout - check if streaming is still active
                    if not self._streaming_running:
                        break
                    # Continue waiting for frames
                    continue

        except Exception as e:
            self._logger.error(f"Error in stream for client: {e}")
        finally:
            self._remove_streaming_client(client_id)
            self._logger.info(f"Streaming client {client_id} disconnected")

    def stop(self):
        """Stop the stream manager and cleanup all connections."""
        self._stop_shared_streaming()

    def _ensure_streaming_connection(self):
        """Ensure shared streaming connection is active and healthy."""
        with self._streaming_lock:
            # Check if we need to start/restart connection
            need_restart = (
                self._shared_socket is None
                or not self._streaming_running
                or not self._is_socket_healthy()
            )

            if need_restart:
                if self._shared_socket is not None:
                    self._logger.info(
                        f"Stream connection to {self.device_ip} needs restart"
                    )
                self._start_shared_streaming()

    def _is_socket_healthy(self):
        """
        Say whether the shared connection to the device is still usable.

        This used to probe with ``recv(0)``, which returns ``b""`` whether the peer
        is alive or has sent FIN and never raises EAGAIN - so it answered "healthy"
        for every socket it was ever given, the EAGAIN branch was unreachable, and
        the restart in :meth:`_ensure_streaming_connection` could not fire. A device
        that dropped off left its viewers on a connection that never recovered.

        ``MSG_PEEK`` leaves whatever it finds in the receive queue for the
        broadcast loop, and ``MSG_DONTWAIT`` asks for the non-blocking behaviour
        per call rather than by flipping the socket's timeout - which the broadcast
        thread is reading through at the same time, and would see as a
        BlockingIOError and treat as the stream failing.

        Returns:
            bool: True while the connection is up.
        """
        if self._shared_socket is None:
            return False

        try:
            # b"" here means the peer has closed: a live connection with nothing
            # to read raises EAGAIN/EWOULDBLOCK instead.
            return bool(
                self._shared_socket.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            )
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return True
            self._logger.debug(f"Socket health check failed: {e}")
            return False
        except Exception as e:
            self._logger.debug(f"Socket health check failed: {e}")
            return False

    def _start_shared_streaming(self):
        """
        Connect to the device, complete the MJPEG handshake, then start relaying.

        The handshake runs here, synchronously, so that a device which answers
        with something other than an MJPEG response is reported rather than
        relayed. See :meth:`_read_stream_headers`.

        Raises:
            StreamUnavailable: the device is not serving a stream we can relay.
        """
        try:
            # Clean up any existing connection
            self._stop_shared_streaming()

            # Create new socket connection
            self._shared_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._shared_socket.settimeout(self._CONNECT_TIMEOUT)
            self._shared_socket.connect((self.device_ip, STREAMING_PORT))
            self._shared_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
            self._shared_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)

            leftover = self._read_stream_headers()

            # Start broadcasting thread
            self._streaming_running = True
            self._streaming_thread = Thread(
                target=self._streaming_broadcast_loop,
                kwargs={"leftover": leftover},
                daemon=True,
                name=f"StreamBroadcast_{self.device_id}",
            )
            self._streaming_thread.start()

            self._logger.info(
                f"Started shared streaming connection to {self.device_ip}:{STREAMING_PORT}"
            )

        except StreamUnavailable as e:
            self._logger.error(f"Cannot stream from {self.device_ip}: {e}")
            self._stop_shared_streaming()
            raise
        except Exception as e:
            self._logger.error(f"Failed to start shared streaming: {e}")
            self._stop_shared_streaming()
            raise

    def _stop_shared_streaming(self):
        """Stop the shared streaming connection."""
        with self._streaming_lock:
            self._streaming_running = False

            if self._shared_socket:
                try:
                    self._shared_socket.close()
                except Exception:
                    pass
                self._shared_socket = None

            if self._streaming_thread and self._streaming_thread.is_alive():
                self._streaming_thread.join(timeout=2)
            self._streaming_thread = None

            # Clear all client queues
            for client_queue in self._streaming_clients.values():
                try:
                    client_queue.put(None)  # Signal end to clients
                except Exception:
                    pass
            self._streaming_clients.clear()

    # Bounds for the handshake. Without them a device that accepts the connection
    # and then says nothing we understand holds the reader for ever: the old code
    # looped on recv() until a b"\r\n\r\n" turned up, which for a device speaking
    # the pre-2026-06 pickle protocol means never, and it swallowed the whole
    # stream in silence while the browser waited on a response with no frames.
    _CONNECT_TIMEOUT = 5.0
    _HEADER_TIMEOUT = 10.0
    _MAX_HEADER_BYTES = 8192

    def _read_stream_headers(self) -> bytes:
        """
        Request the stream and consume the device's HTTP response headers.

        The device serves a standard ``multipart/x-mixed-replace`` response, so the
        relay is a pure byte passthrough and the only thing to do here is to skip
        the headers - but the headers are also the one place where a device that
        cannot be relayed can be recognised. Devices older than the MJPEG change of
        June 2026 answer this same port with pickled frames behind an 8-byte length
        prefix, which is binary and contains no HTTP at all.

        Returns:
            bytes: body bytes that arrived in the same read as the headers. They
                are already part of the multipart stream and must be relayed.

        Raises:
            StreamUnavailable: the answer is not an MJPEG-over-HTTP response, or
                none arrived in time.
        """
        self._shared_socket.settimeout(self._HEADER_TIMEOUT)
        self._shared_socket.sendall(b"GET / HTTP/1.0\r\n\r\n")

        stale = (
            f"it answered port {STREAMING_PORT} with something that is not HTTP. "
            "Ethoscope software older than June 2026 streams pickled frames here, "
            "which this node cannot read - update the device."
        )

        header = b""
        while b"\r\n\r\n" not in header:
            try:
                packet = self._shared_socket.recv(4096)
            except TimeoutError as e:
                raise StreamUnavailable(
                    f"the device sent no response headers within "
                    f"{self._HEADER_TIMEOUT:.0f}s"
                ) from e
            if not packet:
                raise StreamUnavailable(
                    "the device closed the connection before sending any headers"
                )
            header += packet

            # Reason: checked on every read rather than only at the end, so a
            # device speaking the old protocol is named on its first packet
            # instead of after _MAX_HEADER_BYTES of pickled image data.
            if not header.startswith(b"HTTP/1."[: len(header)]):
                raise StreamUnavailable(stale)
            if len(header) > self._MAX_HEADER_BYTES:
                raise StreamUnavailable(
                    f"the device's response headers exceeded "
                    f"{self._MAX_HEADER_BYTES} bytes"
                )

        head, _, leftover = header.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 200" not in status:
            raise StreamUnavailable(
                f"the device answered {status.decode(errors='replace')!r}"
            )
        if b"multipart/x-mixed-replace" not in head.lower():
            raise StreamUnavailable(stale)

        self._shared_socket.settimeout(None)
        return leftover

    def _streaming_broadcast_loop(self, leftover: bytes = b""):
        """Relay the device's MJPEG body verbatim to all clients.

        The handshake has already happened in :meth:`_read_stream_headers`, so this
        is a pure byte passthrough: broadcast the multipart body unchanged, with no
        per-frame decoding (the boundary the device emits matches what we advertise
        to our own clients).

        Args:
            leftover (bytes): body bytes that arrived alongside the headers.
        """
        if not self._streaming_running or self._shared_socket is None:
            with self._streaming_lock:
                self._streaming_running = False
            return

        try:
            if leftover:
                self._broadcast_frame(leftover)

            # Stream the remaining body bytes straight through.
            while self._streaming_running and self._shared_socket:
                packet = self._shared_socket.recv(4096)
                if not packet:
                    break
                self._broadcast_frame(packet)

        except Exception as e:
            if self._streaming_running:
                self._logger.error(f"Streaming broadcast error: {e}")
                # A connection error here is caught by the health check, which restarts
                # the connection on the next streaming attempt.

        self._logger.info("Streaming broadcast loop ended")

        # Mark that streaming has stopped so health check will trigger restart, and
        # release the clients now. Reason: they wait on a 30 s queue timeout, so
        # without this a stream that dies leaves every viewer staring at a frozen
        # image for half a minute before the response even closes.
        with self._streaming_lock:
            self._streaming_running = False
            for client_queue in self._streaming_clients.values():
                try:
                    client_queue.put_nowait(None)
                except queue.Full:
                    pass

    def _broadcast_frame(self, frame_bytes):
        """Broadcast frame to all connected clients."""
        with self._streaming_lock:
            disconnected_clients = []

            for client_id, client_queue in self._streaming_clients.items():
                try:
                    client_queue.put_nowait(frame_bytes)
                except queue.Full:
                    # Client queue is full, skip this frame
                    pass
                except Exception:
                    # Client is disconnected
                    disconnected_clients.append(client_id)

            # Remove disconnected clients
            for client_id in disconnected_clients:
                self._streaming_clients.pop(client_id, None)

    def _add_streaming_client(self) -> tuple[int, queue.Queue]:
        """Add a new streaming client and return client_id and queue."""
        with self._streaming_lock:
            client_id = self._next_client_id
            self._next_client_id += 1

            client_queue = queue.Queue(maxsize=10)  # Limit queue size
            self._streaming_clients[client_id] = client_queue

            return client_id, client_queue

    def _remove_streaming_client(self, client_id: int):
        """Remove a streaming client."""
        with self._streaming_lock:
            self._streaming_clients.pop(client_id, None)

            # If no more clients, stop streaming after a delay
            if not self._streaming_clients and self._streaming_running:
                # Use a timer to stop streaming after 30 seconds of no clients
                def delayed_stop():
                    time.sleep(30)
                    with self._streaming_lock:
                        if not self._streaming_clients and self._streaming_running:
                            self._logger.info(
                                "No streaming clients for 30s, stopping shared connection"
                            )
                            self._stop_shared_streaming()

                Thread(target=delayed_stop, daemon=True).start()
