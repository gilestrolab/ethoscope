#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Notification system for Ethoscope alerts and monitoring.

This package provides extensible notification services for device events,
including email, and future support for telegram, whatsapp, etc.
"""

from .base import NotificationAnalyzer
from .email import EmailNotificationService

__all__ = ['NotificationAnalyzer', 'EmailNotificationService']