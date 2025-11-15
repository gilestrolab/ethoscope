"""
Unit tests for ethoscope_streaming module.

This module tests the Ethoscope streaming manager functionality including
connection sharing, multi-client streaming, frame broadcasting, and
resource cleanup.
"""

import errno
import pickle
import queue
import socket
import struct
import time
from threading import Thread
from unittest.mock import MagicMock, Mock, call, patch

import numpy as np
import pytest

from ethoscope_node.scanner.ethoscope_streaming import (
    STREAMING_PORT,
    EthoscopeStreamManager,
)


class TestStreamingConstants:
    """Test module-level constants."""

    def test_streaming_port_value(self):
        """Test STREAMING_PORT constant is correctly defined."""
        assert STREAMING_PORT == 8887


class TestEthoscopeStreamManager:
    """Test EthoscopeStreamManager class."""

    def test_initialization(self):
        """Test EthoscopeStreamManager initialization."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        assert manager.device_ip == "192.168.1.100"
        assert manager.device_id == "device_001"
        assert manager._shared_socket is None
        assert manager._streaming_clients == {}
        assert manager._streaming_thread is None
        assert manager._streaming_running is False
        assert manager._next_client_id == 0
        assert manager._logger is not None

    def test_initialization_with_special_characters(self):
        """Test initialization with special characters in device_id."""
        manager = EthoscopeStreamManager("10.0.0.1", "device-test_123")

        assert manager.device_id == "device-test_123"
        assert manager._logger.name == "StreamManager_device-test_123"

    @patch("socket.socket")
    @patch("ethoscope_node.scanner.ethoscope_streaming.Thread")
    def test_start_shared_streaming_success(self, mock_thread_class, mock_socket_class):
        """Test successful shared streaming connection start."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket

        # Mock thread
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        # Start streaming
        manager._start_shared_streaming()

        # Verify socket creation and connection
        mock_socket_class.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_socket.connect.assert_called_once_with(("192.168.1.100", STREAMING_PORT))
        mock_socket.setsockopt.assert_any_call(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, True
        )
        mock_socket.setsockopt.assert_any_call(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, True
        )

        # Verify thread creation and start
        assert mock_thread_class.call_count == 1
        call_kwargs = mock_thread_class.call_args[1]
        assert call_kwargs["target"] == manager._streaming_broadcast_loop
        assert call_kwargs["daemon"] is True
        assert call_kwargs["name"] == "StreamBroadcast_device_001"
        mock_thread.start.assert_called_once()

        # Verify state
        assert manager._streaming_running is True
        assert manager._shared_socket == mock_socket
        assert manager._streaming_thread == mock_thread

    @patch("socket.socket")
    def test_start_shared_streaming_connection_error(self, mock_socket_class):
        """Test shared streaming start with connection error."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that fails to connect
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = OSError("Connection refused")
        mock_socket_class.return_value = mock_socket

        # Attempt to start streaming
        with pytest.raises(socket.error):
            manager._start_shared_streaming()

        # Verify cleanup was called
        assert manager._streaming_running is False
        assert manager._shared_socket is None

    @patch("socket.socket")
    @patch("ethoscope_node.scanner.ethoscope_streaming.Thread")
    def test_start_shared_streaming_cleans_up_existing(
        self, mock_thread_class, mock_socket_class
    ):
        """Test that starting streaming cleans up existing connection."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Set up existing connection
        old_socket = MagicMock()
        old_thread = MagicMock()
        old_thread.is_alive.return_value = True
        manager._shared_socket = old_socket
        manager._streaming_thread = old_thread
        manager._streaming_running = True
        manager._streaming_clients = {0: queue.Queue()}

        # Mock new socket
        new_socket = MagicMock()
        mock_socket_class.return_value = new_socket

        # Start new streaming
        manager._start_shared_streaming()

        # Verify old connection was cleaned up
        old_socket.close.assert_called_once()
        old_thread.join.assert_called_once_with(timeout=2)

        # Verify new connection was established
        assert manager._shared_socket == new_socket
        assert manager._streaming_clients == {}

    def test_stop_shared_streaming_no_connection(self):
        """Test stopping when no connection exists."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Should not raise error
        manager._stop_shared_streaming()

        assert manager._streaming_running is False
        assert manager._shared_socket is None
        assert manager._streaming_thread is None

    def test_stop_shared_streaming_with_connection(self):
        """Test stopping an active streaming connection."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Set up active connection
        mock_socket = MagicMock()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        manager._shared_socket = mock_socket
        manager._streaming_thread = mock_thread
        manager._streaming_running = True

        # Stop streaming
        manager._stop_shared_streaming()

        # Verify cleanup
        assert manager._streaming_running is False
        mock_socket.close.assert_called_once()
        mock_thread.join.assert_called_once_with(timeout=2)
        assert manager._shared_socket is None
        assert manager._streaming_thread is None

    def test_stop_shared_streaming_with_clients(self):
        """Test stopping streaming with active clients."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Set up clients
        queue1 = queue.Queue()
        queue2 = queue.Queue()
        manager._streaming_clients = {0: queue1, 1: queue2}
        manager._streaming_running = True

        # Stop streaming
        manager._stop_shared_streaming()

        # Verify clients received end signal
        assert queue1.get() is None
        assert queue2.get() is None
        assert manager._streaming_clients == {}

    def test_stop_shared_streaming_socket_close_error(self):
        """Test stopping streaming when socket.close() raises error."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that fails to close
        mock_socket = MagicMock()
        mock_socket.close.side_effect = OSError("Socket error")
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Should not raise error
        manager._stop_shared_streaming()

        # Verify cleanup still completed
        assert manager._streaming_running is False
        assert manager._shared_socket is None

    def test_stop_method(self):
        """Test public stop method."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        with patch.object(manager, "_stop_shared_streaming") as mock_stop:
            manager.stop()
            mock_stop.assert_called_once()

    def test_is_socket_healthy_no_socket(self):
        """Test socket health check when socket is None."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")
        manager._shared_socket = None

        assert manager._is_socket_healthy() is False

    def test_is_socket_healthy_connection_ok(self):
        """Test socket health check with healthy connection."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock healthy socket that raises EAGAIN (no data available)
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = OSError(errno.EAGAIN, "No data")
        manager._shared_socket = mock_socket

        assert manager._is_socket_healthy() is True
        mock_socket.settimeout.assert_any_call(0)
        mock_socket.settimeout.assert_any_call(None)

    def test_is_socket_healthy_connection_ok_ewouldblock(self):
        """Test socket health check with EWOULDBLOCK error (healthy)."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that raises EWOULDBLOCK
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = OSError(errno.EWOULDBLOCK, "Would block")
        manager._shared_socket = mock_socket

        assert manager._is_socket_healthy() is True

    def test_is_socket_healthy_connection_closed(self):
        """Test socket health check with closed connection."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that is closed
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = OSError(errno.ECONNRESET, "Connection reset")
        manager._shared_socket = mock_socket

        assert manager._is_socket_healthy() is False
        mock_socket.settimeout.assert_any_call(None)

    def test_is_socket_healthy_other_exception(self):
        """Test socket health check with other exceptions."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that raises different exception
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = Exception("Unexpected error")
        manager._shared_socket = mock_socket

        assert manager._is_socket_healthy() is False

    def test_is_socket_healthy_timeout_reset_error(self):
        """Test socket health check when timeout reset fails."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket where settimeout(None) fails
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = OSError(errno.EAGAIN, "No data")
        mock_socket.settimeout.side_effect = [
            None,  # First call (set to 0) succeeds
            Exception("Timeout error"),  # Second call (reset) fails
        ]
        manager._shared_socket = mock_socket

        # Should still return True (healthy) and not raise error
        assert manager._is_socket_healthy() is True

    def test_ensure_streaming_connection_starts_new(self):
        """Test ensuring connection when none exists."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        with patch.object(manager, "_start_shared_streaming") as mock_start:
            manager._ensure_streaming_connection()
            mock_start.assert_called_once()

    def test_ensure_streaming_connection_already_running(self):
        """Test ensuring connection when already running and healthy."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Set up healthy connection
        manager._shared_socket = MagicMock()
        manager._streaming_running = True

        with patch.object(manager, "_is_socket_healthy", return_value=True):
            with patch.object(manager, "_start_shared_streaming") as mock_start:
                manager._ensure_streaming_connection()
                mock_start.assert_not_called()

    def test_ensure_streaming_connection_restarts_unhealthy(self):
        """Test ensuring connection restarts when socket is unhealthy."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Set up unhealthy connection
        manager._shared_socket = MagicMock()
        manager._streaming_running = True

        with patch.object(manager, "_is_socket_healthy", return_value=False):
            with patch.object(manager, "_start_shared_streaming") as mock_start:
                manager._ensure_streaming_connection()
                mock_start.assert_called_once()

    def test_ensure_streaming_connection_restarts_not_running(self):
        """Test ensuring connection restarts when not running."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Set up connection that exists but not running
        manager._shared_socket = MagicMock()
        manager._streaming_running = False

        with patch.object(manager, "_start_shared_streaming") as mock_start:
            manager._ensure_streaming_connection()
            mock_start.assert_called_once()

    def test_add_streaming_client(self):
        """Test adding a streaming client."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Add first client
        client_id1, queue1 = manager._add_streaming_client()
        assert client_id1 == 0
        assert isinstance(queue1, queue.Queue)
        assert manager._streaming_clients[0] == queue1
        assert manager._next_client_id == 1

        # Add second client
        client_id2, queue2 = manager._add_streaming_client()
        assert client_id2 == 1
        assert queue2 != queue1
        assert manager._streaming_clients[1] == queue2
        assert manager._next_client_id == 2

    def test_add_streaming_client_queue_size(self):
        """Test that client queues have correct size limit."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        client_id, client_queue = manager._add_streaming_client()

        # Queue should have maxsize of 10
        assert client_queue.maxsize == 10

    def test_remove_streaming_client_simple(self):
        """Test removing a streaming client."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Add clients
        client_id1, _ = manager._add_streaming_client()
        client_id2, _ = manager._add_streaming_client()

        # Remove first client
        manager._remove_streaming_client(client_id1)
        assert client_id1 not in manager._streaming_clients
        assert client_id2 in manager._streaming_clients

    def test_remove_streaming_client_nonexistent(self):
        """Test removing a client that doesn't exist."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Should not raise error
        manager._remove_streaming_client(999)

    @patch("ethoscope_node.scanner.ethoscope_streaming.Thread")
    def test_remove_streaming_client_last_client_delayed_stop(self, mock_thread_class):
        """Test that removing last client triggers delayed stop."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")
        manager._streaming_running = True

        # Add and remove a client
        client_id, _ = manager._add_streaming_client()

        # Mock thread for delayed stop
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        manager._remove_streaming_client(client_id)

        # Verify delayed stop thread was started
        mock_thread_class.assert_called_once()
        call_kwargs = mock_thread_class.call_args[1]
        assert call_kwargs["daemon"] is True
        mock_thread.start.assert_called_once()

    def test_remove_streaming_client_not_last(self):
        """Test that removing non-last client doesn't trigger delayed stop."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")
        manager._streaming_running = True

        # Add two clients
        client_id1, _ = manager._add_streaming_client()
        client_id2, _ = manager._add_streaming_client()

        with patch("ethoscope_node.scanner.ethoscope_streaming.Thread") as mock_thread:
            manager._remove_streaming_client(client_id1)
            # Should not start delayed stop thread
            mock_thread.assert_not_called()

    def test_broadcast_frame_to_clients(self):
        """Test broadcasting frame to all connected clients."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Add clients
        client_id1, queue1 = manager._add_streaming_client()
        client_id2, queue2 = manager._add_streaming_client()

        frame_bytes = b"test_frame_data"

        # Broadcast frame
        manager._broadcast_frame(frame_bytes)

        # Verify both clients received frame
        assert queue1.get_nowait() == frame_bytes
        assert queue2.get_nowait() == frame_bytes

    def test_broadcast_frame_full_queue_skips(self):
        """Test broadcasting skips frames when client queue is full."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Add client
        client_id, client_queue = manager._add_streaming_client()

        # Fill the queue (maxsize=10)
        for i in range(10):
            client_queue.put(f"frame_{i}")

        frame_bytes = b"new_frame"

        # Broadcast should skip without error
        manager._broadcast_frame(frame_bytes)

        # Queue should still have original frames, not new one
        assert client_queue.get_nowait() == "frame_0"

    def test_broadcast_frame_removes_disconnected_clients(self):
        """Test broadcasting removes clients with broken queues."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Add clients
        client_id1, queue1 = manager._add_streaming_client()
        client_id2, queue2 = manager._add_streaming_client()

        # Make queue2 raise exception
        queue2.put_nowait = MagicMock(side_effect=Exception("Client error"))

        frame_bytes = b"test_frame"

        # Broadcast frame
        manager._broadcast_frame(frame_bytes)

        # Client 1 should have received frame
        assert queue1.get_nowait() == frame_bytes

        # Client 2 should be removed
        assert client_id2 not in manager._streaming_clients
        assert client_id1 in manager._streaming_clients

    def test_streaming_broadcast_loop_processes_frame(self):
        """Test streaming broadcast loop processes and distributes frames."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Create test frame
        test_frame = np.zeros((480, 640), dtype=np.uint8)
        frame_data = pickle.dumps(test_frame)
        msg_size = len(frame_data)
        packed_size = struct.pack("Q", msg_size)

        # Prepare socket data
        socket_data = packed_size + frame_data

        # Mock socket
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [
            socket_data,  # First recv gets all data
            b"",  # Second recv signals end
        ]
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Add client
        client_id, client_queue = manager._add_streaming_client()

        # Run broadcast loop (will exit after processing one frame)
        manager._streaming_broadcast_loop()

        # Verify client received formatted frame
        frame_bytes = client_queue.get_nowait()
        assert frame_bytes.startswith(b"--frame\r\nContent-Type:image/jpeg\r\n\r\n")
        assert frame_bytes.endswith(b"\r\n")
        assert manager._streaming_running is False

    def test_streaming_broadcast_loop_handles_partial_data(self):
        """Test broadcast loop correctly handles partial data packets."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Create test frame
        test_frame = np.zeros((100, 100), dtype=np.uint8)
        frame_data = pickle.dumps(test_frame)
        msg_size = len(frame_data)
        packed_size = struct.pack("Q", msg_size)

        # Split data into multiple chunks
        full_data = packed_size + frame_data
        chunk1 = full_data[:50]
        chunk2 = full_data[50:100]
        chunk3 = full_data[100:]

        # Mock socket that returns data in chunks
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [
            chunk1,
            chunk2,
            chunk3,
            b"",  # End signal
        ]
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Add client
        client_id, client_queue = manager._add_streaming_client()

        # Run broadcast loop
        manager._streaming_broadcast_loop()

        # Verify client received frame
        assert not client_queue.empty()

    def test_streaming_broadcast_loop_handles_corrupted_frame(self):
        """Test broadcast loop handles corrupted frame data gracefully."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Create corrupted data (valid size header, invalid pickle data)
        msg_size = 100
        packed_size = struct.pack("Q", msg_size)
        corrupted_data = b"not_valid_pickle_data" * 10

        # Prepare socket data
        socket_data = packed_size + corrupted_data[:msg_size]

        # Mock socket
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [
            socket_data,
            b"",  # End after one frame
        ]
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Add client
        client_id, client_queue = manager._add_streaming_client()

        # Run broadcast loop (should handle error and continue)
        manager._streaming_broadcast_loop()

        # Client queue should be empty (corrupted frame was skipped)
        assert client_queue.empty()

    def test_streaming_broadcast_loop_socket_error(self):
        """Test broadcast loop handles socket errors."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that raises error
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = OSError("Connection lost")
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Run broadcast loop (should exit gracefully)
        manager._streaming_broadcast_loop()

        # Should mark streaming as stopped
        assert manager._streaming_running is False

    def test_streaming_broadcast_loop_stops_when_flag_false(self):
        """Test broadcast loop exits when streaming_running is False."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Set up socket but streaming not running
        mock_socket = MagicMock()
        manager._shared_socket = mock_socket
        manager._streaming_running = False

        # Run broadcast loop (should exit immediately)
        manager._streaming_broadcast_loop()

        # Socket should not be called
        mock_socket.recv.assert_not_called()

    def test_streaming_broadcast_loop_stops_when_socket_none(self):
        """Test broadcast loop exits when socket is None."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        manager._shared_socket = None
        manager._streaming_running = True

        # Run broadcast loop (should exit immediately)
        manager._streaming_broadcast_loop()

        assert manager._streaming_running is False

    @patch("socket.socket")
    @patch("ethoscope_node.scanner.ethoscope_streaming.Thread")
    def test_get_stream_for_client_success(self, mock_thread_class, mock_socket_class):
        """Test getting stream for a client successfully."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket and thread
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        # Prepare test frames
        test_frames = [b"frame1", b"frame2", b"frame3", None]

        # Create a thread to feed frames to the queue
        def feed_frames():
            time.sleep(0.1)  # Give client time to set up
            with manager._streaming_lock:
                if manager._streaming_clients:
                    client_queue = list(manager._streaming_clients.values())[0]
                    for frame in test_frames:
                        client_queue.put(frame)

        feeder_thread = Thread(target=feed_frames, daemon=True)
        feeder_thread.start()

        # Get stream
        frames = []
        for frame in manager.get_stream_for_client():
            frames.append(frame)

        # Verify frames received (excluding None terminator)
        assert frames == [b"frame1", b"frame2", b"frame3"]

        # Verify client was cleaned up
        assert len(manager._streaming_clients) == 0

        feeder_thread.join(timeout=1)

    @patch("socket.socket")
    @patch("ethoscope_node.scanner.ethoscope_streaming.Thread")
    def test_get_stream_for_client_timeout(self, mock_thread_class, mock_socket_class):
        """Test stream timeout when no frames received."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket and thread
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        # Stop streaming after client connects
        def stop_streaming():
            time.sleep(0.2)
            manager._streaming_running = False

        stopper_thread = Thread(target=stop_streaming, daemon=True)
        stopper_thread.start()

        # Get stream (should timeout and exit)
        frames = []
        for frame in manager.get_stream_for_client():
            frames.append(frame)

        # Should receive no frames
        assert frames == []

        # Verify client was cleaned up
        assert len(manager._streaming_clients) == 0

        stopper_thread.join(timeout=1)

    @patch("socket.socket")
    @patch("ethoscope_node.scanner.ethoscope_streaming.Thread")
    def test_get_stream_for_client_error_cleanup(
        self, mock_thread_class, mock_socket_class
    ):
        """Test that client is cleaned up even if error occurs."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that fails
        mock_socket_class.side_effect = OSError("Connection failed")

        # Get stream (should handle error and cleanup)
        frames = []
        for frame in manager.get_stream_for_client():
            frames.append(frame)

        # Should receive no frames
        assert frames == []

        # Verify no clients remain
        assert len(manager._streaming_clients) == 0

    @patch("socket.socket")
    @patch("ethoscope_node.scanner.ethoscope_streaming.Thread")
    def test_get_stream_for_client_multiple_clients(
        self, mock_thread_class, mock_socket_class
    ):
        """Test multiple clients can stream simultaneously."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket and thread
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        test_frames = [b"frame1", b"frame2", None]

        # Feed frames to all clients
        def feed_frames():
            time.sleep(0.1)
            with manager._streaming_lock:
                for client_queue in manager._streaming_clients.values():
                    for frame in test_frames:
                        client_queue.put(frame)

        feeder_thread = Thread(target=feed_frames, daemon=True)
        feeder_thread.start()

        # Start multiple clients
        client1_frames = []
        client2_frames = []

        def client1():
            for frame in manager.get_stream_for_client():
                client1_frames.append(frame)

        def client2():
            for frame in manager.get_stream_for_client():
                client2_frames.append(frame)

        thread1 = Thread(target=client1, daemon=True)
        thread2 = Thread(target=client2, daemon=True)

        thread1.start()
        thread2.start()

        thread1.join(timeout=2)
        thread2.join(timeout=2)
        feeder_thread.join(timeout=1)

        # Both clients should receive same frames
        assert client1_frames == [b"frame1", b"frame2"]
        assert client2_frames == [b"frame1", b"frame2"]

        # All clients should be cleaned up
        assert len(manager._streaming_clients) == 0

    def test_streaming_broadcast_loop_empty_packet(self):
        """Test broadcast loop handles empty packet correctly."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Mock socket that returns empty data (connection closed)
        mock_socket = MagicMock()
        mock_socket.recv.return_value = b""
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Run broadcast loop
        manager._streaming_broadcast_loop()

        # Should exit cleanly and mark as not running
        assert manager._streaming_running is False

    def test_streaming_broadcast_loop_incomplete_message_size(self):
        """Test broadcast loop handles incomplete message size."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Send only partial size header (needs 8 bytes, send 4)
        partial_header = struct.pack("I", 12345)  # Only 4 bytes

        # Mock socket
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [
            partial_header,
            b"",  # Connection closed before complete header
        ]
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Run broadcast loop
        manager._streaming_broadcast_loop()

        # Should exit cleanly
        assert manager._streaming_running is False

    def test_streaming_broadcast_loop_incomplete_frame_data(self):
        """Test broadcast loop handles incomplete frame data."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        # Send complete size header but incomplete data
        msg_size = 1000
        packed_size = struct.pack("Q", msg_size)
        partial_data = b"incomplete_data"

        # Mock socket
        mock_socket = MagicMock()
        mock_socket.recv.side_effect = [
            packed_size,
            partial_data,
            b"",  # Connection closed before all data received
        ]
        manager._shared_socket = mock_socket
        manager._streaming_running = True

        # Run broadcast loop
        manager._streaming_broadcast_loop()

        # Should exit cleanly
        assert manager._streaming_running is False

    def test_thread_safety_concurrent_client_operations(self):
        """Test thread safety with concurrent add/remove operations."""
        manager = EthoscopeStreamManager("192.168.1.100", "device_001")

        results = []

        def add_clients():
            for _ in range(10):
                client_id, queue = manager._add_streaming_client()
                results.append(("add", client_id))

        def remove_clients():
            time.sleep(0.01)  # Let some clients be added first
            for i in range(5):
                manager._remove_streaming_client(i)
                results.append(("remove", i))

        thread1 = Thread(target=add_clients)
        thread2 = Thread(target=remove_clients)

        thread1.start()
        thread2.start()

        thread1.join(timeout=2)
        thread2.join(timeout=2)

        # Verify operations completed without deadlock
        assert len(results) == 15  # 10 adds + 5 removes

        # Verify final state is consistent
        assert manager._next_client_id == 10
        # Should have 5 clients remaining (10 added - 5 removed)
        assert len(manager._streaming_clients) == 5
