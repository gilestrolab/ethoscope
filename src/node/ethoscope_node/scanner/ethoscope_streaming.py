"""
Ethoscope streaming management module.

This module provides connection sharing and multi-client streaming capabilities
for Ethoscope devices using a simple, HTTP-compatible approach.
"""

import errno
import logging
import pickle
import queue
import socket
import struct
import time
from threading import RLock
from threading import Thread
from typing import Iterator
from typing import Tuple

# Import the streaming port constant
STREAMING_PORT = 8887


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
        Get a streaming iterator for a new client.

        Returns:
            Iterator that yields frame data for HTTP streaming
        """
        client_id = None
        client_queue = None

        try:
            # Ensure shared streaming connection is active
            self._ensure_streaming_connection()

            # Add this client to the streaming system
            client_id, client_queue = self._add_streaming_client()

            self._logger.info(f"New streaming client {client_id} connected")

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
            # Clean up this client
            if client_id is not None:
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
        """Check if the current socket connection is healthy."""
        if self._shared_socket is None:
            return False

        try:
            # Use a non-blocking check to see if socket is still connected
            # This will detect closed connections without sending data
            self._shared_socket.settimeout(0)
            self._shared_socket.recv(0)
            return True
        except OSError as e:
            # If we get EAGAIN/EWOULDBLOCK, socket is healthy but no data available
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return True
            # Any other error means socket is not healthy
            self._logger.debug(f"Socket health check failed: {e}")
            return False
        except Exception as e:
            self._logger.debug(f"Socket health check failed: {e}")
            return False
        finally:
            # Reset socket to blocking mode
            if self._shared_socket:
                try:
                    self._shared_socket.settimeout(None)
                except:
                    pass

    def _start_shared_streaming(self):
        """Start the shared streaming connection and broadcasting thread."""
        try:
            # Clean up any existing connection
            self._stop_shared_streaming()

            # Create new socket connection
            self._shared_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._shared_socket.connect((self.device_ip, STREAMING_PORT))
            self._shared_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
            self._shared_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)

            # Start broadcasting thread
            self._streaming_running = True
            self._streaming_thread = Thread(
                target=self._streaming_broadcast_loop,
                daemon=True,
                name=f"StreamBroadcast_{self.device_id}",
            )
            self._streaming_thread.start()

            self._logger.info(
                f"Started shared streaming connection to {self.device_ip}:{STREAMING_PORT}"
            )

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

    def _streaming_broadcast_loop(self):
        """Main loop for broadcasting frames to all clients."""
        data = b""
        payload_size = struct.calcsize("Q")

        while self._streaming_running and self._shared_socket:
            try:
                # Get message size
                while len(data) < payload_size:
                    packet = self._shared_socket.recv(4096)
                    if not packet:
                        break
                    data += packet

                if len(data) < payload_size:
                    break

                # Unpack message size
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("Q", packed_msg_size)[0]

                # Get frame data
                while len(data) < msg_size:
                    packet = self._shared_socket.recv(4096)
                    if not packet:
                        break
                    data += packet

                if len(data) < msg_size:
                    break

                # Extract frame
                frame_data = data[:msg_size]
                data = data[msg_size:]

                # Process and broadcast frame
                try:
                    frame = pickle.loads(frame_data)
                    frame_bytes = (
                        b"--frame\r\nContent-Type:image/jpeg\r\n\r\n"
                        + frame.tobytes()
                        + b"\r\n"
                    )

                    # Broadcast to all connected clients
                    self._broadcast_frame(frame_bytes)

                except Exception as e:
                    self._logger.warning(f"Error processing frame: {e}")
                    continue

            except Exception as e:
                if self._streaming_running:
                    self._logger.error(f"Streaming broadcast error: {e}")
                    # If this is a connection error, the health check will catch it
                    # and restart the connection on the next streaming attempt
                break

        self._logger.info("Streaming broadcast loop ended")

        # Mark that streaming has stopped so health check will trigger restart
        with self._streaming_lock:
            self._streaming_running = False

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

    def _add_streaming_client(self) -> Tuple[int, queue.Queue]:
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
