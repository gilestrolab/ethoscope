#!/usr/bin/env python

"""
Unit tests for TemperatureAlertMonitor class.

Tests the temperature monitoring and alert system including:
- Alert triggering when thresholds are crossed
- Alert suppression after first alert
- State reset when temperature normalizes
- Configuration-based enable/disable
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from ethoscope_node.notifications.temperature_monitor import (
    AlertState,
    TemperatureAlertMonitor,
)


class TestAlertState:
    """Tests for AlertState enum."""

    def test_alert_states_defined(self):
        """Test that all expected alert states are defined."""
        assert AlertState.NORMAL.value == "normal"
        assert AlertState.ALERT_HIGH_SENT.value == "alert_high_sent"
        assert AlertState.ALERT_LOW_SENT.value == "alert_low_sent"


class TestTemperatureAlertMonitor:
    """Tests for TemperatureAlertMonitor class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration with temperature alert settings."""
        config = Mock()
        config.get_temperature_alert_config.return_value = {
            "enabled": True,
            "min_threshold": 18.0,
            "max_threshold": 28.0,
        }
        return config

    @pytest.fixture
    def mock_notification_manager(self):
        """Create a mock notification manager."""
        manager = Mock()
        manager.send_temperature_alert.return_value = True
        return manager

    @pytest.fixture
    def monitor(self, mock_config, mock_notification_manager):
        """Create a TemperatureAlertMonitor instance with mocked dependencies."""
        monitor = TemperatureAlertMonitor(
            config=mock_config,
            notification_manager=mock_notification_manager,
        )
        return monitor

    def test_init_with_config(self, mock_config):
        """Test initialization with provided config."""
        monitor = TemperatureAlertMonitor(config=mock_config)
        assert monitor.config == mock_config
        assert monitor._alert_states == {}
        assert monitor._alert_timestamps == {}

    def test_init_creates_default_config(self):
        """Test initialization creates default config if none provided."""
        with patch(
            "ethoscope_node.notifications.temperature_monitor.EthoscopeConfiguration"
        ) as mock_config_class:
            mock_config = Mock()
            mock_config_class.return_value = mock_config

            _monitor = TemperatureAlertMonitor()  # noqa: F841
            mock_config_class.assert_called_once()

    def test_lazy_notification_manager_initialization(self, mock_config):
        """Test that notification manager is lazily initialized."""
        monitor = TemperatureAlertMonitor(config=mock_config)
        assert monitor._notification_manager is None

        # Patch the import inside the manager module
        with patch(
            "ethoscope_node.notifications.manager.NotificationManager"
        ) as mock_manager_class:
            mock_manager = Mock()
            mock_manager_class.return_value = mock_manager

            # Access the property to trigger lazy init
            result = monitor.notification_manager

            # Since the lazy init imports from .manager, verify it works
            assert result is not None

    # Tests for high temperature alerts

    def test_high_temperature_triggers_alert(self, monitor, mock_notification_manager):
        """Test that high temperature triggers an alert."""
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,  # Above 28.0 threshold
        )

        assert result is True
        mock_notification_manager.send_temperature_alert.assert_called_once_with(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,
            threshold=28.0,
            violation_type="high",
        )
        assert monitor.get_alert_state("sensor1") == AlertState.ALERT_HIGH_SENT

    def test_high_temperature_alert_suppressed_after_first(
        self, monitor, mock_notification_manager
    ):
        """Test that high temperature alerts are suppressed after first alert."""
        # First reading triggers alert
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,
        )

        mock_notification_manager.reset_mock()

        # Second high reading should NOT trigger alert
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=31.0,  # Still high
        )

        assert result is False
        mock_notification_manager.send_temperature_alert.assert_not_called()

    # Tests for low temperature alerts

    def test_low_temperature_triggers_alert(self, monitor, mock_notification_manager):
        """Test that low temperature triggers an alert."""
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=15.0,  # Below 18.0 threshold
        )

        assert result is True
        mock_notification_manager.send_temperature_alert.assert_called_once_with(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=15.0,
            threshold=18.0,
            violation_type="low",
        )
        assert monitor.get_alert_state("sensor1") == AlertState.ALERT_LOW_SENT

    def test_low_temperature_alert_suppressed_after_first(
        self, monitor, mock_notification_manager
    ):
        """Test that low temperature alerts are suppressed after first alert."""
        # First reading triggers alert
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=15.0,
        )

        mock_notification_manager.reset_mock()

        # Second low reading should NOT trigger alert
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=14.0,  # Still low
        )

        assert result is False
        mock_notification_manager.send_temperature_alert.assert_not_called()

    # Tests for temperature normalization

    def test_temperature_normalizes_resets_state(
        self, monitor, mock_notification_manager
    ):
        """Test that state resets when temperature returns to normal."""
        # First, trigger a high alert
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,
        )
        assert monitor.get_alert_state("sensor1") == AlertState.ALERT_HIGH_SENT

        # Temperature returns to normal
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=22.0,  # Within normal range
        )
        assert monitor.get_alert_state("sensor1") == AlertState.NORMAL

    def test_can_alert_again_after_normalization(
        self, monitor, mock_notification_manager
    ):
        """Test that new alert can be sent after temperature normalizes."""
        # Trigger high alert
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,
        )

        # Normalize
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=22.0,
        )

        mock_notification_manager.reset_mock()

        # New high reading should trigger alert again
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=29.0,
        )

        assert result is True
        mock_notification_manager.send_temperature_alert.assert_called_once()

    # Tests for state transitions

    def test_transition_from_high_to_low_alert(
        self, monitor, mock_notification_manager
    ):
        """Test proper state transition from high alert to low alert."""
        # Trigger high alert
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,
        )
        assert monitor.get_alert_state("sensor1") == AlertState.ALERT_HIGH_SENT

        # Temperature normalizes
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=22.0,
        )
        assert monitor.get_alert_state("sensor1") == AlertState.NORMAL

        mock_notification_manager.reset_mock()

        # Now goes low
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=15.0,
        )
        assert monitor.get_alert_state("sensor1") == AlertState.ALERT_LOW_SENT
        mock_notification_manager.send_temperature_alert.assert_called_once_with(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=15.0,
            threshold=18.0,
            violation_type="low",
        )

    # Tests for configuration

    def test_alerts_disabled_in_config(self, mock_notification_manager):
        """Test that no alerts sent when disabled in configuration."""
        config = Mock()
        config.get_temperature_alert_config.return_value = {
            "enabled": False,
            "min_threshold": 18.0,
            "max_threshold": 28.0,
        }

        monitor = TemperatureAlertMonitor(
            config=config,
            notification_manager=mock_notification_manager,
        )

        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,  # High temp, but alerts disabled
        )

        assert result is False
        mock_notification_manager.send_temperature_alert.assert_not_called()

    def test_custom_thresholds(self, mock_notification_manager):
        """Test that custom thresholds from config are used."""
        config = Mock()
        config.get_temperature_alert_config.return_value = {
            "enabled": True,
            "min_threshold": 20.0,  # Custom min
            "max_threshold": 25.0,  # Custom max
        }

        monitor = TemperatureAlertMonitor(
            config=config,
            notification_manager=mock_notification_manager,
        )

        # Temperature 26 is high with custom threshold of 25
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=26.0,
        )

        assert result is True
        mock_notification_manager.send_temperature_alert.assert_called_once()
        call_kwargs = mock_notification_manager.send_temperature_alert.call_args[1]
        assert call_kwargs["threshold"] == 25.0
        assert call_kwargs["violation_type"] == "high"

    # Tests for multiple sensors

    def test_independent_state_per_sensor(self, monitor, mock_notification_manager):
        """Test that each sensor has independent alert state."""
        # Trigger alert for sensor1
        monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Sensor 1",
            location="Lab A",
            temperature=30.0,
        )

        # Sensor2 should still be able to trigger alert
        mock_notification_manager.reset_mock()

        result = monitor.check_temperature(
            sensor_id="sensor2",
            sensor_name="Sensor 2",
            location="Lab B",
            temperature=29.0,
        )

        assert result is True
        mock_notification_manager.send_temperature_alert.assert_called_once()

        # Both sensors in alert state
        assert monitor.get_alert_state("sensor1") == AlertState.ALERT_HIGH_SENT
        assert monitor.get_alert_state("sensor2") == AlertState.ALERT_HIGH_SENT

    # Tests for state management methods

    def test_get_all_alert_states(self, monitor):
        """Test getting all alert states."""
        # Set up some states
        monitor._alert_states["sensor1"] = AlertState.ALERT_HIGH_SENT
        monitor._alert_timestamps["sensor1"] = 1234567890.0
        monitor._alert_states["sensor2"] = AlertState.ALERT_LOW_SENT
        monitor._alert_timestamps["sensor2"] = 1234567891.0

        states = monitor.get_all_alert_states()

        assert "sensor1" in states
        assert states["sensor1"]["state"] == "alert_high_sent"
        assert states["sensor1"]["timestamp"] == 1234567890.0
        assert "sensor2" in states
        assert states["sensor2"]["state"] == "alert_low_sent"

    def test_reset_alert_state(self, monitor):
        """Test resetting alert state for a sensor."""
        monitor._alert_states["sensor1"] = AlertState.ALERT_HIGH_SENT
        monitor._alert_timestamps["sensor1"] = 1234567890.0

        monitor.reset_alert_state("sensor1")

        assert "sensor1" not in monitor._alert_states
        assert "sensor1" not in monitor._alert_timestamps

    def test_reset_all_alert_states(self, monitor):
        """Test resetting all alert states."""
        monitor._alert_states["sensor1"] = AlertState.ALERT_HIGH_SENT
        monitor._alert_states["sensor2"] = AlertState.ALERT_LOW_SENT
        monitor._alert_timestamps["sensor1"] = 1234567890.0
        monitor._alert_timestamps["sensor2"] = 1234567891.0

        monitor.reset_all_alert_states()

        assert len(monitor._alert_states) == 0
        assert len(monitor._alert_timestamps) == 0

    # Tests for edge cases

    def test_notification_failure_does_not_change_state(
        self, monitor, mock_notification_manager
    ):
        """Test that failed notification doesn't change alert state."""
        mock_notification_manager.send_temperature_alert.return_value = False

        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=30.0,
        )

        assert result is False
        # State should remain NORMAL since notification failed
        assert monitor.get_alert_state("sensor1") == AlertState.NORMAL

    def test_temperature_exactly_at_threshold_is_normal(
        self, monitor, mock_notification_manager
    ):
        """Test that temperature exactly at threshold is considered normal."""
        # At max threshold - should be normal
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=28.0,  # Exactly at max threshold
        )

        assert result is False
        mock_notification_manager.send_temperature_alert.assert_not_called()

        # At min threshold - should be normal
        result = monitor.check_temperature(
            sensor_id="sensor1",
            sensor_name="Test Sensor",
            location="Lab",
            temperature=18.0,  # Exactly at min threshold
        )

        assert result is False
        mock_notification_manager.send_temperature_alert.assert_not_called()

    def test_get_alert_state_unknown_sensor(self, monitor):
        """Test getting alert state for unknown sensor returns NORMAL."""
        state = monitor.get_alert_state("unknown_sensor")
        assert state == AlertState.NORMAL
