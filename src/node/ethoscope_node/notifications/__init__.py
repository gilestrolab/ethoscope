#!/usr/bin/env python

"""
Notification system for Ethoscope alerts and monitoring.

This package provides extensible notification services for device events,
including email, and future support for telegram, whatsapp, etc.
"""

from .base import NotificationAnalyzer
from .email import EmailNotificationService
from .manager import NotificationManager
from .mattermost import MattermostNotificationService
from .slack import SlackNotificationService

__all__ = [
    "NotificationAnalyzer",
    "EmailNotificationService",
    "MattermostNotificationService",
    "SlackNotificationService",
    "NotificationManager",
]
