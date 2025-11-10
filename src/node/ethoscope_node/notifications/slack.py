#!/usr/bin/env python

import datetime
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import requests

from ..utils.configuration import EthoscopeConfiguration
from ..utils.etho_db import ExperimentalDB
from .base import NotificationAnalyzer


class SlackNotificationService(NotificationAnalyzer):
    """
    Slack notification service for Ethoscope system alerts.

    Handles sending Slack notifications for device events like:
    - Device stopped unexpectedly
    - Storage warnings (80% full)
    - Device unreachable
    - Long-running experiments

    Supports both webhook and bot token authentication methods.
    """

    def __init__(
        self,
        config: Optional[EthoscopeConfiguration] = None,
        db: Optional[ExperimentalDB] = None,
    ):
        """
        Initialize Slack notification service.

        Args:
            config: Configuration instance, will create new one if None
            db: Database instance, will create new one if None
        """
        super().__init__(config, db)

        # Rate limiting: track last alert time per device/type
        self._last_alert_times = {}
        self._default_cooldown = 3600  # 1 hour between similar alerts

    def _get_slack_config(self) -> Dict[str, Any]:
        """Get Slack configuration from settings."""
        return self.config.content.get("slack", {})

    def _get_alert_config(self) -> Dict[str, Any]:
        """Get alert configuration from settings."""
        return self.config.content.get("alerts", {})

    def _should_send_alert(
        self, device_id: str, alert_type: str, run_id: str = None
    ) -> bool:
        """
        Check if we should send an alert based on rate limiting and database history.

        Args:
            device_id: Device identifier
            alert_type: Type of alert (device_stopped, storage_warning, etc.)
            run_id: Run ID for device_stopped alerts (prevents duplicates for same run)

        Returns:
            True if alert should be sent
        """
        # For device_stopped alerts, check database for duplicates based on run_id
        if alert_type == "device_stopped" and run_id:
            has_been_sent = self.db.hasAlertBeenSent(device_id, alert_type, run_id)
            if has_been_sent:
                self.logger.debug(
                    f"Alert {device_id}:{alert_type}:{run_id} already sent - preventing duplicate"
                )
                return False
        elif alert_type == "device_stopped" and not run_id:
            # For alerts without run_id, use timestamp-based approach to prevent spam
            self.logger.debug(
                "No run_id provided for device_stopped alert - using cooldown only"
            )

        # For other alerts or when no run_id, use traditional cooldown
        alert_config = self._get_alert_config()
        cooldown = alert_config.get("cooldown_seconds", self._default_cooldown)

        # Use run_id in key for device_stopped alerts, otherwise use traditional key
        if alert_type == "device_stopped" and run_id:
            key = f"{device_id}:{alert_type}:{run_id}"
        else:
            key = f"{device_id}:{alert_type}"

        current_time = time.time()

        if key in self._last_alert_times:
            time_since_last = current_time - self._last_alert_times[key]
            if time_since_last < cooldown:
                self.logger.debug(
                    f"Alert {key} suppressed due to cooldown ({time_since_last:.0f}s < {cooldown}s)"
                )
                return False

        self._last_alert_times[key] = current_time
        return True

    def _send_message(self, blocks: List[Dict[str, Any]], text: str = None) -> bool:
        """
        Send message to Slack using either webhook or bot token.

        Args:
            blocks: Slack Block Kit formatted message blocks
            text: Fallback text for notifications (optional)

        Returns:
            True if message sent successfully
        """
        config = self._get_slack_config()

        # Check if Slack is enabled
        if not config.get("enabled", False):
            self.logger.debug("Slack notifications are disabled")
            return False

        # Determine authentication method
        use_webhook = config.get("use_webhook", True)

        if use_webhook:
            return self._send_via_webhook(blocks, text)
        else:
            return self._send_via_bot_token(blocks, text)

    def _send_via_webhook(self, blocks: List[Dict[str, Any]], text: str = None) -> bool:
        """
        Send message via Slack webhook.

        Args:
            blocks: Slack Block Kit formatted message blocks
            text: Fallback text for notifications

        Returns:
            True if message sent successfully
        """
        config = self._get_slack_config()
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            self.logger.error("Slack webhook URL not configured")
            return False

        payload = {"blocks": blocks}

        # Add text fallback if provided
        if text:
            payload["text"] = text

        # Add channel override if specified
        channel = config.get("channel")
        if channel:
            payload["channel"] = channel

        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()

            if response.text.strip() == "ok":
                self.logger.info("Slack webhook message sent successfully")
                return True
            else:
                self.logger.error(
                    f"Slack webhook returned unexpected response: {response.text}"
                )
                return False

        except requests.RequestException as e:
            self.logger.error(f"Failed to send Slack webhook message: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error sending Slack webhook message: {e}")
            return False

    def _send_via_bot_token(
        self, blocks: List[Dict[str, Any]], text: str = None
    ) -> bool:
        """
        Send message via Slack bot token (chat.postMessage API).

        Args:
            blocks: Slack Block Kit formatted message blocks
            text: Fallback text for notifications

        Returns:
            True if message sent successfully
        """
        config = self._get_slack_config()
        bot_token = config.get("bot_token")
        channel = config.get("channel", "#general")

        if not bot_token:
            self.logger.error("Slack bot token not configured")
            return False

        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json",
        }

        payload = {"channel": channel, "blocks": blocks}

        # Add text fallback if provided
        if text:
            payload["text"] = text

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get("ok"):
                self.logger.info(f"Slack bot message sent successfully to {channel}")
                return True
            else:
                error = result.get("error", "Unknown error")
                self.logger.error(f"Slack bot API returned error: {error}")
                return False

        except requests.RequestException as e:
            self.logger.error(f"Failed to send Slack bot message: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error sending Slack bot message: {e}")
            return False

    def _create_device_stopped_blocks(
        self,
        device_name: str,
        device_id: str,
        failure_analysis: Dict[str, Any],
        run_id: str,
        last_seen: datetime.datetime,
        device_logs: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Create Slack Block Kit blocks for device stopped alert.

        Args:
            device_name: Human-readable device name
            device_id: Device identifier
            failure_analysis: Device failure analysis from base class
            run_id: Run identifier
            last_seen: Last time device was seen
            device_logs: Optional device logs

        Returns:
            List of Slack Block Kit blocks
        """
        blocks = []

        # Header block with alert emoji and title
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 Device Alert: {device_name} stopped",
                    "emoji": True,
                },
            }
        )

        # Main information section
        info_fields = [
            {"type": "mrkdwn", "text": f"*Device:* {device_name} ({device_id})"},
            {
                "type": "mrkdwn",
                "text": f"*Status:* {failure_analysis.get('status', 'Unknown')}",
            },
            {"type": "mrkdwn", "text": f"*Run ID:* {run_id}"},
            {
                "type": "mrkdwn",
                "text": f"*Last Seen:* {last_seen.strftime('%Y-%m-%d %H:%M:%S')}",
            },
        ]

        # Add experiment details if available
        if failure_analysis.get("user"):
            info_fields.append(
                {"type": "mrkdwn", "text": f"*User:* {failure_analysis['user']}"}
            )
        if failure_analysis.get("location"):
            info_fields.append(
                {
                    "type": "mrkdwn",
                    "text": f"*Location:* {failure_analysis['location']}",
                }
            )
        if failure_analysis.get("experiment_duration_str"):
            info_fields.append(
                {
                    "type": "mrkdwn",
                    "text": f"*Duration:* {failure_analysis['experiment_duration_str']}",
                }
            )
        if failure_analysis.get("experiment_type"):
            info_fields.append(
                {
                    "type": "mrkdwn",
                    "text": f"*Type:* {failure_analysis['experiment_type'].title()}",
                }
            )

        blocks.append({"type": "section", "fields": info_fields})

        # Problems section if any issues exist
        problems = []
        if failure_analysis.get("problems"):
            problems.append(f"• Run issues: {failure_analysis['problems']}")
        if failure_analysis.get("device_problems"):
            problems.append(f"• Device issues: {failure_analysis['device_problems']}")

        if problems:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Issues:*\n" + "\n".join(problems),
                    },
                }
            )

        # Recent logs section if available
        if device_logs:
            log_lines = device_logs.strip().split("\n")
            if log_lines:
                recent_logs = "\n".join(log_lines[-5:])  # Show last 5 lines
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Recent logs:*\n```{recent_logs}```",
                        },
                    }
                )

        # Action recommendations
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Recommended actions:*\n• Check device power and network connection\n• Review device status in web interface\n• Check for hardware issues\n• Restart device if necessary",
                },
            }
        )

        return blocks

    def send_device_stopped_alert(
        self,
        device_id: str,
        device_name: str,
        run_id: str,
        last_seen: datetime.datetime,
    ) -> bool:
        """
        Send alert when device has stopped unexpectedly.

        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            run_id: Run identifier
            last_seen: Last time device was seen

        Returns:
            True if alert sent successfully
        """
        if not self._should_send_alert(device_id, "device_stopped", run_id):
            return False

        try:
            # Get comprehensive device failure analysis
            failure_analysis = self.analyze_device_failure(device_id)

            # Don't send alert if the run completed normally
            failure_type = failure_analysis.get("failure_type", "")
            if failure_type == "completed_normally":
                self.logger.info(
                    f"Suppressing alert for device {device_id} - run {run_id} completed normally"
                )
                return False

            # Get device logs for context
            device_logs = self.get_device_logs(device_id, max_lines=10)

            # Create Slack blocks
            blocks = self._create_device_stopped_blocks(
                device_name, device_id, failure_analysis, run_id, last_seen, device_logs
            )

            # Fallback text for notifications
            fallback_text = f"🚨 Device Alert: {device_name} ({device_id}) has stopped unexpectedly. Run ID: {run_id}"

            # Send the message
            success = self._send_message(blocks, fallback_text)

            # Log alert in database if sent successfully
            if success:
                if blocks:  # Ensure blocks is not empty before logging
                    try:
                        self.db.logAlert(
                            device_id, "device_stopped", fallback_text, "slack", run_id
                        )
                    except Exception as e:
                        self.logger.warning(f"Failed to log alert in database: {e}")
                else:
                    self.logger.warning(
                        f"Attempted to log an empty alert message for device {device_id}, type device_stopped. Skipping database log."
                    )

            return success

        except Exception as e:
            self.logger.error(f"Error sending device stopped alert: {e}")
            return False

    def send_storage_warning_alert(
        self,
        device_id: str,
        device_name: str,
        storage_percent: float,
        available_space: str,
    ) -> bool:
        """
        Send alert when device storage is running low.

        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            storage_percent: Percentage of storage used
            available_space: Amount of available space remaining

        Returns:
            True if alert sent successfully
        """
        if not self._should_send_alert(device_id, "storage_warning"):
            return False

        try:
            # Create storage warning blocks
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"⚠️ Storage Warning: {device_name}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Device:* {device_name} ({device_id})",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Storage Used:* {storage_percent:.1f}%",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Available Space:* {available_space}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Status:* {'🔴 Critical' if storage_percent > 90 else '🟡 Warning'}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Recommended actions:*\n• Check device data folder for cleanup opportunities\n• Ensure backup processes are running\n• Consider stopping non-essential experiments\n• Contact system administrator if needed",
                    },
                },
            ]

            fallback_text = f"⚠️ Storage Warning: {device_name} ({device_id}) storage is {storage_percent:.1f}% full. Available: {available_space}"

            return self._send_message(blocks, fallback_text)

        except Exception as e:
            self.logger.error(f"Error sending storage warning alert: {e}")
            return False

    def send_device_unreachable_alert(
        self, device_id: str, device_name: str, last_seen: datetime.datetime
    ) -> bool:
        """
        Send alert when device becomes unreachable.

        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            last_seen: Last time device was reachable

        Returns:
            True if alert sent successfully
        """
        if not self._should_send_alert(device_id, "device_unreachable"):
            return False

        try:
            # Calculate offline duration
            time_offline = datetime.datetime.now() - last_seen
            offline_str = self._format_duration(time_offline.total_seconds())

            # Create unreachable alert blocks
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"📵 Device Unreachable: {device_name}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Device:* {device_name} ({device_id})",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Last Seen:* {last_seen.strftime('%Y-%m-%d %H:%M:%S')}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Offline Duration:* {offline_str}",
                        },
                        {"type": "mrkdwn", "text": "*Status:* 🔴 Offline"},
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Device may have network issues or be powered off.*\n\n*Recommended actions:*\n• Check device power status\n• Verify network connectivity\n• Check for hardware issues\n• Restart device if necessary\n• Review web interface for details",
                    },
                },
            ]

            fallback_text = f"📵 Device Unreachable: {device_name} ({device_id}) has been offline since {last_seen.strftime('%Y-%m-%d %H:%M:%S')}"

            return self._send_message(blocks, fallback_text)

        except Exception as e:
            self.logger.error(f"Error sending device unreachable alert: {e}")
            return False

    def test_slack_configuration(self) -> Dict[str, Any]:
        """
        Test Slack configuration by sending a test message.

        Returns:
            Dictionary with test results
        """
        try:
            config = self._get_slack_config()

            if not config.get("enabled", False):
                return {
                    "success": False,
                    "error": "Slack notifications are disabled in configuration",
                }

            # Check required configuration based on method
            use_webhook = config.get("use_webhook", True)

            if use_webhook:
                webhook_url = config.get("webhook_url")
                if not webhook_url:
                    return {
                        "success": False,
                        "error": "Slack webhook URL not configured",
                    }
            else:
                bot_token = config.get("bot_token")
                channel = config.get("channel")
                if not bot_token:
                    return {"success": False, "error": "Slack bot token not configured"}
                if not channel:
                    return {
                        "success": False,
                        "error": "Slack channel not configured for bot token method",
                    }

            # Create test message blocks
            test_blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🧪 Ethoscope Test Message",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Slack notifications are working correctly! ✅",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Test sent:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        }
                    ],
                },
            ]

            fallback_text = (
                "🧪 Ethoscope Test Message - Slack notifications are working correctly!"
            )

            success = self._send_message(test_blocks, fallback_text)

            if success:
                result = {
                    "success": True,
                    "method": "webhook" if use_webhook else "bot_token",
                    "message": "Test message sent successfully",
                }
                if use_webhook:
                    result["webhook_configured"] = True
                else:
                    result["channel"] = config.get("channel")
                return result
            else:
                return {
                    "success": False,
                    "error": "Failed to send test message (check logs for details)",
                }

        except Exception as e:
            self.logger.error(f"Error testing Slack configuration: {e}")
            return {"success": False, "error": f"Exception during test: {str(e)}"}
