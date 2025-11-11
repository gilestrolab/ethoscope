"""
Setup API Module

Handles installation wizard and first-time setup functionality.
"""

import os
from pathlib import Path

import bottle

from ethoscope_node.utils.etho_db import ExperimentalDB

from .base import BaseAPI
from .base import error_decorator


class SetupAPI(BaseAPI):
    """API endpoints for installation wizard and setup management."""

    def register_routes(self):
        """Register setup-related routes."""
        self.app.route("/setup/<action>", method="GET")(self._setup_get)
        self.app.route("/setup/<action>", method="POST")(self._setup_post)

    @error_decorator
    def _setup_get(self, action):
        """Handle GET requests for setup information."""
        if action == "status":
            return self._get_setup_status()
        elif action == "system-info":
            return self._get_system_info()
        elif action == "validate-folders":
            return self._validate_folders()
        elif action == "current-config":
            return self._get_current_config()
        elif action == "existing-users":
            return self._get_existing_users()
        else:
            bottle.abort(404, f"Setup action '{action}' not found")

    @error_decorator
    def _setup_post(self, action):
        """Handle POST requests for setup actions."""
        print(f"DEBUG: Received POST action: '{action}'")
        if action == "basic-info":
            return self._setup_basic_info()
        elif action == "admin-user":
            return self._setup_admin_user()
        elif action == "add-user":
            return self._setup_add_user()
        elif action == "update-user":
            return self._setup_update_user()
        elif action == "add-incubator":
            return self._setup_add_incubator()
        elif action == "update-incubator":
            return self._setup_update_incubator()
        elif action == "notifications":
            return self._setup_notifications()
        elif action == "test-notifications":
            return self._test_notifications()
        elif action == "virtual-sensor":
            return self._setup_virtual_sensor()
        elif action == "test-weather-api":
            return self._test_weather_api()
        elif action == "tunnel":
            return self._setup_tunnel()
        elif action == "complete":
            return self._complete_setup()
        elif action == "reset":
            return self._reset_setup()
        elif action == "current-config":
            return self._get_current_config()
        else:
            bottle.abort(404, f"Setup action '{action}' not found")

    def _get_setup_status(self):
        """Get current setup status and progress."""
        return self.config.get_setup_status()

    def _get_system_info(self):
        """Get system information for setup validation."""
        import socket

        import psutil

        # Get hostname
        try:
            hostname = socket.gethostname()
            fqdn = socket.getfqdn()
        except Exception:
            hostname = "unknown"
            fqdn = "unknown"

        # Get disk usage for important paths
        disk_info = {}
        for path_name, path_config in self.config.content.get("folders", {}).items():
            try:
                path = path_config.get("path", "")
                if path and os.path.exists(path):
                    usage = psutil.disk_usage(path)
                    disk_info[path_name] = {
                        "path": path,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": (usage.used / usage.total) * 100,
                    }
            except Exception as e:
                self.logger.warning(f"Error getting disk usage for {path_name}: {e}")

        # Get memory info
        try:
            memory = psutil.virtual_memory()
            memory_info = {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
                "used": memory.used,
            }
        except Exception:
            memory_info = {}

        return {
            "hostname": hostname,
            "fqdn": fqdn,
            "disk_usage": disk_info,
            "memory": memory_info,
            "python_version": os.sys.version,
            "current_user": os.getenv("USER", "unknown"),
        }

    def _validate_folders(self):
        """Validate folder paths and permissions."""
        data = self.get_request_json()
        folders = data.get("folders", {})

        validation_results = {}

        for folder_name, folder_path in folders.items():
            result = {
                "path": folder_path,
                "valid": False,
                "exists": False,
                "writable": False,
                "readable": False,
                "errors": [],
            }

            try:
                # Check if path exists
                path = Path(folder_path)
                if path.exists():
                    result["exists"] = True

                    # Check if it's a directory
                    if not path.is_dir():
                        result["errors"].append("Path exists but is not a directory")
                    else:
                        # Check permissions
                        result["readable"] = os.access(folder_path, os.R_OK)
                        result["writable"] = os.access(folder_path, os.W_OK)

                        if not result["readable"]:
                            result["errors"].append("Directory is not readable")
                        if not result["writable"]:
                            result["errors"].append("Directory is not writable")

                        if result["readable"] and result["writable"]:
                            result["valid"] = True
                else:
                    # Try to create the directory
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        result["exists"] = True
                        result["readable"] = True
                        result["writable"] = True
                        result["valid"] = True
                    except Exception as e:
                        result["errors"].append(f"Could not create directory: {e}")

            except Exception as e:
                result["errors"].append(f"Error validating path: {e}")

            validation_results[folder_name] = result

        return {"validation_results": validation_results}

    def _get_existing_users(self):
        """Get existing users from the database for admin replacement option."""
        try:
            users = self.db.get_all_users()
            user_list = []

            for user in users:
                user_info = {
                    "username": user.get("username", ""),
                    "fullname": user.get("fullname", ""),
                    "email": user.get("email", ""),
                    "labname": user.get("labname", ""),
                }
                user_list.append(user_info)

            return {"result": "success", "users": user_list}
        except Exception as e:
            return {
                "result": "error",
                "message": f"Failed to fetch existing users: {str(e)}",
            }

    def _setup_basic_info(self):
        """Configure basic system information."""
        data = self.get_request_json()

        # Update folder paths if provided
        folders = data.get("folders", {})
        if folders:
            current_folders = self.config.content.get("folders", {})

            for folder_name, folder_path in folders.items():
                if folder_name in current_folders:
                    # Create directory if it doesn't exist
                    try:
                        Path(folder_path).mkdir(parents=True, exist_ok=True)
                        current_folders[folder_name]["path"] = folder_path
                    except Exception as e:
                        self.logger.error(f"Error creating folder {folder_path}: {e}")
                        return {
                            "result": "error",
                            "message": f"Could not create folder {folder_path}: {e}",
                        }

            # Update configuration
            self.config._settings["folders"] = current_folders
            self.config.save()

        # Mark step as completed
        self.config.mark_setup_step_completed("basic_info")

        return {
            "result": "success",
            "message": "Basic configuration updated successfully",
        }

    def _setup_admin_user(self):
        """Create or replace admin user."""
        data = self.get_request_json()

        try:
            db = ExperimentalDB()

            # Get required user data
            user_data = {
                "username": data.get("username", "").strip(),
                "fullname": data.get("fullname", "").strip(),
                "email": data.get("email", "").strip(),
                "pin": data.get("pin", "").strip(),
                "telephone": data.get("telephone", "").strip(),
                "labname": data.get("labname", "").strip(),
                "active": 1,
                "isadmin": 1,
            }

            # Validate required fields
            if not user_data["username"]:
                return {"result": "error", "message": "Username is required"}
            if not user_data["email"]:
                return {"result": "error", "message": "Email is required"}

            # Check if user already exists
            existing_user = db.getUserByName(user_data["username"])

            if existing_user:
                # Update existing user
                updates_data = {k: v for k, v in user_data.items() if k != "username"}
                self.logger.info(
                    f"Updating user {user_data['username']} with data: {updates_data}"
                )
                result = db.updateUser(username=user_data["username"], **updates_data)
                self.logger.info(f"Update result: {result}")

                if result >= 0:
                    self.config.mark_setup_step_completed("admin_user")
                    return {
                        "result": "success",
                        "message": f'Admin user {user_data["username"]} updated successfully',
                        "user_id": existing_user["id"],
                    }
                else:
                    return {"result": "error", "message": "Failed to update admin user"}
            else:
                # Check if replacing existing admin user
                replace_user = data.get("replace_user")
                if replace_user:
                    # Deactivate the existing user
                    existing_replace_user = db.getUserByName(replace_user)
                    if existing_replace_user:
                        db.deactivateUser(username=replace_user)
                        self.logger.info(
                            f"Deactivated existing admin user: {replace_user}"
                        )

                # Add new admin user
                result = db.addUser(**user_data)

                if result > 0:
                    self.config.mark_setup_step_completed("admin_user")
                    return {
                        "result": "success",
                        "message": f'Admin user {user_data["username"]} created successfully',
                        "user_id": result,
                    }
                else:
                    return {"result": "error", "message": "Failed to create admin user"}

        except Exception as e:
            self.logger.error(f"Error creating admin user: {e}")
            return {"result": "error", "message": str(e)}

    def _setup_add_user(self):
        """Add additional user."""
        data = self.get_request_json()

        try:
            db = ExperimentalDB()

            # Get user data
            user_data = {
                "username": data.get("username", "").strip(),
                "fullname": data.get("fullname", "").strip(),
                "email": data.get("email", "").strip(),
                "pin": data.get("pin", "").strip(),
                "telephone": data.get("telephone", "").strip(),
                "labname": data.get("labname", "").strip(),
                "active": 1,
                "isadmin": 1 if data.get("isadmin", False) else 0,
            }

            # Validate required fields
            if not user_data["username"]:
                return {"result": "error", "message": "Username is required"}
            if not user_data["email"]:
                return {"result": "error", "message": "Email is required"}

            # Add user
            result = db.addUser(**user_data)

            if result > 0:
                return {
                    "result": "success",
                    "message": f'User {user_data["username"]} created successfully',
                    "user_id": result,
                }
            else:
                return {"result": "error", "message": "Failed to create user"}

        except Exception as e:
            self.logger.error(f"Error creating user: {e}")
            return {"result": "error", "message": str(e)}

    def _setup_update_user(self):
        """Update user."""
        data = self.get_request_json()

        try:
            db = ExperimentalDB()

            # Get the original username to identify the user
            original_username = data.get("original_username", "").strip()
            if not original_username:
                return {
                    "result": "error",
                    "message": "Original username is required for update",
                }

            # Get updated user data
            update_data = {}
            new_username = None
            if "username" in data and data["username"].strip():
                new_username = data["username"].strip()
                if new_username != original_username:
                    update_data["username"] = new_username
            if "fullname" in data:
                update_data["fullname"] = data["fullname"].strip()
            if "email" in data:
                update_data["email"] = data["email"].strip()
            if "pin" in data:
                update_data["pin"] = data["pin"].strip()
            if "telephone" in data:
                update_data["telephone"] = data["telephone"].strip()
            if "labname" in data:
                update_data["labname"] = data["labname"].strip()
            if "isadmin" in data:
                update_data["isadmin"] = 1 if data.get("isadmin", False) else 0

            # Validate required fields
            if new_username and not new_username:
                return {"result": "error", "message": "Username cannot be empty"}
            if "email" in update_data and not update_data["email"]:
                return {"result": "error", "message": "Email cannot be empty"}

            # Update user by username
            result = db.updateUser(username=original_username, **update_data)

            if (
                result >= 0
            ):  # 0 means no changes needed, >= 1 means rows updated, -1 means error
                return {"result": "success", "message": "User updated successfully"}
            else:
                return {"result": "error", "message": "Failed to update user"}

        except Exception as e:
            self.logger.error(f"Error updating user: {e}")
            return {"result": "error", "message": str(e)}

    def _setup_add_incubator(self):
        """Add incubator."""
        data = self.get_request_json()

        try:
            db = ExperimentalDB()

            # Get incubator data
            incubator_data = {
                "name": data.get("name", "").strip(),
                "location": data.get("location", "").strip(),
                "owner": data.get("owner", "").strip(),
                "description": data.get("description", "").strip(),
                "active": 1,
            }

            # Validate required fields
            if not incubator_data["name"]:
                return {"result": "error", "message": "Incubator name is required"}

            # Add incubator
            result = db.addIncubator(**incubator_data)

            if result > 0:
                return {
                    "result": "success",
                    "message": f'Incubator {incubator_data["name"]} created successfully',
                    "incubator_id": result,
                }
            else:
                return {"result": "error", "message": "Failed to create incubator"}

        except Exception as e:
            self.logger.error(f"Error creating incubator: {e}")
            return {"result": "error", "message": str(e)}

    def _setup_update_incubator(self):
        """Update incubator."""
        data = self.get_request_json()

        try:
            db = ExperimentalDB()

            # Get the original name to identify the incubator
            original_name = data.get("original_name", "").strip()
            if not original_name:
                return {
                    "result": "error",
                    "message": "Original incubator name is required for update",
                }

            # Get updated incubator data
            update_data = {}
            new_name = None
            if "name" in data and data["name"].strip():
                new_name = data["name"].strip()
                if new_name != original_name:
                    update_data["name"] = new_name
            if "location" in data:
                update_data["location"] = data["location"].strip()
            if "owner" in data:
                update_data["owner"] = data["owner"].strip()
            if "description" in data:
                update_data["description"] = data["description"].strip()

            # Validate required fields
            if new_name and not new_name:
                return {"result": "error", "message": "Incubator name cannot be empty"}

            # Update incubator by name
            result = db.updateIncubator(name=original_name, **update_data)

            if (
                result >= 0
            ):  # 0 means no changes needed, >= 1 means rows updated, -1 means error
                return {
                    "result": "success",
                    "message": "Incubator updated successfully",
                }
            else:
                return {"result": "error", "message": "Failed to update incubator"}

        except Exception as e:
            self.logger.error(f"Error updating incubator: {e}")
            return {"result": "error", "message": str(e)}

    def _setup_notifications(self):
        """Configure notification settings."""
        data = self.get_request_json()

        try:
            # Update SMTP settings (stored directly under 'smtp' key)
            smtp_config = data.get("smtp", {})
            if smtp_config:
                current_smtp = self.config._settings.get("smtp", {})

                # Handle masked password - preserve existing password if user didn't change it
                submitted_password = smtp_config.get("password", "")
                if submitted_password == "***CONFIGURED***" and current_smtp.get(
                    "password"
                ):
                    # User didn't change the masked password, preserve existing one
                    actual_password = current_smtp.get("password")
                else:
                    # User provided a new password (or cleared it)
                    actual_password = submitted_password

                smtp_settings = {
                    "enabled": smtp_config.get("enabled", False),
                    "host": smtp_config.get("host", "localhost"),
                    "port": int(smtp_config.get("port", 587)),
                    "use_tls": smtp_config.get("use_tls", True),
                    "username": smtp_config.get("username", ""),
                    "password": actual_password,
                    "from_email": smtp_config.get("from_email", "ethoscope@localhost"),
                }

                # Store directly under 'smtp' key (matching configuration.py structure)
                self.config._settings["smtp"] = smtp_settings

            # Update Mattermost settings (stored directly under 'mattermost' key)
            mattermost_config = data.get("mattermost", {})
            if mattermost_config:
                current_mattermost = self.config._settings.get("mattermost", {})

                # Handle masked token - preserve existing token if user didn't change it
                submitted_token = mattermost_config.get("bot_token", "")
                if submitted_token == "***CONFIGURED***" and current_mattermost.get(
                    "bot_token"
                ):
                    # User didn't change the masked token, preserve existing one
                    actual_token = current_mattermost.get("bot_token")
                else:
                    # User provided a new token (or cleared it)
                    actual_token = submitted_token

                mattermost_settings = {
                    "enabled": mattermost_config.get("enabled", False),
                    "server_url": mattermost_config.get("server_url", ""),
                    "bot_token": actual_token,
                    "channel_id": mattermost_config.get("channel_id", ""),
                }

                # Store directly under 'mattermost' key (matching configuration.py structure)
                self.config._settings["mattermost"] = mattermost_settings

            # Update Slack settings (stored directly under 'slack' key)
            slack_config = data.get("slack", {})
            if slack_config:
                current_slack = self.config._settings.get("slack", {})

                # Handle masked webhook URL - preserve existing URL if user didn't change it
                submitted_webhook_url = slack_config.get("webhook_url", "")
                if submitted_webhook_url == "***CONFIGURED***" and current_slack.get(
                    "webhook_url"
                ):
                    # User didn't change the masked webhook URL, preserve existing one
                    actual_webhook_url = current_slack.get("webhook_url")
                else:
                    # User provided a new webhook URL (or cleared it)
                    actual_webhook_url = submitted_webhook_url

                slack_settings = {
                    "enabled": slack_config.get("enabled", False),
                    "webhook_url": actual_webhook_url,
                    "channel": slack_config.get("channel", ""),
                    "use_webhook": slack_config.get("use_webhook", True),
                    "use_manual_setup": slack_config.get("use_manual_setup", False),
                }

                # Store directly under 'slack' key (matching configuration.py structure)
                self.config._settings["slack"] = slack_settings

            # Save configuration
            self.config.save()
            self.config.mark_setup_step_completed("notifications")

            return {
                "result": "success",
                "message": "Notification settings updated successfully",
            }

        except Exception as e:
            self.logger.error(f"Error updating notification settings: {e}")
            return {"result": "error", "message": str(e)}

    def _setup_tunnel(self):
        """Configure tunnel settings."""
        data = self.get_request_json()

        try:
            # Get current token to preserve it if masked value is sent
            current_tunnel_config = self.config._settings.get("tunnel", {})
            current_token = current_tunnel_config.get("token", "")

            # Handle masked token - preserve existing token if user didn't change it
            submitted_token = data.get("token", "")
            if submitted_token == "***CONFIGURED***" and current_token:
                # User didn't change the masked token, preserve existing one
                actual_token = current_token
            else:
                # User provided a new token (or cleared it)
                actual_token = submitted_token

            # Update tunnel configuration with dual mode support
            tunnel_config = {
                "enabled": data.get("tunnel_enabled", False),
                "mode": data.get("tunnel_mode", "custom"),
                "token": actual_token,
                "node_id": data.get("node_id", "auto"),
                "domain": data.get("domain", "ethoscope.net"),
                "custom_domain": data.get(
                    "custom_domain", ""
                ),  # For custom domain mode
            }

            # Extract authentication setting for separate configuration
            auth_config = {"enabled": data.get("authentication_enabled", False)}

            # Validate configuration based on mode
            if tunnel_config["enabled"]:
                if not tunnel_config["token"]:
                    return {
                        "result": "error",
                        "message": "Tunnel token is required when tunnel is enabled",
                    }

                if (
                    tunnel_config["mode"] == "custom"
                    and not tunnel_config["custom_domain"]
                ):
                    return {
                        "result": "error",
                        "message": "Custom domain is required for free mode",
                    }

                if not auth_config["enabled"]:
                    return {
                        "result": "error",
                        "message": "Authentication must be enabled when remote access is active for security reasons",
                    }

            # Update configuration using the existing methods
            self.config.update_tunnel_config(tunnel_config)
            self.config.update_authentication_config(auth_config)

            # Update the tunnel environment file if server is available
            if hasattr(self, "server") and self.server:
                self.server._update_tunnel_environment()

            # Mark this setup step as completed
            self.config.mark_setup_step_completed("tunnel")

            return {
                "result": "success",
                "message": "Tunnel settings updated successfully",
            }

        except Exception as e:
            self.logger.error(f"Error updating tunnel settings: {e}")
            return {"result": "error", "message": str(e)}

    def _test_notifications(self):
        """Test notification configuration."""
        data = self.get_request_json()
        test_type = data.get("type", "smtp")

        try:
            if test_type == "smtp":
                return self._test_smtp(data.get("config", {}))
            elif test_type == "mattermost":
                return self._test_mattermost(data.get("config", {}))
            elif test_type == "slack":
                return self._test_slack(data.get("config", {}))
            else:
                return {"result": "error", "message": f"Unknown test type: {test_type}"}

        except Exception as e:
            self.logger.error(f"Error testing {test_type} configuration: {e}")
            return {"result": "error", "message": str(e)}

    def _test_smtp(self, smtp_config):
        """Test SMTP configuration by sending a test email."""
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        try:
            # Get configuration
            host = smtp_config.get("host", "localhost")
            port = int(smtp_config.get("port", 587))
            use_tls = smtp_config.get("use_tls", True)
            username = smtp_config.get("username", "")
            password = smtp_config.get("password", "")
            from_email = smtp_config.get("from_email", "ethoscope@localhost")
            test_email = smtp_config.get("test_email", from_email)

            # Create test message
            msg = MIMEMultipart()
            msg["From"] = from_email
            msg["To"] = test_email
            msg["Subject"] = "Ethoscope Node - SMTP Configuration Test"

            body = """
This is a test email sent from the Ethoscope Node installation wizard.
If you receive this message, your SMTP configuration is working correctly.

Best regards,
Ethoscope Node Setup Wizard
"""
            msg.attach(MIMEText(body, "plain"))

            # Connect and send email with timeout
            server = None
            try:
                # Try SMTP_SSL first for port 465, then regular SMTP
                if port == 465:
                    server = smtplib.SMTP_SSL(host, port, timeout=10)
                    server.ehlo()  # Identify ourselves
                else:
                    server = smtplib.SMTP(host, port, timeout=10)
                    server.ehlo()  # Identify ourselves

                    if use_tls:
                        server.starttls()
                        server.ehlo()  # Re-identify after STARTTLS

                if username and password:
                    server.login(username, password)

                server.send_message(msg)

            finally:
                if server:
                    try:
                        server.quit()
                    except Exception:
                        pass  # Ignore quit errors

            return {
                "result": "success",
                "message": f"Test email sent successfully to {test_email}",
            }

        except Exception as e:
            return {"result": "error", "message": f"SMTP test failed: {str(e)}"}

    def _test_mattermost(self, mattermost_config):
        """Test Mattermost configuration by sending a test message."""
        import requests

        try:
            # Get configuration
            server_url = mattermost_config.get("server_url", "").rstrip("/")
            bot_token = mattermost_config.get("bot_token", "")
            channel_id = mattermost_config.get("channel_id", "")

            if not all([server_url, bot_token, channel_id]):
                return {
                    "result": "error",
                    "message": "Server URL, bot token, and channel ID are required",
                }

            # Prepare test message
            message = {
                "channel_id": channel_id,
                "message": "This is a test message from the Ethoscope Node installation wizard. If you see this, your Mattermost configuration is working correctly!",
            }

            headers = {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json",
            }

            # Send test message
            response = requests.post(
                f"{server_url}/api/v4/posts", json=message, headers=headers, timeout=10
            )

            if response.status_code == 201:
                return {
                    "result": "success",
                    "message": "Test message sent successfully to Mattermost",
                }
            else:
                return {
                    "result": "error",
                    "message": f"Mattermost test failed: HTTP {response.status_code} - {response.text}",
                }

        except Exception as e:
            return {"result": "error", "message": f"Mattermost test failed: {str(e)}"}

    def _test_slack(self, slack_config):
        """Test Slack configuration by sending a test message."""
        import requests

        try:
            # Get configuration
            webhook_url = slack_config.get("webhook_url", "")
            channel = slack_config.get("channel", "")

            # Handle masked webhook URL - use the actual stored URL if masked value is sent
            if webhook_url == "***CONFIGURED***":
                current_slack = self.config._settings.get("slack", {})
                webhook_url = current_slack.get("webhook_url", "")

            if not webhook_url:
                return {
                    "result": "error",
                    "message": "Webhook URL is required for Slack testing",
                }

            # Prepare test message with Block Kit formatting
            message = {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "🧪 *Ethoscope Test Message*",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "This is a test message from the Ethoscope Node installation wizard. If you see this, your Slack configuration is working correctly!",
                        },
                    },
                ],
                "text": "🧪 Ethoscope Test Message - Slack notifications are working correctly!",
            }

            # Add channel override if specified
            if channel:
                message["channel"] = channel

            # Send test message
            response = requests.post(webhook_url, json=message, timeout=10)

            if response.status_code == 200:
                return {
                    "result": "success",
                    "message": "Test message sent successfully to Slack",
                }
            else:
                return {
                    "result": "error",
                    "message": f"Slack test failed: HTTP {response.status_code} - {response.text}",
                }

        except Exception as e:
            return {"result": "error", "message": f"Slack test failed: {str(e)}"}

    def _setup_virtual_sensor(self):
        """Configure virtual sensor settings."""
        try:
            data = bottle.request.json
            if not data:
                return {"result": "error", "message": "No data provided"}

            # Validate required fields if enabled
            if data.get("enabled", False):
                required_fields = ["sensor_name", "location"]
                for field in required_fields:
                    if not data.get(field):
                        return {
                            "result": "error",
                            "message": f"Missing required field: {field}",
                        }

            # Update virtual sensor configuration
            config_data = self.config.config
            if "virtual_sensor" not in config_data:
                config_data["virtual_sensor"] = {}

            config_data["virtual_sensor"].update(
                {
                    "enabled": data.get("enabled", False),
                    "sensor_name": data.get("sensor_name", "virtual-sensor"),
                    "location": data.get("location", "Lab"),
                    "weather_location": data.get("weather_location", ""),
                    "api_key": data.get("api_key", ""),
                }
            )

            # Save configuration
            self.config.save_config()

            return {
                "result": "success",
                "message": "Virtual sensor configured successfully",
            }

        except Exception as e:
            return {
                "result": "error",
                "message": f"Failed to configure virtual sensor: {str(e)}",
            }

    def _test_weather_api(self):
        """Test weather API connection."""
        try:
            data = bottle.request.json
            if not data:
                return {"result": "error", "message": "No data provided"}

            weather_location = data.get("weather_location")
            api_key = data.get("api_key")

            if not weather_location or not api_key:
                return {
                    "result": "error",
                    "message": "Weather location and API key are required",
                }

            # Test the weather API
            import json
            import urllib.error
            import urllib.request

            # Determine URL format based on location
            if "," in weather_location and len(weather_location.split(",")) == 2:
                # Check if it's lat,lon coordinates
                try:
                    lat, lon = weather_location.split(",")
                    float(lat)  # Test if it's numeric
                    float(lon)
                    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
                except ValueError:
                    # It's city,country format
                    url = f"https://api.openweathermap.org/data/2.5/weather?q={weather_location}&appid={api_key}&units=metric"
            elif weather_location.isdigit():
                # City ID format
                url = f"https://api.openweathermap.org/data/2.5/weather?id={weather_location}&appid={api_key}&units=metric"
            else:
                # City name or other query format
                url = f"https://api.openweathermap.org/data/2.5/weather?q={weather_location}&appid={api_key}&units=metric"

            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    weather_data = json.loads(response.read().decode())

                return {
                    "success": True,
                    "temperature": weather_data["main"]["temp"],
                    "humidity": weather_data["main"]["humidity"],
                    "pressure": weather_data["main"]["pressure"],
                    "location": weather_data["name"],
                    "country": weather_data["sys"]["country"],
                }

            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return {
                        "success": False,
                        "message": "Invalid API key. Please check your OpenWeatherMap API key.",
                    }
                elif e.code == 404:
                    return {
                        "success": False,
                        "message": "Location not found. Please check your location format.",
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Weather API error: HTTP {e.code}",
                    }
            except urllib.error.URLError as e:
                return {"success": False, "message": f"Network error: {str(e)}"}
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "message": "Invalid response from weather API",
                }
            except KeyError as e:
                return {
                    "success": False,
                    "message": f"Unexpected response format: missing {str(e)}",
                }

        except Exception as e:
            return {"success": False, "message": f"Weather API test failed: {str(e)}"}

    def _complete_setup(self):
        """Complete the setup process."""
        try:
            # Mark setup as completed
            self.config.complete_setup()

            return {
                "result": "success",
                "message": "Installation wizard completed successfully",
                "setup_completed": True,
            }

        except Exception as e:
            self.logger.error(f"Error completing setup: {e}")
            return {"result": "error", "message": str(e)}

    def _reset_setup(self):
        """Reset setup status (for testing or re-setup)."""
        try:
            # Reset setup status
            self.config.reset_setup()

            return {
                "result": "success",
                "message": "Setup status reset successfully",
                "setup_completed": False,
            }

        except Exception as e:
            self.logger.error(f"Error resetting setup: {e}")
            return {"result": "error", "message": str(e)}

    def _get_current_config(self):
        """Get current system configuration for reconfiguration mode."""
        try:
            from ethoscope_node.utils.etho_db import ExperimentalDB

            config_data = {
                "folders": {},
                "admin_user": None,
                "users": [],
                "incubators": [],
                "tunnel": {
                    "enabled": False,
                    "mode": "custom",
                    "token": "",  # Will be populated with masked value if configured
                    "node_id": "auto",
                    "domain": "ethoscope.net",
                    "custom_domain": "",
                },
                "authentication": {"enabled": False},
                "notifications": {
                    "smtp": {
                        "enabled": False,
                        "host": "localhost",
                        "port": 587,
                        "use_tls": True,
                        "username": "",
                        "password": "",
                        "from_email": "ethoscope@localhost",
                    },
                    "mattermost": {
                        "enabled": False,
                        "server_url": "",
                        "bot_token": "",
                        "channel_id": "",
                    },
                    "slack": {
                        "enabled": False,
                        "webhook_url": "",
                        "channel": "",
                        "use_webhook": True,
                        "use_manual_setup": False,
                    },
                },
                "virtual_sensor": {
                    "enabled": False,
                    "sensor_name": "virtual-sensor",
                    "location": "Lab",
                    "weather_location": "",
                    "api_key": "",
                },
            }

            # Get current folder configuration
            if hasattr(self.config, "_settings") and "folders" in self.config._settings:
                folders_config = self.config._settings["folders"]
                for folder_name, folder_info in folders_config.items():
                    if isinstance(folder_info, dict) and "path" in folder_info:
                        config_data["folders"][folder_name] = folder_info["path"]

            # Get admin user information
            try:
                db = ExperimentalDB()
                all_users = db.getAllUsers(active_only=False, asdict=True)
                for username, user_info in all_users.items():
                    if user_info.get("isadmin") == 1:
                        config_data["admin_user"] = {
                            "username": username,
                            "fullname": user_info.get("fullname", ""),
                            "email": user_info.get("email", ""),
                            "pin": user_info.get("pin", ""),
                            "telephone": user_info.get("telephone", ""),
                            "labname": user_info.get("labname", ""),
                        }
                        break  # Use first admin user found
            except Exception as e:
                self.logger.warning(f"Could not load admin user info: {e}")

            # Get tunnel settings
            try:
                tunnel_config = self.config._settings.get("tunnel", {})
                if tunnel_config:
                    # Show masked token if one exists, empty if none configured
                    existing_token = tunnel_config.get("token", "")
                    masked_token = "***CONFIGURED***" if existing_token else ""

                    config_data["tunnel"].update(
                        {
                            "enabled": tunnel_config.get("enabled", False),
                            "mode": tunnel_config.get("mode", "custom"),
                            "token": masked_token,  # Show masked token for UX, empty if none exists
                            "node_id": tunnel_config.get("node_id", "auto"),
                            "domain": tunnel_config.get("domain", "ethoscope.net"),
                            "custom_domain": tunnel_config.get("custom_domain", ""),
                        }
                    )
            except Exception as e:
                self.logger.warning(f"Could not load tunnel settings: {e}")

            # Get authentication settings
            try:
                auth_config = self.config._settings.get("authentication", {})
                if auth_config:
                    config_data["authentication"].update(
                        {"enabled": auth_config.get("enabled", False)}
                    )
            except Exception as e:
                self.logger.warning(f"Could not load authentication settings: {e}")

            # Get notification settings (from correct configuration paths)
            try:
                # SMTP settings - stored directly under 'smtp' key
                smtp_config = self.config._settings.get("smtp", {})
                if smtp_config:
                    # Show masked password if one exists, empty if none configured
                    existing_password = smtp_config.get("password", "")
                    masked_password = "***CONFIGURED***" if existing_password else ""

                    config_data["notifications"]["smtp"].update(
                        {
                            "enabled": smtp_config.get("enabled", False),
                            "host": smtp_config.get("host", "localhost"),
                            "port": smtp_config.get("port", 587),
                            "use_tls": smtp_config.get("use_tls", True),
                            "username": smtp_config.get("username", ""),
                            "password": masked_password,  # Show masked password for UX, empty if none exists
                            "from_email": smtp_config.get(
                                "from_email", "ethoscope@localhost"
                            ),
                        }
                    )

                # Mattermost settings - stored directly under 'mattermost' key
                mattermost_config = self.config._settings.get("mattermost", {})
                if mattermost_config:
                    # Show masked token if one exists, empty if none configured
                    existing_token = mattermost_config.get("bot_token", "")
                    masked_token = "***CONFIGURED***" if existing_token else ""

                    config_data["notifications"]["mattermost"].update(
                        {
                            "enabled": mattermost_config.get("enabled", False),
                            "server_url": mattermost_config.get("server_url", ""),
                            "bot_token": masked_token,  # Show masked token for UX, empty if none exists
                            "channel_id": mattermost_config.get("channel_id", ""),
                        }
                    )

                # Slack settings - stored directly under 'slack' key
                slack_config = self.config._settings.get("slack", {})
                if slack_config:
                    # Show masked webhook URL if one exists, empty if none configured
                    existing_webhook_url = slack_config.get("webhook_url", "")
                    masked_webhook_url = (
                        "***CONFIGURED***" if existing_webhook_url else ""
                    )

                    config_data["notifications"]["slack"].update(
                        {
                            "enabled": slack_config.get("enabled", False),
                            "webhook_url": masked_webhook_url,  # Show masked webhook URL for UX, empty if none exists
                            "channel": slack_config.get("channel", ""),
                            "use_webhook": slack_config.get("use_webhook", True),
                            "use_manual_setup": slack_config.get(
                                "use_manual_setup", False
                            ),
                        }
                    )
            except Exception as e:
                self.logger.warning(f"Could not load notification settings: {e}")

            # Get virtual sensor settings
            try:
                virtual_sensor_config = self.config._settings.get("virtual_sensor", {})
                if virtual_sensor_config:
                    # Show masked API key if one exists, empty if none configured
                    existing_api_key = virtual_sensor_config.get("api_key", "")
                    masked_api_key = "***CONFIGURED***" if existing_api_key else ""

                    config_data["virtual_sensor"].update(
                        {
                            "enabled": virtual_sensor_config.get("enabled", False),
                            "sensor_name": virtual_sensor_config.get(
                                "sensor_name", "virtual-sensor"
                            ),
                            "location": virtual_sensor_config.get("location", "Lab"),
                            "weather_location": virtual_sensor_config.get(
                                "weather_location", ""
                            ),
                            "api_key": masked_api_key,  # Show masked API key for UX, empty if none exists
                        }
                    )
            except Exception as e:
                self.logger.warning(f"Could not load virtual sensor settings: {e}")

            # Get existing users (excluding admin user already loaded)
            try:
                db = ExperimentalDB()
                all_users = db.getAllUsers(active_only=False, asdict=True)
                for username, user_info in all_users.items():
                    # Skip the admin user as it's already loaded separately
                    if user_info.get("isadmin") != 1:
                        config_data["users"].append(
                            {
                                "username": username,
                                "fullname": user_info.get("fullname", ""),
                                "email": user_info.get("email", ""),
                                "pin": user_info.get("pin", ""),
                                "telephone": user_info.get("telephone", ""),
                                "labname": user_info.get("labname", ""),
                                "isadmin": bool(user_info.get("isadmin", 0)),
                            }
                        )
            except Exception as e:
                self.logger.warning(f"Could not load existing users: {e}")

            # Get existing incubators
            try:
                db = ExperimentalDB()
                all_incubators = db.getAllIncubators(asdict=True)
                if isinstance(all_incubators, dict):
                    # When asdict=True, it returns a dictionary keyed by name
                    for incubator_name, incubator_data in all_incubators.items():
                        config_data["incubators"].append(
                            {
                                "name": incubator_data.get("name", incubator_name),
                                "description": incubator_data.get("description", ""),
                                "location": incubator_data.get("location", ""),
                                "owner": incubator_data.get("owner", ""),
                                "active": incubator_data.get("active", True),
                            }
                        )
                elif isinstance(all_incubators, list):
                    # When asdict=False, it returns a list of tuples/objects
                    for incubator in all_incubators:
                        config_data["incubators"].append(
                            {
                                "name": incubator.get("name", ""),
                                "description": incubator.get("description", ""),
                                "location": incubator.get("location", ""),
                                "owner": incubator.get("owner", ""),
                                "active": incubator.get("active", True),
                            }
                        )
            except Exception as e:
                self.logger.warning(f"Could not load existing incubators: {e}")

            return {"result": "success", "config": config_data}

        except Exception as e:
            self.logger.error(f"Error loading current configuration: {e}")
            return {"result": "error", "message": str(e)}
