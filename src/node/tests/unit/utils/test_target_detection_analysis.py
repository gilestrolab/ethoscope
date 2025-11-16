"""
Unit tests for ethoscope_node.utils.target_detection_analysis module.

Tests cover:
- TargetDetectionAnalyzer initialization and setup
- Detection log loading and parsing
- Summary statistics generation
- Failure pattern analysis
- Device performance analysis
- Lighting conditions analysis
- Recommendation generation
- Report generation
- Log cleanup functionality
- Dataset export for ML training
- Error handling and edge cases
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import numpy as np
import pytest

from ethoscope_node.utils.target_detection_analysis import TargetDetectionAnalyzer


class TestTargetDetectionAnalyzerInit:
    """Test TargetDetectionAnalyzer initialization."""

    def test_init_default_path(self):
        """Test initialization with default path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # The analyzer will use the provided tmpdir
            analyzer = TargetDetectionAnalyzer(tmpdir)

            assert analyzer.base_path == Path(tmpdir)
            assert analyzer.logger is not None

    def test_init_custom_path(self):
        """Test initialization with custom path."""
        custom_path = "/tmp/custom/path"
        analyzer = TargetDetectionAnalyzer(custom_path)

        assert analyzer.base_path == Path(custom_path)

    def test_init_creates_reports_directory(self):
        """Test initialization creates reports directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            reports_dir = Path(tmpdir) / "analysis_reports"
            assert reports_dir.exists()
            assert analyzer.reports_dir == reports_dir

    def test_init_handles_existing_reports_directory(self):
        """Test initialization when reports directory already exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = Path(tmpdir) / "analysis_reports"
            reports_dir.mkdir()

            analyzer = TargetDetectionAnalyzer(tmpdir)

            assert analyzer.reports_dir == reports_dir
            assert reports_dir.exists()


class TestLoadDetectionData:
    """Test _load_detection_data functionality."""

    def test_load_detection_data_empty_directory(self):
        """Test loading data from nonexistent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            cutoff = datetime.now() - timedelta(days=7)

            data = analyzer._load_detection_data("failed", cutoff)

            assert data == []

    def test_load_detection_data_valid_metadata(self):
        """Test loading valid detection metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create valid metadata file
            timestamp = datetime.now()
            metadata = {
                "timestamp": timestamp.isoformat(),
                "device_id": "test_device",
                "targets_found": 1,
            }
            metadata_file = failed_dir / "test_metadata.json"
            metadata_file.write_text(json.dumps(metadata))

            cutoff = timestamp - timedelta(hours=1)
            data = analyzer._load_detection_data("failed", cutoff)

            assert len(data) == 1
            assert data[0]["device_id"] == "test_device"
            assert data[0]["targets_found"] == 1
            assert "parsed_timestamp" in data[0]

    def test_load_detection_data_filters_old_data(self):
        """Test loading filters out data older than cutoff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create old metadata (before cutoff)
            old_timestamp = datetime.now() - timedelta(days=10)
            old_metadata = {
                "timestamp": old_timestamp.isoformat(),
                "device_id": "old_device",
            }
            old_file = failed_dir / "old_metadata.json"
            old_file.write_text(json.dumps(old_metadata))

            # Create recent metadata (after cutoff)
            new_timestamp = datetime.now()
            new_metadata = {
                "timestamp": new_timestamp.isoformat(),
                "device_id": "new_device",
            }
            new_file = failed_dir / "new_metadata.json"
            new_file.write_text(json.dumps(new_metadata))

            cutoff = datetime.now() - timedelta(days=7)
            data = analyzer._load_detection_data("failed", cutoff)

            assert len(data) == 1
            assert data[0]["device_id"] == "new_device"

    def test_load_detection_data_handles_invalid_json(self):
        """Test loading handles invalid JSON gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create invalid JSON file
            invalid_file = failed_dir / "invalid_metadata.json"
            invalid_file.write_text("not valid json {")

            cutoff = datetime.now() - timedelta(days=7)
            data = analyzer._load_detection_data("failed", cutoff)

            # Should skip invalid file
            assert data == []

    def test_load_detection_data_handles_missing_timestamp(self):
        """Test loading handles missing timestamp field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create metadata without timestamp
            metadata = {"device_id": "test_device"}
            metadata_file = failed_dir / "no_timestamp_metadata.json"
            metadata_file.write_text(json.dumps(metadata))

            cutoff = datetime.now() - timedelta(days=7)
            data = analyzer._load_detection_data("failed", cutoff)

            # Should skip files without valid timestamp
            assert data == []

    def test_load_detection_data_handles_invalid_timestamp(self):
        """Test loading handles invalid timestamp format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create metadata with invalid timestamp
            metadata = {
                "timestamp": "not-a-valid-timestamp",
                "device_id": "test_device",
            }
            metadata_file = failed_dir / "bad_timestamp_metadata.json"
            metadata_file.write_text(json.dumps(metadata))

            cutoff = datetime.now() - timedelta(days=7)
            data = analyzer._load_detection_data("failed", cutoff)

            # Should skip files with invalid timestamp
            assert data == []


