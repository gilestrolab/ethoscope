"""
Test configuration and fixtures for ethoscope device tests.

This module provides common pytest fixtures and configuration for all tests
in the ethoscope device package.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import numpy as np
import pytest

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "static_files"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_camera():
    """Mock camera interface for testing."""
    camera = Mock()
    camera.resolution = (640, 480)
    camera.framerate = 30
    camera.is_recording = False
    camera.capture.return_value = True
    camera.start_recording.return_value = True
    camera.stop_recording.return_value = True
    camera.close.return_value = True
    return camera


@pytest.fixture
def mock_frame():
    """Mock video frame for testing."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Add some test patterns
    frame[100:150, 100:150] = 255  # White square
    frame[200:250, 200:250] = 128  # Gray square
    return frame


@pytest.fixture
def mock_roi():
    """Mock ROI (Region of Interest) for testing."""
    roi = Mock()
    roi.id = 1
    roi.x = 100
    roi.y = 100
    roi.width = 100
    roi.height = 100
    roi.mask = np.ones((100, 100), dtype=np.uint8)
    return roi


@pytest.fixture
def mock_roi_list():
    """Mock list of ROIs for testing."""
    rois = []
    for i in range(5):
        roi = Mock()
        roi.id = i + 1
        roi.x = 50 + i * 120
        roi.y = 50 + i * 80
        roi.width = 100
        roi.height = 100
        roi.mask = np.ones((100, 100), dtype=np.uint8)
        rois.append(roi)
    return rois


@pytest.fixture
def mock_tracker():
    """Mock tracker for testing."""
    tracker = Mock()
    tracker.name = "AdaptiveBGTracker"
    tracker.is_running = False
    tracker.last_positions = []
    tracker.track.return_value = []
    tracker.start.return_value = True
    tracker.stop.return_value = True
    return tracker


@pytest.fixture
def mock_monitor():
    """Mock monitor for testing."""
    monitor = Mock()
    monitor.is_running = False
    monitor.last_frame_time = 0
    monitor.frame_count = 0
    monitor.start.return_value = True
    monitor.stop.return_value = True
    monitor.get_status.return_value = "stopped"
    return monitor


@pytest.fixture
def mock_stimulator():
    """Mock stimulator for testing."""
    stimulator = Mock()
    stimulator.name = "TestStimulator"
    stimulator.is_active = False
    stimulator.activate.return_value = True
    stimulator.deactivate.return_value = True
    stimulator.set_parameters.return_value = True
    return stimulator


@pytest.fixture
def mock_database():
    """Mock database for testing."""
    db = Mock()
    db.connect.return_value = True
    db.execute.return_value = True
    db.fetchall.return_value = []
    db.fetchone.return_value = None
    db.commit.return_value = True
    db.close.return_value = True
    return db


@pytest.fixture
def mock_hardware_config():
    """Mock hardware configuration for testing."""
    config = {
        "camera": {
            "type": "PiCamera",
            "resolution": [640, 480],
            "framerate": 30,
            "rotation": 0,
        },
        "stimulators": [
            {"type": "OptomotorStimulator", "gpio_pin": 18, "frequency": 1.0}
        ],
        "sensors": [{"type": "TemperatureSensor", "gpio_pin": 4, "interval": 60}],
    }
    return config


@pytest.fixture
def sample_tracking_results():
    """Sample tracking results for testing."""
    return [
        {
            "roi_id": 1,
            "x": 100.5,
            "y": 200.3,
            "width": 50,
            "height": 30,
            "angle": 45.0,
            "area": 1500,
            "timestamp": 1640995200.0,
        },
        {
            "roi_id": 2,
            "x": 300.2,
            "y": 150.7,
            "width": 48,
            "height": 32,
            "angle": 30.0,
            "area": 1536,
            "timestamp": 1640995200.0,
        },
    ]


@pytest.fixture
def mock_video_file():
    """Mock video file for testing."""
    video_file = Mock()
    video_file.name = "test_video.mp4"
    video_file.path = "/tmp/test_video.mp4"
    video_file.duration = 3600.0  # 1 hour
    video_file.frame_count = 108000  # 30 fps * 3600 seconds
    video_file.resolution = (640, 480)
    video_file.fps = 30
    return video_file


@pytest.fixture
def mock_experiment_config():
    """Mock experiment configuration for testing."""
    config = {
        "name": "Test Experiment",
        "description": "Test experiment for unit testing",
        "duration": 3600,  # 1 hour
        "tracking": {
            "enabled": True,
            "tracker": "AdaptiveBGTracker",
            "parameters": {"threshold": 30, "min_area": 100, "max_area": 10000},
        },
        "video_recording": {"enabled": False, "format": "mp4", "quality": "medium"},
        "stimulation": {"enabled": False, "type": "optomotor", "parameters": {}},
    }
    return config


@pytest.fixture
def test_images():
    """Provide paths to test images."""
    return {
        "bright_targets": TEST_DATA_DIR / "img" / "bright_targets.png",
        "dark_targets": TEST_DATA_DIR / "img" / "dark_targets.png",
    }


@pytest.fixture
def test_videos():
    """Provide paths to test videos."""
    return {"arena_video": TEST_DATA_DIR / "videos" / "arena_10x2_sortTubes.mp4"}


@pytest.fixture(autouse=True)
def cleanup_test_files():
    """Automatically clean up test files after each test."""
    yield
    # Clean up any test files that might have been created
    test_files = [
        "test_tracking.db",
        "test_video.mp4",
        "test_config.json",
        "test_experiment.json",
    ]
    for file_path in test_files:
        if os.path.exists(file_path):
            os.remove(file_path)


@pytest.fixture
def mock_gpio():
    """Mock GPIO interface for testing."""
    gpio = Mock()
    gpio.setup.return_value = True
    gpio.output.return_value = True
    gpio.input.return_value = False
    gpio.cleanup.return_value = True
    return gpio


@pytest.fixture
def mock_serial_port():
    """Mock serial port for testing."""
    port = Mock()
    port.name = "/dev/ttyUSB0"
    port.baudrate = 9600
    port.is_open = True
    port.read.return_value = b"OK"
    port.write.return_value = 2
    port.close.return_value = True
    return port
