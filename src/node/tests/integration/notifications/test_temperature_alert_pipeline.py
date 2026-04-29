"""
End-to-end test for the temperature alert pipeline.

Simulates a sensor update reporting an over-threshold temperature and asserts
the full chain fires: Sensor._update_info() -> temperature callback ->
TemperatureAlertMonitor.check_temperature() -> NotificationManager ->
EmailNotificationService.send_temperature_alert() -> smtplib SMTP send.

Regression test for the dead `_add_or_update_device()` override bug that caused
temperature alerts to silently no-op in production (see April 2026 incident:
sensor reached 45C for 24 hours without an email alert being sent).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from ethoscope_node.notifications.manager import NotificationManager
from ethoscope_node.notifications.temperature_monitor import TemperatureAlertMonitor
from ethoscope_node.scanner.sensor_scanner import Sensor, SensorScanner


class _StubConfig:
    """Minimal EthoscopeConfiguration stand-in for the alert pipeline."""

    def __init__(self):
        self.content = {
            "smtp": {
                "enabled": True,
                "host": "smtp.example.test",
                "port": 465,
                "from_email": "alerts@example.test",
                "use_tls": True,
            },
            "alerts": {
                "temperature_alerts_enabled": True,
                "temperature_min_threshold": 18.0,
                "temperature_max_threshold": 28.0,
            },
            "notifications": {
                "email_enabled": True,
                "mattermost_enabled": False,
                "slack_enabled": False,
            },
        }

    def get_temperature_alert_config(self):
        alerts = self.content["alerts"]
        return {
            "enabled": alerts["temperature_alerts_enabled"],
            "min_threshold": alerts["temperature_min_threshold"],
            "max_threshold": alerts["temperature_max_threshold"],
        }


@pytest.fixture
def fake_db():
    db = MagicMock()
    db.getAllUsers.return_value = {
        "ggilestro": {
            "id": 1,
            "username": "ggilestro",
            "email": "admin@example.test",
            "active": 1,
            "isadmin": 1,
        }
    }
    db.hasAlertBeenSent.return_value = False
    db.logAlert.return_value = None
    return db


def _build_notification_manager(config, db):
    """Build a NotificationManager with only a real EmailNotificationService.

    Dependency injection dodges the default _initialize_services() path, which
    would try to stand up the Mattermost/Slack clients from env vars.
    """
    from ethoscope_node.notifications.email import EmailNotificationService

    manager = NotificationManager.__new__(NotificationManager)
    manager.config = config
    manager.db = db
    manager.logger = MagicMock()
    manager._services = []

    email_service = EmailNotificationService(config=config, db=db)
    manager._services.append(("email", email_service))
    return manager


def test_over_threshold_sensor_reading_sends_email(fake_db, tmp_path):
    """A 45C sensor reading must travel end-to-end and reach smtplib."""
    config = _StubConfig()

    notification_manager = _build_notification_manager(config, fake_db)
    monitor = TemperatureAlertMonitor(
        config=config, notification_manager=notification_manager
    )

    scanner = SensorScanner(device_class=Sensor, results_dir=str(tmp_path))
    scanner._is_running = True
    scanner._config = config
    scanner._temperature_monitor = monitor

    with (
        patch("smtplib.SMTP_SSL") as mock_smtp_ssl,
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        # Discover the sensor — this is the path that was broken in production.
        scanner.add("192.168.1.250", 80, name="sensor-incubator-6A", device_id="6A")
        assert len(scanner.devices) == 1
        sensor = scanner.devices[0]
        assert (
            sensor._temperature_callback is not None
        ), "Temperature callback must be attached to newly-discovered sensors"

        # Mock the sensor HTTP responses: /id then /
        id_response = MagicMock()
        id_response.__enter__.return_value = id_response
        id_response.read.return_value = json.dumps({"id": "sensor_6A"}).encode()

        data_response = MagicMock()
        data_response.__enter__.return_value = data_response
        data_response.read.return_value = json.dumps(
            {
                "id": "sensor_6A",
                "name": "incubator-6A",
                "location": "lab-south",
                "temperature": 45.0,
                "humidity": 30.0,
                "pressure": 1013.0,
                "light": 0,
            }
        ).encode()
        mock_urlopen.side_effect = [id_response, data_response]

        smtp_instance = MagicMock()
        mock_smtp_ssl.return_value = smtp_instance

        # Trigger the full pipeline.
        sensor.save_to_csv = False
        sensor._update_info()

        mock_smtp_ssl.assert_called_once_with("smtp.example.test", 465)
        smtp_instance.send_message.assert_called_once()
        sent_msg = smtp_instance.send_message.call_args[0][0]
        assert sent_msg["To"] == "admin@example.test"
        assert "45.0" in sent_msg["Subject"]

        from ethoscope_node.notifications.temperature_monitor import AlertState

        assert monitor.get_alert_state("sensor_6A") == AlertState.ALERT_HIGH_SENT


def test_in_range_sensor_reading_does_not_send_email(fake_db, tmp_path):
    """A 22C reading must not trigger SMTP traffic."""
    config = _StubConfig()
    notification_manager = _build_notification_manager(config, fake_db)
    monitor = TemperatureAlertMonitor(
        config=config, notification_manager=notification_manager
    )

    scanner = SensorScanner(device_class=Sensor, results_dir=str(tmp_path))
    scanner._is_running = True
    scanner._temperature_monitor = monitor

    with (
        patch("smtplib.SMTP_SSL") as mock_smtp_ssl,
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        scanner.add("192.168.1.251", 80, name="sensor-ok", device_id="OK")
        sensor = scanner.devices[0]
        sensor.save_to_csv = False

        id_response = MagicMock()
        id_response.__enter__.return_value = id_response
        id_response.read.return_value = json.dumps({"id": "sensor_OK"}).encode()
        data_response = MagicMock()
        data_response.__enter__.return_value = data_response
        data_response.read.return_value = json.dumps(
            {
                "id": "sensor_OK",
                "name": "sensor-ok",
                "location": "lab",
                "temperature": 22.0,
            }
        ).encode()
        mock_urlopen.side_effect = [id_response, data_response]

        sensor._update_info()

        mock_smtp_ssl.assert_not_called()