class TestGenerateSummaryStats:
    """Test _generate_summary_stats functionality."""

    def test_generate_summary_stats_empty_data(self):
        """Test summary stats with no data."""
        analyzer = TargetDetectionAnalyzer()
        stats = analyzer._generate_summary_stats([], [])

        assert stats["total_detection_attempts"] == 0
        assert stats["successful_detections"] == 0
        assert stats["failed_detections"] == 0
        assert stats["overall_success_rate"] == 0
        assert stats["total_devices"] == 0

    def test_generate_summary_stats_only_failures(self):
        """Test summary stats with only failures."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"device_id": "device1"},
            {"device_id": "device2"},
            {"device_id": "device1"},
        ]

        stats = analyzer._generate_summary_stats(failed_data, [])

        assert stats["total_detection_attempts"] == 3
        assert stats["successful_detections"] == 0
        assert stats["failed_detections"] == 3
        assert stats["overall_success_rate"] == 0
        assert stats["devices_with_failures"] == 2
        assert stats["total_devices"] == 2

    def test_generate_summary_stats_only_successes(self):
        """Test summary stats with only successes."""
        analyzer = TargetDetectionAnalyzer()
        success_data = [
            {"device_id": "device1"},
            {"device_id": "device2"},
        ]

        stats = analyzer._generate_summary_stats([], success_data)

        assert stats["total_detection_attempts"] == 2
        assert stats["successful_detections"] == 2
        assert stats["failed_detections"] == 0
        assert stats["overall_success_rate"] == 1.0
        assert stats["devices_with_successes"] == 2

    def test_generate_summary_stats_mixed_data(self):
        """Test summary stats with mixed success and failure data."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"device_id": "device1"},
            {"device_id": "device2"},
        ]
        success_data = [
            {"device_id": "device1"},
            {"device_id": "device3"},
            {"device_id": "device3"},
        ]

        stats = analyzer._generate_summary_stats(failed_data, success_data)

        assert stats["total_detection_attempts"] == 5
        assert stats["successful_detections"] == 3
        assert stats["failed_detections"] == 2
        assert stats["overall_success_rate"] == 0.6
        assert stats["total_devices"] == 3

    def test_generate_summary_stats_handles_missing_device_id(self):
        """Test summary stats handles missing device_id fields."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"device_id": "device1"},
            {},  # Missing device_id
        ]
        success_data = [{"device_id": "device1"}]

        stats = analyzer._generate_summary_stats(failed_data, success_data)

        # Should use "unknown" for missing device_id
        assert "unknown" in stats["devices_analyzed"]


class TestAnalyzeFailurePatterns:
    """Test _analyze_failure_patterns functionality."""

    def test_analyze_failure_patterns_no_failures(self):
        """Test failure pattern analysis with no failures."""
        analyzer = TargetDetectionAnalyzer()
        patterns = analyzer._analyze_failure_patterns([])

        assert patterns["no_failures"] is True

    def test_analyze_failure_patterns_targets_found_distribution(self):
        """Test failure patterns tracks targets found distribution."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"targets_found": 0, "image_quality": {}},
            {"targets_found": 1, "image_quality": {}},
            {"targets_found": 0, "image_quality": {}},
            {"targets_found": 2, "image_quality": {}},
        ]

        patterns = analyzer._analyze_failure_patterns(failed_data)

        assert patterns["total_failures"] == 4
        assert patterns["targets_found_distribution"][0] == 2
        assert patterns["targets_found_distribution"][1] == 1
        assert patterns["targets_found_distribution"][2] == 1
        assert patterns["most_common_targets_found"] == 0

    def test_analyze_failure_patterns_brightness_categorization(self):
        """Test failure patterns categorizes brightness correctly."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"image_quality": {"mean_brightness": 10}},  # very_dark
            {"image_quality": {"mean_brightness": 50}},  # dark
            {"image_quality": {"mean_brightness": 100}},  # normal
            {"image_quality": {"mean_brightness": 190}},  # bright
            {"image_quality": {"mean_brightness": 230}},  # very_bright
        ]

        patterns = analyzer._analyze_failure_patterns(failed_data)

        assert patterns["brightness_distribution"]["very_dark"] == 1
        assert patterns["brightness_distribution"]["dark"] == 1
        assert patterns["brightness_distribution"]["normal"] == 1
        assert patterns["brightness_distribution"]["bright"] == 1
        assert patterns["brightness_distribution"]["very_bright"] == 1

    def test_analyze_failure_patterns_low_contrast_detection(self):
        """Test failure patterns detects low contrast issues."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"image_quality": {"contrast_rms": 10}},  # Low contrast
            {"image_quality": {"contrast_rms": 15}},  # Low contrast
            {"image_quality": {"contrast_rms": 30}},  # Good contrast
        ]

        patterns = analyzer._analyze_failure_patterns(failed_data)

        assert patterns["low_contrast_failures"] == 2
        assert patterns["low_contrast_percentage"] == pytest.approx(66.67, rel=0.01)

    def test_analyze_failure_patterns_handles_missing_image_quality(self):
        """Test failure patterns handles missing image_quality data."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {},  # No image_quality
            {"image_quality": {}},  # Empty image_quality
        ]

        patterns = analyzer._analyze_failure_patterns(failed_data)

        # Should use defaults (128 brightness, 0 contrast)
        assert patterns["brightness_distribution"]["normal"] == 2
        assert patterns["low_contrast_failures"] == 2


class TestAnalyzeDevicePerformance:
    """Test _analyze_device_performance functionality."""

    def test_analyze_device_performance_empty_data(self):
        """Test device performance analysis with no data."""
        analyzer = TargetDetectionAnalyzer()
        performance = analyzer._analyze_device_performance([], [])

        assert performance["device_performance"] == {}
        assert performance["problematic_devices"] == []
        assert performance["total_devices_analyzed"] == 0

    def test_analyze_device_performance_single_device(self):
        """Test device performance analysis for single device."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [{"device_id": "device1"}]
        success_data = [
            {"device_id": "device1"},
            {"device_id": "device1"},
            {"device_id": "device1"},
        ]

        performance = analyzer._analyze_device_performance(failed_data, success_data)

        assert "device1" in performance["device_performance"]
        assert performance["device_performance"]["device1"]["total_attempts"] == 4
        assert performance["device_performance"]["device1"]["failed"] == 1
        assert performance["device_performance"]["device1"]["successful"] == 3
        assert performance["device_performance"]["device1"]["success_rate"] == 0.75

    def test_analyze_device_performance_multiple_devices(self):
        """Test device performance analysis for multiple devices."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"device_id": "device1"},
            {"device_id": "device2"},
        ]
        success_data = [
            {"device_id": "device1"},
            {"device_id": "device3"},
        ]

        performance = analyzer._analyze_device_performance(failed_data, success_data)

        assert len(performance["device_performance"]) == 3
        assert performance["total_devices_analyzed"] == 3

    def test_analyze_device_performance_identifies_problematic_devices(self):
        """Test device performance identifies devices with low success rates."""
        analyzer = TargetDetectionAnalyzer()
        # Device with < 80% success rate and >= 5 attempts
        failed_data = [
            {"device_id": "bad_device"},
            {"device_id": "bad_device"},
            {"device_id": "bad_device"},
            {"device_id": "bad_device"},
        ]
        success_data = [{"device_id": "bad_device"}]

        performance = analyzer._analyze_device_performance(failed_data, success_data)

        assert len(performance["problematic_devices"]) == 1
        assert performance["problematic_devices"][0]["device_id"] == "bad_device"
        assert performance["problematic_devices"][0]["success_rate"] == 0.2

    def test_analyze_device_performance_ignores_insufficient_data(self):
        """Test device performance ignores devices with < 5 attempts."""
        analyzer = TargetDetectionAnalyzer()
        # Device with low success but < 5 total attempts
        failed_data = [
            {"device_id": "device1"},
            {"device_id": "device1"},
        ]
        success_data = [{"device_id": "device1"}]

        performance = analyzer._analyze_device_performance(failed_data, success_data)

        # Should not be flagged as problematic (only 3 attempts)
        assert performance["problematic_devices"] == []

    def test_analyze_device_performance_sorts_problematic_devices(self):
        """Test device performance sorts problematic devices by success rate."""
        analyzer = TargetDetectionAnalyzer()
        # Create two problematic devices with different success rates
        failed_data = [
            {"device_id": "device1"},  # 1 fail, 4 success = 0.8 (not flagged)
            {"device_id": "device2"},  # 3 fail, 2 success = 0.4
            {"device_id": "device2"},
            {"device_id": "device2"},
            {"device_id": "device3"},  # 4 fail, 1 success = 0.2
            {"device_id": "device3"},
            {"device_id": "device3"},
            {"device_id": "device3"},
        ]
        success_data = [
            {"device_id": "device1"},
            {"device_id": "device1"},
            {"device_id": "device1"},
            {"device_id": "device1"},
            {"device_id": "device2"},
            {"device_id": "device2"},
            {"device_id": "device3"},
        ]

        performance = analyzer._analyze_device_performance(failed_data, success_data)

        # Should be sorted by success rate (lowest first)
        assert len(performance["problematic_devices"]) == 2
        assert performance["problematic_devices"][0]["device_id"] == "device3"
        assert performance["problematic_devices"][1]["device_id"] == "device2"


class TestAnalyzeLightingConditions:
    """Test _analyze_lighting_conditions functionality."""

    def test_analyze_lighting_conditions_empty_data(self):
        """Test lighting analysis with no data."""
        analyzer = TargetDetectionAnalyzer()
        lighting = analyzer._analyze_lighting_conditions([], [])

        assert lighting["successful_detections"]["brightness"]["count"] == 0
        assert lighting["failed_detections"]["brightness"]["count"] == 0
        assert lighting["optimal_brightness_range"] is None
        assert lighting["optimal_contrast_range"] is None

    def test_analyze_lighting_conditions_brightness_stats(self):
        """Test lighting analysis calculates brightness statistics."""
        analyzer = TargetDetectionAnalyzer()
        success_data = [
            {"image_quality": {"mean_brightness": 100, "contrast_rms": 30}},
            {"image_quality": {"mean_brightness": 120, "contrast_rms": 35}},
            {"image_quality": {"mean_brightness": 110, "contrast_rms": 32}},
        ]

        lighting = analyzer._analyze_lighting_conditions([], success_data)

        brightness_stats = lighting["successful_detections"]["brightness"]
        assert brightness_stats["count"] == 3
        assert brightness_stats["mean"] == pytest.approx(110, rel=0.01)
        assert brightness_stats["min"] == 100
        assert brightness_stats["max"] == 120

    def test_analyze_lighting_conditions_contrast_stats(self):
        """Test lighting analysis calculates contrast statistics."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"image_quality": {"mean_brightness": 100, "contrast_rms": 10}},
            {"image_quality": {"mean_brightness": 100, "contrast_rms": 20}},
            {"image_quality": {"mean_brightness": 100, "contrast_rms": 15}},
        ]

        lighting = analyzer._analyze_lighting_conditions(failed_data, [])

        contrast_stats = lighting["failed_detections"]["contrast"]
        assert contrast_stats["count"] == 3
        assert contrast_stats["mean"] == pytest.approx(15, rel=0.01)
        assert contrast_stats["min"] == 10
        assert contrast_stats["max"] == 20

    def test_analyze_lighting_conditions_optimal_ranges(self):
        """Test lighting analysis calculates optimal ranges from success data."""
        analyzer = TargetDetectionAnalyzer()
        success_data = [
            {"image_quality": {"mean_brightness": 100, "contrast_rms": 30}},
            {"image_quality": {"mean_brightness": 120, "contrast_rms": 40}},
        ]

        lighting = analyzer._analyze_lighting_conditions([], success_data)

        # Should calculate mean ± std
        brightness_range = lighting["optimal_brightness_range"]
        assert brightness_range is not None
        assert "min" in brightness_range
        assert "max" in brightness_range
        assert brightness_range["min"] >= 0
        assert brightness_range["max"] <= 255

        contrast_range = lighting["optimal_contrast_range"]
        assert contrast_range is not None
        assert "min" in contrast_range
        assert "max" in contrast_range

    def test_analyze_lighting_conditions_handles_missing_values(self):
        """Test lighting analysis handles missing image quality values."""
        analyzer = TargetDetectionAnalyzer()
        data = [
            {"image_quality": {}},  # No brightness or contrast
            {"image_quality": {"mean_brightness": 100}},  # No contrast
            {},  # No image_quality
        ]

        lighting = analyzer._analyze_lighting_conditions(data, [])

        # Should only count records with valid data
        assert lighting["failed_detections"]["brightness"]["count"] == 1
        assert lighting["failed_detections"]["contrast"]["count"] == 0

    def test_analyze_lighting_conditions_clips_brightness_range(self):
        """Test lighting analysis clips brightness range to valid values."""
        analyzer = TargetDetectionAnalyzer()
        # Very low brightness with high std could produce negative min
        success_data = [
            {"image_quality": {"mean_brightness": 10, "contrast_rms": 30}},
            {"image_quality": {"mean_brightness": 50, "contrast_rms": 30}},
        ]

        lighting = analyzer._analyze_lighting_conditions([], success_data)

        brightness_range = lighting["optimal_brightness_range"]
        assert brightness_range["min"] >= 0
        assert brightness_range["max"] <= 255


