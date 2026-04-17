#!/usr/bin/env python

"""
Temperature alert monitor for Ethoscope sensor system.

Monitors sensor temperatures against configurable thresholds and sends
alerts through the notification system when thresholds are crossed.
Implements "alert once" behavior - alerts are sent when a threshold is
first crossed, then suppressed until temperature returns to normal.
"""

import logging
import time
from enum import Enum
from typing import Any, Dict, Optional

from ..utils.configuration import EthoscopeConfiguration


class AlertState(Enum):
    """State of temperature alert for a sensor."""

    NORMAL = "normal"
    ALERT_HIGH_SENT = "alert_high_sent"
    ALERT_LOW_SENT = "alert_low_sent"


class TemperatureAlertMonitor:
    """
    Monitors sensor temperatures and sends alerts when thresholds are crossed.

    Implements "alert once" behavior: sends alert when threshold is first crossed,
    then suppresses until temperature returns to normal range.
    """

    def __init__(
        self,
        config: Optional[EthoscopeConfiguration] = None,
        notification_manager: Optional[Any] = None,
    ):
        """
        Initialize temperature alert monitor.

        Args:
            config: Configuration instance, will create new one if None
            notification_manager: NotificationManager instance for sending alerts.
                If None, will be lazily initialized when needed.
        """
        self.config = config or EthoscopeConfiguration()
        self._notification_manager = notification_manager
        self.logger = logging.getLogger(self.__class__.__name__)

        # Track alert state per sensor: {sensor_id: AlertState}
        self._alert_states: Dict[str, AlertState] = {}
        # Track when alert was sent: {sensor_id: timestamp}
        self._alert_timestamps: Dict[str, float] = {}

    @property
    def notification_manager(self):
        """Lazy initialization of notification manager to avoid circular imports."""
        if self._notification_manager is None:
            from .manager import NotificationManager

            self._notification_manager = NotificationManager(self.config)
        return self._notification_manager

    def check_temperature(
        self,
        sensor_id: str,
        sensor_name: str,
        location: str,
        temperature: float,
    ) -> bool:
        """
        Check temperature against thresholds and send alert if needed.

        Args:
            sensor_id: Unique sensor identifier
            sensor_name: Human-readable sensor name
            location: Sensor location
            temperature: Current temperature in Celsius

        Returns:
            True if an alert was sent, False otherwise
        """
        # Skip alerts for virtual sensors (weather data, not incubator conditions)
        if sensor_id and sensor_id.startswith("virtual_sensor_"):
            return False

        # Check per-sensor alert config first, fall back to global
        try:
            all_sensors = self.config.get_all_sensors()
            per_sensor_alerts = all_sensors.get(sensor_name, {}).get("alerts", {})
        except (AttributeError, TypeError):
            per_sensor_alerts = {}

        if isinstance(per_sensor_alerts, dict) and per_sensor_alerts.get("enabled"):
            min_threshold = per_sensor_alerts.get("min_threshold", 18.0)
            max_threshold = per_sensor_alerts.get("max_threshold", 28.0)
        else:
            alert_config = self.config.get_temperature_alert_config()
            if not alert_config.get("enabled", True):
                return False
            min_threshold = alert_config.get("min_threshold", 18.0)
            max_threshold = alert_config.get("max_threshold", 28.0)

        # Get current state for this sensor
        current_state = self._alert_states.get(sensor_id, AlertState.NORMAL)

        # Check for high temperature violation
        if temperature > max_threshold:
            if current_state != AlertState.ALERT_HIGH_SENT:
                # Temperature crossed high threshold - send alert
                success = self.notification_manager.send_temperature_alert(
                    sensor_id=sensor_id,
                    sensor_name=sensor_name,
                    location=location,
                    temperature=temperature,
                    threshold=max_threshold,
                    violation_type="high",
                )
                if success:
                    self._alert_states[sensor_id] = AlertState.ALERT_HIGH_SENT
                    self._alert_timestamps[sensor_id] = time.time()
                    self.logger.info(
                        f"Temperature HIGH alert sent for {sensor_name}: "
                        f"{temperature:.1f}C > {max_threshold:.1f}C"
                    )
                return success
            return False  # Already alerted

        # Check for low temperature violation
        elif temperature < min_threshold:
            if current_state != AlertState.ALERT_LOW_SENT:
                # Temperature crossed low threshold - send alert
                success = self.notification_manager.send_temperature_alert(
                    sensor_id=sensor_id,
                    sensor_name=sensor_name,
                    location=location,
                    temperature=temperature,
                    threshold=min_threshold,
                    violation_type="low",
                )
                if success:
                    self._alert_states[sensor_id] = AlertState.ALERT_LOW_SENT
                    self._alert_timestamps[sensor_id] = time.time()
                    self.logger.info(
                        f"Temperature LOW alert sent for {sensor_name}: "
                        f"{temperature:.1f}C < {min_threshold:.1f}C"
                    )
                return success
            return False  # Already alerted

        else:
            # Temperature is back in normal range
            if current_state != AlertState.NORMAL:
                self.logger.info(
                    f"Temperature returned to normal for {sensor_name}: "
                    f"{temperature:.1f}C (range: {min_threshold:.1f}-{max_threshold:.1f}C)"
                )
                self._alert_states[sensor_id] = AlertState.NORMAL
            return False

    def get_alert_state(self, sensor_id: str) -> AlertState:
        """
        Get current alert state for a sensor.

        Args:
            sensor_id: Sensor identifier

        Returns:
            Current AlertState for the sensor
        """
        return self._alert_states.get(sensor_id, AlertState.NORMAL)

    def get_all_alert_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Get alert states for all monitored sensors.

        Returns:
            Dictionary mapping sensor_id to state info
        """
        states = {}
        for sensor_id, state in self._alert_states.items():
            states[sensor_id] = {
                "state": state.value,
                "timestamp": self._alert_timestamps.get(sensor_id),
            }
        return states

    def reset_alert_state(self, sensor_id: str) -> None:
        """
        Reset alert state for a sensor (for testing/admin use).

        Args:
            sensor_id: Sensor identifier to reset
        """
        if sensor_id in self._alert_states:
            del self._alert_states[sensor_id]
            self.logger.info(f"Reset alert state for sensor: {sensor_id}")
        if sensor_id in self._alert_timestamps:
            del self._alert_timestamps[sensor_id]

    def reset_all_alert_states(self) -> None:
        """Reset alert states for all sensors."""
        self._alert_states.clear()
        self._alert_timestamps.clear()
        self.logger.info("Reset all temperature alert states")