class TestGenerateRecommendations:
    """Test _generate_recommendations functionality."""

    def test_generate_recommendations_no_failures(self):
        """Test recommendations with no failures."""
        analyzer = TargetDetectionAnalyzer()
        recommendations = analyzer._generate_recommendations([], [{"device_id": "d1"}])

        assert len(recommendations) == 1
        assert "No failures detected" in recommendations[0]

    def test_generate_recommendations_high_failure_rate(self):
        """Test recommendations for high failure rate."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [{"image_quality": {}} for _ in range(4)]
        success_data = [{"image_quality": {}} for _ in range(6)]

        recommendations = analyzer._generate_recommendations(failed_data, success_data)

        # 40% failure rate should trigger recommendation
        assert any("High failure rate" in r for r in recommendations)

    def test_generate_recommendations_low_lighting(self):
        """Test recommendations for low lighting issues."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"image_quality": {"mean_brightness": 50}},  # Dark
            {"image_quality": {"mean_brightness": 60}},  # Dark
            {"image_quality": {"mean_brightness": 70}},  # Dark
            {"image_quality": {"mean_brightness": 100}},  # Normal
        ]

        recommendations = analyzer._generate_recommendations(failed_data, [])

        # > 30% dark failures should trigger recommendation
        assert any("low lighting" in r for r in recommendations)

    def test_generate_recommendations_excessive_brightness(self):
        """Test recommendations for excessive brightness."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"image_quality": {"mean_brightness": 210}},
            {"image_quality": {"mean_brightness": 220}},
            {"image_quality": {"mean_brightness": 100}},
        ]

        recommendations = analyzer._generate_recommendations(failed_data, [])

        # > 30% bright failures should trigger recommendation
        assert any("excessive brightness" in r for r in recommendations)

    def test_generate_recommendations_low_contrast(self):
        """Test recommendations for low contrast issues."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"image_quality": {"contrast_rms": 10}},
            {"image_quality": {"contrast_rms": 15}},
            {"image_quality": {"contrast_rms": 30}},
        ]

        recommendations = analyzer._generate_recommendations(failed_data, [])

        # > 30% low contrast should trigger recommendation
        assert any("Low contrast" in r for r in recommendations)

    def test_generate_recommendations_partial_detections(self):
        """Test recommendations for partial detections pattern."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"targets_found": 1, "image_quality": {}},
            {"targets_found": 2, "image_quality": {}},
            {"targets_found": 1, "image_quality": {}},
            {"targets_found": 0, "image_quality": {}},
        ]

        recommendations = analyzer._generate_recommendations(failed_data, [])

        # > 50% partial detections should trigger recommendation
        assert any("partial detections" in r for r in recommendations)

    def test_generate_recommendations_zero_detections(self):
        """Test recommendations for complete detection failures."""
        analyzer = TargetDetectionAnalyzer()
        failed_data = [
            {"targets_found": 0, "image_quality": {}},
            {"targets_found": 0, "image_quality": {}},
            {"targets_found": 1, "image_quality": {}},
        ]

        recommendations = analyzer._generate_recommendations(failed_data, [])

        # > 30% zero detections should trigger recommendation
        assert any("complete detection failures" in r for r in recommendations)


class TestAnalyzeDetectionLogs:
    """Test analyze_detection_logs main method."""

    def test_analyze_detection_logs_integration(self):
        """Test complete detection log analysis workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            # Create test data
            failed_dir = Path(tmpdir) / "failed"
            success_dir = Path(tmpdir) / "success"
            failed_dir.mkdir()
            success_dir.mkdir()

            timestamp = datetime.now()
            failed_metadata = {
                "timestamp": timestamp.isoformat(),
                "device_id": "device1",
                "targets_found": 1,
                "image_quality": {"mean_brightness": 100, "contrast_rms": 20},
            }
            (failed_dir / "failed_metadata.json").write_text(
                json.dumps(failed_metadata)
            )

            success_metadata = {
                "timestamp": timestamp.isoformat(),
                "device_id": "device2",
                "targets_found": 3,
                "image_quality": {"mean_brightness": 120, "contrast_rms": 30},
            }
            (success_dir / "success_metadata.json").write_text(
                json.dumps(success_metadata)
            )

            analysis = analyzer.analyze_detection_logs(days_back=30)

            assert "analysis_period" in analysis
            assert "summary" in analysis
            assert "failure_patterns" in analysis
            assert "device_performance" in analysis
            assert "lighting_analysis" in analysis
            assert "recommendations" in analysis

    def test_analyze_detection_logs_sets_correct_date_range(self):
        """Test analyze_detection_logs uses correct date range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            analysis = analyzer.analyze_detection_logs(days_back=7)

            period = analysis["analysis_period"]
            start_date = datetime.fromisoformat(period["start_date"])
            end_date = datetime.fromisoformat(period["end_date"])

            assert period["days_analyzed"] == 7
            assert (end_date - start_date).days == pytest.approx(7, abs=1)


class TestGenerateFailureReport:
    """Test generate_failure_report functionality."""

    def test_generate_failure_report_creates_file(self):
        """Test generate_failure_report creates JSON report file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            report_path = analyzer.generate_failure_report(days_back=7)

            assert Path(report_path).exists()
            assert report_path.endswith(".json")

    def test_generate_failure_report_contains_analysis(self):
        """Test generate_failure_report contains complete analysis data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            report_path = analyzer.generate_failure_report(days_back=7)

            with open(report_path) as f:
                report_data = json.load(f)

            assert "analysis_period" in report_data
            assert "summary" in report_data
            assert "failure_patterns" in report_data

    def test_generate_failure_report_returns_path(self):
        """Test generate_failure_report returns path as string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            report_path = analyzer.generate_failure_report(days_back=7)

            assert isinstance(report_path, str)
            assert "target_detection_report_" in report_path


class TestCleanupOldLogs:
    """Test cleanup_old_logs functionality."""

    def test_cleanup_old_logs_empty_directory(self):
        """Test cleanup with no logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            stats = analyzer.cleanup_old_logs(days_to_keep=30)

            assert stats["files_removed"] == 0
            assert stats["bytes_freed"] == 0

    def test_cleanup_old_logs_removes_old_files(self):
        """Test cleanup removes files older than cutoff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create old file
            old_file = failed_dir / "old_file.txt"
            old_file.write_text("test data")

            # Set modification time to 60 days ago
            old_time = (datetime.now() - timedelta(days=60)).timestamp()
            old_file.touch()
            import os

            os.utime(old_file, (old_time, old_time))

            stats = analyzer.cleanup_old_logs(days_to_keep=30)

            assert stats["files_removed"] == 1
            assert stats["bytes_freed"] > 0
            assert not old_file.exists()

    def test_cleanup_old_logs_preserves_recent_files(self):
        """Test cleanup preserves files newer than cutoff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            success_dir = Path(tmpdir) / "success"
            success_dir.mkdir()

            # Create recent file
            recent_file = success_dir / "recent_file.txt"
            recent_file.write_text("keep this")

            stats = analyzer.cleanup_old_logs(days_to_keep=30)

            assert stats["files_removed"] == 0
            assert recent_file.exists()

    def test_cleanup_old_logs_handles_both_subdirs(self):
        """Test cleanup processes both failed and success directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)

            # Create both subdirectories with old files
            for subdir in ["failed", "success"]:
                subdir_path = Path(tmpdir) / subdir
                subdir_path.mkdir()
                old_file = subdir_path / "old.txt"
                old_file.write_text("data")

                old_time = (datetime.now() - timedelta(days=60)).timestamp()
                import os

                os.utime(old_file, (old_time, old_time))

            stats = analyzer.cleanup_old_logs(days_to_keep=30)

            assert stats["files_removed"] == 2

    def test_cleanup_old_logs_handles_errors(self):
        """Test cleanup handles file errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create file
            test_file = failed_dir / "test.txt"
            test_file.write_text("data")

            # Mock unlink to raise error
            with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
                stats = analyzer.cleanup_old_logs(days_to_keep=0)

            # Should continue despite error
            assert stats["files_removed"] == 0


class TestExportDatasetForTraining:
    """Test export_dataset_for_training functionality."""

    def test_export_dataset_creates_directory(self):
        """Test export creates output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            output_dir = Path(tmpdir) / "export"

            analyzer.export_dataset_for_training(str(output_dir))

            assert output_dir.exists()

    def test_export_dataset_creates_subdirectories(self):
        """Test export creates success and failed subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            output_dir = Path(tmpdir) / "export"

            analyzer.export_dataset_for_training(str(output_dir))

            assert (output_dir / "success").exists()
            assert (output_dir / "failed").exists()

    def test_export_dataset_copies_images_and_metadata(self):
        """Test export copies both images and corresponding metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create image and metadata
            (failed_dir / "test_original.png").write_bytes(b"fake image data")
            (failed_dir / "test_metadata.json").write_text('{"test": "data"}')

            output_dir = Path(tmpdir) / "export"
            stats = analyzer.export_dataset_for_training(str(output_dir))

            assert stats["failed_exported"] == 1
            assert (output_dir / "failed" / "test_original.png").exists()
            assert (output_dir / "failed" / "test_metadata.json").exists()

    def test_export_dataset_limits_samples(self):
        """Test export respects max_samples_per_class limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            success_dir = Path(tmpdir) / "success"
            success_dir.mkdir()

            # Create 5 images
            for i in range(5):
                (success_dir / f"test{i}_original.png").write_bytes(b"data")

            output_dir = Path(tmpdir) / "export"
            stats = analyzer.export_dataset_for_training(
                str(output_dir), max_samples_per_class=3
            )

            # Should only export 3 images
            assert stats["success_exported"] == 3

    def test_export_dataset_creates_info_file(self):
        """Test export creates dataset_info.json file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            output_dir = Path(tmpdir) / "export"

            analyzer.export_dataset_for_training(str(output_dir))

            info_file = output_dir / "dataset_info.json"
            assert info_file.exists()

            with open(info_file) as f:
                info = json.load(f)

            assert "export_date" in info
            assert "source_path" in info
            assert "export_stats" in info
            assert "max_samples_per_class" in info

    def test_export_dataset_handles_missing_metadata(self):
        """Test export handles images without corresponding metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create image without metadata
            (failed_dir / "test_original.png").write_bytes(b"image data")

            output_dir = Path(tmpdir) / "export"
            stats = analyzer.export_dataset_for_training(str(output_dir))

            # Should still export the image
            assert stats["failed_exported"] == 1
            assert (output_dir / "failed" / "test_original.png").exists()

    def test_export_dataset_returns_stats(self):
        """Test export returns statistics dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            output_dir = Path(tmpdir) / "export"

            stats = analyzer.export_dataset_for_training(str(output_dir))

            assert isinstance(stats, dict)
            assert "success_exported" in stats
            assert "failed_exported" in stats
            assert stats["success_exported"] == 0
            assert stats["failed_exported"] == 0


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_analyzer_handles_nonexistent_base_path(self):
        """Test analyzer handles nonexistent base path gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use a path that exists but has no data subdirectories
            analyzer = TargetDetectionAnalyzer(tmpdir)

            # Remove the reports dir to simulate minimal setup
            import shutil

            shutil.rmtree(analyzer.reports_dir, ignore_errors=True)
            analyzer.reports_dir.mkdir(parents=True, exist_ok=True)

            # Should not crash, just return empty data
            analysis = analyzer.analyze_detection_logs(days_back=7)

            assert analysis["summary"]["total_detection_attempts"] == 0

    def test_analyze_with_corrupted_metadata(self):
        """Test analysis handles various corrupted metadata formats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create various corrupted files that should be skipped
            # Note: files need *_metadata.json naming pattern
            # Empty file
            (failed_dir / "empty_metadata.json").write_text("")
            # Invalid JSON
            (failed_dir / "invalid_metadata.json").write_text("not json {")
            # Missing timestamp
            (failed_dir / "notime_metadata.json").write_text('{"device_id": "test"}')

            # Create valid file to ensure pattern matching works
            valid_metadata = {
                "timestamp": datetime.now().isoformat(),
                "device_id": "test",
            }
            (failed_dir / "valid_metadata.json").write_text(json.dumps(valid_metadata))

            analysis = analyzer.analyze_detection_logs(days_back=7)

            # Should handle gracefully - only valid file should be counted
            assert analysis["summary"]["total_detection_attempts"] == 1

    def test_cleanup_with_special_characters_in_filenames(self):
        """Test cleanup handles filenames with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            failed_dir = Path(tmpdir) / "failed"
            failed_dir.mkdir()

            # Create file with special characters
            special_file = failed_dir / "file with spaces & special!chars.txt"
            special_file.write_text("data")

            old_time = (datetime.now() - timedelta(days=60)).timestamp()
            import os

            os.utime(special_file, (old_time, old_time))

            stats = analyzer.cleanup_old_logs(days_to_keep=30)

            assert stats["files_removed"] == 1

    def test_export_with_very_long_filenames(self):
        """Test export handles very long filenames."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = TargetDetectionAnalyzer(tmpdir)
            success_dir = Path(tmpdir) / "success"
            success_dir.mkdir()

            # Create file with long name (but within filesystem limits)
            long_name = "x" * 100 + "_original.png"
            (success_dir / long_name).write_bytes(b"data")

            output_dir = Path(tmpdir) / "export"
            stats = analyzer.export_dataset_for_training(str(output_dir))

            assert stats["success_exported"] == 1
