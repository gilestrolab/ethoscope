import datetime
import json
import logging
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

# Configuration validation constants
USERS_KEYS = [
    "name",
    "fullname",
    "PIN",
    "email",
    "telephone",
    "group",
    "active",
    "isAdmin",
    "created",
]
INCUBATORS_KEYS = ["id", "name", "location", "owner", "description"]

# Module-level default configuration file path
_default_config_file = "/etc/ethoscope/ethoscope.conf"


def set_default_config_file(path: str) -> None:
    """
    Set the default configuration file path for all new EthoscopeConfiguration instances.

    This should be called early in application startup (e.g., in server.py __init__)
    to ensure all subsequent EthoscopeConfiguration instantiations use the correct path.

    Args:
        path: Path to configuration file
    """
    global _default_config_file
    _default_config_file = path


class ConfigurationError(Exception):
    """Custom exception for configuration-related errors."""

    pass


class ConfigurationValidationError(ConfigurationError):
    """Exception for configuration validation errors."""

    pass


def migrate_conf_file(file_path: str, destination: str = "/etc/ethoscope") -> bool:
    """
    Migrate configuration file to new location.

    Args:
        file_path: Source file path
        destination: Destination directory

    Returns:
        bool: True if migration was performed, False if no action needed

    Raises:
        ConfigurationError: If migration fails
    """
    try:
        if not os.path.isfile(file_path):
            return False

        logging.info(f"Migrating configuration file from {file_path}")

        # Ensure destination directory exists
        destination_path = Path(destination)
        destination_path.mkdir(parents=True, exist_ok=True)

        # Construct new file path
        new_file_path = destination_path / Path(file_path).name

        # Move the file
        shutil.move(file_path, str(new_file_path))
        logging.info(f"Configuration file migrated to {new_file_path}")

        return True

    except Exception as e:
        raise ConfigurationError(f"Failed to migrate configuration file: {e}")


class EthoscopeConfiguration:
    """
    Handles ethoscope configuration parameters with improved error handling and validation.

    Data are stored in and retrieved from a JSON configuration file with automatic
    migration support and comprehensive validation.
    """

    DEFAULT_SETTINGS = {
        "folders": {
            "results": {
                "path": "/ethoscope_data/results",
                "description": "Where tracking data will be saved by the backup daemon.",
            },
            "video": {
                "path": "/ethoscope_data/videos",
                "description": "Where video chunks (h264) will be saved by the backup daemon",
            },
            "temporary": {
                "path": "/tmp/ethoscope",
                "description": "A temporary location for downloading data.",
            },
        },
        "incubators": {
            "incubator 1": {
                "id": 1,
                "name": "Incubator 1",
                "location": "",
                "owner": "",
                "description": "",
            }
        },
        "sensors": {},
        "commands": {
            "command_1": {
                "name": "List ethoscope files.",
                "description": "Show ethoscope data folders on the node. Just an example of how to write a command",
                "command": "ls -lh /ethoscope_data/results",
            }
        },
        "custom": {"UPDATE_SERVICE_URL": "http://localhost:8888"},
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
            "bot_token": "",
            "channel": "",
            "use_webhook": True,
        },
        "alerts": {
            "enabled": True,
            "cooldown_seconds": 3600,
            "storage_warning_threshold": 80,
            "device_timeout_minutes": 30,
            "unreachable_timeout_minutes": 20,
            "graceful_shutdown_grace_minutes": 5,
            "user_action_timeout_seconds": 30,
        },
        "setup": {
            "completed": False,
            "steps_completed": [],
            "setup_started": None,
            "setup_completed": None,
            "setup_version": "1.0",
        },
        "authentication": {
            "enabled": False  # Global authentication setting, independent of tunnel
        },
        "tunnel": {
            "enabled": False,
            "provider": "cloudflare",
            "mode": "custom",  # 'custom' (free) or 'ethoscope_net' (paid)
            "token": "",
            "node_id": "auto",
            "domain": "ethoscope.net",
            "custom_domain": "",  # For custom domain mode
            "status": "disconnected",
            "last_connected": None,
            "container_name": "ethoscope-cloudflare-tunnel"
            # authentication_enabled removed from tunnel section
        },
    }

    REQUIRED_SECTIONS = [
        "folders",
        "incubators",
        "sensors",
        "commands",
        "custom",
        "smtp",
        "mattermost",
        "slack",
        "alerts",
        "setup",
        "authentication",
        "tunnel",
    ]
    REQUIRED_FOLDERS = ["results", "video", "temporary"]

    def __init__(self, config_file: str = None):
        """
        Initialize configuration manager.

        Args:
            config_file: Path to configuration file (defaults to module-level setting)
        """
        self._config_file = Path(config_file or _default_config_file)
        self._settings = {}
        self._logger = logging.getLogger(self.__class__.__name__)

        # Perform migration if needed
        self._migrate_legacy_files()

        # Load configuration
        self.load()

    def _migrate_legacy_files(self):
        """Migrate legacy configuration files to new location."""
        legacy_paths = [
            "/etc/ethoscope.conf",
            "/etc/node.conf",  # Add other legacy paths as needed
        ]

        for legacy_path in legacy_paths:
            try:
                migrate_conf_file(legacy_path, str(self._config_file.parent))
            except ConfigurationError as e:
                self._logger.warning(f"Migration warning: {e}")

    def _validate_configuration(self, config_data: Dict[str, Any]) -> None:
        """
        Validate configuration data structure.

        Args:
            config_data: Configuration data to validate

        Raises:
            ConfigurationValidationError: If validation fails
        """
        # Check required sections
        missing_sections = set(self.REQUIRED_SECTIONS) - set(config_data.keys())
        if missing_sections:
            raise ConfigurationValidationError(
                f"Missing required sections: {missing_sections}"
            )

        # Validate folders section
        folders = config_data.get("folders", {})
        missing_folders = set(self.REQUIRED_FOLDERS) - set(folders.keys())
        if missing_folders:
            raise ConfigurationValidationError(
                f"Missing required folders: {missing_folders}"
            )

        # Validate folder structure
        for folder_name, folder_config in folders.items():
            if not isinstance(folder_config, dict):
                raise ConfigurationValidationError(
                    f"Folder '{folder_name}' must be a dictionary"
                )

            if "path" not in folder_config:
                raise ConfigurationValidationError(
                    f"Folder '{folder_name}' missing 'path' field"
                )

            if not isinstance(folder_config["path"], str):
                raise ConfigurationValidationError(
                    f"Folder '{folder_name}' path must be a string"
                )

        # Users are now stored in database, no validation needed for config file

    def _merge_with_defaults(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge loaded configuration with defaults.

        Args:
            config_data: Loaded configuration data

        Returns:
            Merged configuration data
        """
        import copy

        merged = copy.deepcopy(self.DEFAULT_SETTINGS)

        def deep_merge(target: Dict, source: Dict) -> Dict:
            """Recursively merge dictionaries."""
            for key, value in source.items():
                if (
                    key in target
                    and isinstance(target[key], dict)
                    and isinstance(value, dict)
                ):
                    deep_merge(target[key], value)
                else:
                    target[key] = value
            return target

        # Handle backward compatibility: migrate authentication_enabled from tunnel to authentication section
        if (
            "tunnel" in config_data
            and "authentication_enabled" in config_data["tunnel"]
        ):
            # Move authentication_enabled from tunnel to authentication section
            if "authentication" not in config_data:
                config_data["authentication"] = {}
            config_data["authentication"]["enabled"] = config_data["tunnel"][
                "authentication_enabled"
            ]
            # Remove from tunnel section
            del config_data["tunnel"]["authentication_enabled"]
            self._logger.info(
                "Migrated authentication_enabled from tunnel section to authentication section"
            )

        # Merge configuration with defaults (users are handled by database)
        merged = deep_merge(merged, config_data)

        return merged

    @property
    def content(self) -> Dict[str, Any]:
        """Get configuration content."""
        return self._settings

    @property
    def file_exists(self) -> bool:
        """Check if configuration file exists."""
        return self._config_file.exists()

    def save(self) -> None:
        """
        Save settings to configuration file.

        Raises:
            ConfigurationError: If saving fails
        """
        try:
            # Ensure directory exists
            self._config_file.parent.mkdir(parents=True, exist_ok=True)

            # Write configuration file
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(
                    self._settings, f, indent=4, sort_keys=True, ensure_ascii=False
                )

            self._logger.info(f"Saved ethoscope configuration to {self._config_file}")

        except Exception as e:
            raise ConfigurationError(
                f"Failed to write configuration file {self._config_file}: {e}"
            )

    def load(self) -> Dict[str, Any]:
        """
        Load configuration from file.

        Returns:
            Configuration settings

        Raises:
            ConfigurationError: If loading or validation fails
        """
        # If file doesn't exist, save defaults
        if not self.file_exists:
            self._logger.info("Configuration file not found, creating with defaults")
            self._settings = self.DEFAULT_SETTINGS.copy()
            self.save()
            return self._settings

        try:
            # Load configuration file
            with open(self._config_file, encoding="utf-8") as f:
                content = f.read().strip()

                if not content:
                    raise ValueError("Configuration file is empty")

                try:
                    loaded_config = json.loads(content)
                except json.JSONDecodeError as e:
                    raise ConfigurationError(f"Invalid JSON in configuration file: {e}")

            # Merge with defaults first to ensure all sections are present
            self._settings = self._merge_with_defaults(loaded_config)

            # Validate the merged configuration
            self._validate_configuration(self._settings)

            # Save merged configuration back to file
            self.save()

            self._logger.info(
                f"Configuration loaded successfully from {self._config_file}"
            )
            return self._settings

        except Exception as e:
            if isinstance(e, (ConfigurationError, ConfigurationValidationError)):
                raise
            else:
                raise ConfigurationError(
                    f"Failed to load configuration file {self._config_file}: {e}"
                )

    def add_section(self, section: str) -> None:
        """
        Add a new section to configuration.

        Args:
            section: Section name

        Raises:
            ValueError: If section already exists
        """
        if section in self._settings:
            raise ValueError(f"Section '{section}' already exists")

        self._settings[section] = {}
        self._logger.info(f"Added new section: {section}")

    def list_sections(self) -> List[str]:
        """Get list of configuration sections."""
        return list(self._settings.keys())

    def list_subsection(self, section: str) -> List[str]:
        """
        Get list of subsection keys.

        Args:
            section: Section name

        Returns:
            List of subsection keys
        """
        if section not in self._settings:
            return []
        return list(self._settings[section].keys())

    def add_key(self, section: str, obj: Dict[str, Any]) -> None:
        """
        Add key-value pairs to a section.

        Args:
            section: Section name
            obj: Dictionary to merge into section
        """
        if section not in self._settings:
            self.add_section(section)

        self._settings[section].update(obj)
        self._logger.info(
            f"Updated section '{section}' with new keys: {list(obj.keys())}"
        )

    def add_user(self, userdata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new user using database storage.

        Args:
            userdata: User data dictionary

        Returns:
            Result dictionary with success/failure status

        Raises:
            ValueError: If user data is invalid
        """
        if "name" not in userdata:
            raise ValueError("User data must include 'name' field")

        name = userdata["name"]

        try:
            # Import here to avoid circular imports
            from ethoscope_node.utils.etho_db import ExperimentalDB

            # Validate user data
            for key in USERS_KEYS:
                if key not in userdata and key not in ["created"]:
                    self._logger.warning(f"User '{name}' missing field: {key}")

            # Map configuration fields to database fields
            db_user_data = {
                "username": userdata["name"],
                "fullname": userdata.get("fullname", ""),
                "pin": str(userdata.get("PIN", "")),
                "email": userdata.get("email", ""),
                "telephone": userdata.get("telephone", ""),
                "labname": userdata.get("group", ""),
                "active": 1 if userdata.get("active", True) else 0,
                "isadmin": 1 if userdata.get("isAdmin", False) else 0,
                "created": userdata.get("created", datetime.datetime.now().timestamp()),
            }

            # Add user to database
            db = ExperimentalDB()
            result = db.addUser(**db_user_data)

            if result > 0:
                self._logger.info(f"Added user to database: {name}")
                # Get all users from database to return consistent format
                all_users = db.getAllUsers(asdict=True)
                return {"result": "success", "data": all_users}
            else:
                error_msg = f"Failed to add user '{name}' to database"
                self._logger.error(error_msg)
                raise ValueError(error_msg)

        except Exception as e:
            error_msg = f"Failed to add user '{name}': {e}"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

    def add_incubator(self, incubatordata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new incubator using database storage.

        Args:
            incubatordata: Incubator data dictionary

        Returns:
            Result dictionary with success/failure status

        Raises:
            ValueError: If incubator data is invalid
        """
        if "name" not in incubatordata:
            raise ValueError("Incubator data must include 'name' field")

        name = incubatordata["name"]

        try:
            # Import here to avoid circular imports
            from ethoscope_node.utils.etho_db import ExperimentalDB

            # Validate incubator data
            for key in INCUBATORS_KEYS:
                if key not in incubatordata and key not in ["id"]:
                    self._logger.warning(f"Incubator '{name}' missing field: {key}")

            # Map configuration fields to database fields
            db_incubator_data = {
                "name": incubatordata["name"],
                "location": incubatordata.get("location", ""),
                "owner": incubatordata.get("owner", ""),
                "description": incubatordata.get("description", ""),
                "active": 1,
            }

            # Add incubator to database
            db = ExperimentalDB()
            result = db.addIncubator(**db_incubator_data)

            if result > 0:
                self._logger.info(f"Added incubator to database: {name}")
                # Get all incubators from database to return consistent format
                all_incubators = db.getAllIncubators(asdict=True)
                return {"result": "success", "data": all_incubators}
            else:
                error_msg = f"Failed to add incubator '{name}' to database"
                self._logger.error(error_msg)
                raise ValueError(error_msg)

        except Exception as e:
            error_msg = f"Failed to add incubator '{name}': {e}"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

    def add_sensor(self, sensordata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new sensor to configuration.

        Args:
            sensordata: Sensor data dictionary

        Returns:
            Result dictionary with success/failure status

        Raises:
            ValueError: If sensor data is invalid
        """
        if "name" not in sensordata:
            raise ValueError("Sensor data must include 'name' field")

        name = sensordata["name"]

        try:
            # Add sensor
            if "sensors" not in self._settings:
                self._settings["sensors"] = {}

            self._settings["sensors"][name] = sensordata
            self.save()

            self._logger.info(f"Added sensor: {name}")
            return {"result": "success", "data": self._settings["sensors"]}

        except Exception as e:
            error_msg = f"Failed to add sensor '{name}': {e}"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

    def get_custom(self, name: Optional[str] = None) -> Any:
        """
        Get custom configuration value(s).

        Args:
            name: Specific custom variable name, or None for all

        Returns:
            Custom configuration value or entire custom section
        """
        custom_section = self._settings.get("custom", {})

        if name is None:
            return custom_section
        else:
            return custom_section.get(name)

    # Keep legacy method name for compatibility
    def custom(self, name: Optional[str] = None) -> Any:
        """Legacy method name for get_custom."""
        return self.get_custom(name)

    def update_custom(self, name: str, value: Any) -> None:
        """
        Update a custom configuration value.

        Args:
            name: Custom variable name
            value: New value
        """
        if "custom" not in self._settings:
            self._settings["custom"] = {}

        self._settings["custom"][name] = value
        self.save()
        self._logger.info(f"Updated custom setting '{name}'")

    def remove_user(self, username: str) -> bool:
        """
        Deactivate a user in the database (users are never actually deleted).

        Args:
            username: Name of user to deactivate

        Returns:
            True if user was deactivated, False if not found
        """
        try:
            # Import here to avoid circular imports
            from ethoscope_node.utils.etho_db import ExperimentalDB

            # Deactivate user in database
            db = ExperimentalDB()
            result = db.deactivateUser(username=username)

            if result > 0:
                self._logger.info(f"Deactivated user: {username}")
                return True
            else:
                self._logger.warning(f"User '{username}' not found for deactivation")
                return False

        except Exception as e:
            self._logger.error(f"Error deactivating user '{username}': {e}")
            return False

    def get_folder_path(self, folder_name: str) -> Optional[str]:
        """
        Get path for a specific folder.

        Args:
            folder_name: Name of folder (e.g., 'results', 'video')

        Returns:
            Folder path or None if not found
        """
        folders = self._settings.get("folders", {})
        folder_config = folders.get(folder_name, {})
        return folder_config.get("path")

    def reload(self) -> Dict[str, Any]:
        """
        Reload configuration from file.

        Returns:
            Reloaded configuration settings
        """
        self._logger.info("Reloading configuration from file")
        return self.load()

    def is_setup_completed(self) -> bool:
        """
        Check if first-time setup has been completed.

        Returns:
            True if setup is completed, False otherwise
        """
        setup_section = self._settings.get("setup", {})
        return setup_section.get("completed", False)

    def is_setup_required(self) -> bool:
        """
        Determine if setup is required based on various conditions.

        Returns:
            True if setup is required, False otherwise
        """
        if self.is_setup_completed():
            return False

        # Check if we have admin users in the database
        try:
            from ethoscope_node.utils.etho_db import ExperimentalDB

            db = ExperimentalDB()

            # Get admin users from database
            all_users = db.getAllUsers(active_only=True, asdict=True)
            admin_users = [
                user for user in all_users.values() if user.get("isadmin", 0) == 1
            ]

            # If no admin users exist, setup is required
            if not admin_users:
                return True

            # Check for default/test admin users that should be replaced
            default_usernames = ["admin", "test", "default", "ethoscope"]
            default_emails = ["admin@localhost", "test@localhost", "admin@example.com"]

            for admin in admin_users:
                username = admin.get("username", "").lower()
                email = admin.get("email", "").lower()

                # If any admin has default credentials, setup is required
                if username in default_usernames or email in default_emails:
                    return True

            return False

        except Exception as e:
            self._logger.warning(f"Error checking setup requirements: {e}")
            # If we can't determine, assume setup is required
            return True

    def get_setup_status(self) -> Dict[str, Any]:
        """
        Get detailed setup status information.

        Returns:
            Dictionary with setup status details
        """
        setup_section = self._settings.get("setup", {})

        status = {
            "completed": self.is_setup_completed(),
            "required": self.is_setup_required(),
            "steps_completed": setup_section.get("steps_completed", []),
            "setup_started": setup_section.get("setup_started"),
            "setup_completed": setup_section.get("setup_completed"),
            "setup_version": setup_section.get("setup_version", "1.0"),
        }

        # Add system information
        try:
            from ethoscope_node.utils.etho_db import ExperimentalDB

            db = ExperimentalDB()

            user_count = len(db.getAllUsers(active_only=True))
            admin_count = len(
                [
                    u
                    for u in db.getAllUsers(active_only=True, asdict=True).values()
                    if u.get("isadmin", 0) == 1
                ]
            )
            incubator_count = len(db.getAllIncubators(active_only=True))

            status["system_info"] = {
                "users": user_count,
                "admin_users": admin_count,
                "incubators": incubator_count,
                "smtp_configured": self._settings.get("smtp", {}).get("enabled", False),
                "mattermost_configured": self._settings.get("mattermost", {}).get(
                    "enabled", False
                ),
                "slack_configured": self._settings.get("slack", {}).get(
                    "enabled", False
                ),
            }

        except Exception as e:
            self._logger.warning(f"Error getting system info for setup status: {e}")
            status["system_info"] = {}

        return status

    def mark_setup_step_completed(self, step: str) -> None:
        """
        Mark a setup step as completed.

        Args:
            step: Name of the completed step
        """
        if "setup" not in self._settings:
            self._settings["setup"] = self.DEFAULT_SETTINGS["setup"].copy()

        steps_completed = self._settings["setup"].get("steps_completed", [])
        if step not in steps_completed:
            steps_completed.append(step)
            self._settings["setup"]["steps_completed"] = steps_completed

        # Mark setup as started if this is the first step
        if not self._settings["setup"].get("setup_started"):
            self._settings["setup"][
                "setup_started"
            ] = datetime.datetime.now().isoformat()

        self.save()
        self._logger.info(f"Setup step completed: {step}")

    def complete_setup(self) -> None:
        """
        Mark the entire setup process as completed.
        """
        if "setup" not in self._settings:
            self._settings["setup"] = self.DEFAULT_SETTINGS["setup"].copy()

        self._settings["setup"]["completed"] = True
        self._settings["setup"]["setup_completed"] = datetime.datetime.now().isoformat()

        self.save()
        self._logger.info("Setup process marked as completed")

    def reset_setup(self) -> None:
        """
        Reset setup status (for testing or re-setup).
        """
        self._settings["setup"] = self.DEFAULT_SETTINGS["setup"].copy()
        self.save()
        self._logger.info("Setup status reset")

    def get_tunnel_node_id(self) -> str:
        """
        Get the tunnel node ID, generating it if set to 'auto'.

        Returns:
            Node ID string for tunnel subdomain
        """
        tunnel_config = self._settings.get("tunnel", {})
        node_id = tunnel_config.get("node_id", "auto")

        if node_id == "auto":
            # Generate node ID as node-<admin_username>
            try:
                from ethoscope_node.utils.etho_db import ExperimentalDB

                db = ExperimentalDB()
                admin_users = db.getAllUsers(active_only=True, asdict=True)

                # Find first admin user
                admin_username = None
                for user_data in admin_users.values():
                    if user_data.get("isAdmin", False):
                        admin_username = user_data.get("name", "")
                        break

                if admin_username:
                    return f"node-{admin_username.lower()}"
                else:
                    # Fallback to hostname if no admin user found
                    import socket

                    hostname = socket.gethostname().lower()
                    return f"node-{hostname}"

            except Exception as e:
                self._logger.warning(f"Failed to get admin username for node ID: {e}")
                # Fallback to hostname
                import socket

                hostname = socket.gethostname().lower()
                return f"node-{hostname}"

        return node_id.lower()

    def update_tunnel_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update tunnel configuration.

        Args:
            config_data: Tunnel configuration data

        Returns:
            Updated tunnel configuration

        Raises:
            ValueError: If configuration data is invalid
        """
        if "tunnel" not in self._settings:
            self._settings["tunnel"] = self.DEFAULT_SETTINGS["tunnel"].copy()

        # Validate and update tunnel settings
        allowed_keys = [
            "enabled",
            "mode",
            "token",
            "node_id",
            "domain",
            "custom_domain",
            "status",
            "last_connected",
        ]

        for key, value in config_data.items():
            if key in allowed_keys:
                self._settings["tunnel"][key] = value
            else:
                self._logger.warning(f"Unknown tunnel configuration key: {key}")

        # Update last modified timestamp if status changed
        if "status" in config_data:
            self._settings["tunnel"][
                "last_connected"
            ] = datetime.datetime.now().isoformat()

        self.save()
        self._logger.info(f"Updated tunnel configuration: {list(config_data.keys())}")

        return self._settings["tunnel"]

    def get_tunnel_config(self) -> Dict[str, Any]:
        """
        Get current tunnel configuration with computed node ID and domain.

        Returns:
            Complete tunnel configuration dictionary
        """
        tunnel_config = self._settings.get(
            "tunnel", self.DEFAULT_SETTINGS["tunnel"]
        ).copy()

        # Add computed node ID
        tunnel_config["computed_node_id"] = self.get_tunnel_node_id()

        # Determine the full domain based on mode
        if tunnel_config.get("mode", "custom") == "ethoscope_net":
            # Paid mode: use ethoscope.net
            tunnel_config["effective_domain"] = "ethoscope.net"
            tunnel_config[
                "full_domain"
            ] = f"{tunnel_config['computed_node_id']}.ethoscope.net"
            tunnel_config["is_paid_mode"] = True
        else:
            # Free mode: use custom domain
            custom_domain = tunnel_config.get("custom_domain", "")
            tunnel_config["effective_domain"] = custom_domain
            tunnel_config["full_domain"] = (
                f"{tunnel_config['computed_node_id']}.{custom_domain}"
                if custom_domain
                else ""
            )
            tunnel_config["is_paid_mode"] = False

        return tunnel_config

    def update_authentication_config(
        self, config_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update authentication configuration.

        Args:
            config_data: Authentication configuration data

        Returns:
            Updated authentication configuration

        Raises:
            ValueError: If configuration data is invalid
        """
        if "authentication" not in self._settings:
            self._settings["authentication"] = self.DEFAULT_SETTINGS[
                "authentication"
            ].copy()

        # Validate and update authentication settings
        allowed_keys = ["enabled"]

        for key, value in config_data.items():
            if key in allowed_keys:
                self._settings["authentication"][key] = value
            else:
                self._logger.warning(f"Unknown authentication configuration key: {key}")

        self.save()
        self._logger.info(
            f"Updated authentication configuration: {list(config_data.keys())}"
        )

        return self._settings["authentication"]

    def get_authentication_config(self) -> Dict[str, Any]:
        """
        Get current authentication configuration.

        Returns:
            Authentication configuration dictionary
        """
        return self._settings.get(
            "authentication", self.DEFAULT_SETTINGS["authentication"]
        ).copy()

    def migrate_user_pins(self, dry_run: bool = False) -> int:
        """
        Migrate plaintext PINs to secure hashed format.

        Args:
            dry_run: If True, only report what would be migrated without making changes

        Returns:
            Number of PINs migrated

        Raises:
            ConfigurationError: If migration fails
        """
        try:
            from ethoscope_node.utils.etho_db import ExperimentalDB

            # Initialize database
            db = ExperimentalDB()

            # Get all users with PINs
            all_users = db.getAllUsers(active_only=False, asdict=True)

            if not all_users:
                self._logger.info("No users found in database")
                return 0

            plaintext_users = []

            for username, user_data in all_users.items():
                pin = user_data.get("pin", "")
                if pin:
                    # Check if PIN looks like plaintext (not bcrypt hash)
                    if not (pin.startswith("$2b$") or pin.startswith("$2a$")):
                        # Also check if it's not a simple hex hash
                        is_hex_hash = False
                        try:
                            int(pin, 16)
                            if len(pin) == 64:  # SHA256 hex length
                                is_hex_hash = True
                        except ValueError:
                            pass

                        if not is_hex_hash:
                            plaintext_users.append(username)

            self._logger.info(f"Found {len(plaintext_users)} users with plaintext PINs")

            if len(plaintext_users) == 0:
                self._logger.info(
                    "No plaintext PINs found - all PINs are already secure"
                )
                return 0

            if dry_run:
                self._logger.info("DRY RUN - Would migrate the following users:")
                for username in plaintext_users:
                    self._logger.info(f"  - {username}")
                return len(plaintext_users)

            # Perform migration
            self._logger.info("Starting PIN migration...")
            migrated_count = db.migrate_plaintext_pins()

            if migrated_count > 0:
                self._logger.info(
                    f"Successfully migrated {migrated_count} plaintext PINs to secure format"
                )

                # Mark this migration step as completed
                self.mark_setup_step_completed("pin_migration")
            else:
                self._logger.warning("No PINs were migrated - check logs for errors")

            return migrated_count

        except Exception as e:
            error_msg = f"PIN migration failed: {e}"
            self._logger.error(error_msg)
            raise ConfigurationError(error_msg)


def _setup_system_ssh_config(private_key_path: str) -> None:
    """
    Set up system-wide SSH configuration for ethoscope connections.

    Creates or updates /etc/ssh/ssh_config with ethoscope-specific settings
    that apply to all users on the system.

    Args:
        private_key_path: Path to the private key file
    """
    logger = logging.getLogger(__name__)
    ssh_config_path = "/etc/ssh/ssh_config"

    # Import here to avoid circular imports
    from .network import get_private_ip_pattern

    # Get the actual IP pattern for this network
    ip_pattern = get_private_ip_pattern()

    # Configuration block to add
    config_block = f"""
# Ethoscope SSH configuration
Host {ip_pattern} ethoscope*
     User ethoscope
     StrictHostKeyChecking no
     UserKnownHostsFile=/dev/null
     IdentityFile {private_key_path}
     ConnectTimeout 10
     ServerAliveInterval 30
     ServerAliveCountMax 3
"""

    try:
        # Check if configuration already exists
        if os.path.exists(ssh_config_path):
            with open(ssh_config_path) as f:
                content = f.read()

            # If ethoscope config already exists, skip
            if "# Ethoscope SSH configuration" in content:
                logger.info("System SSH config for ethoscopes already exists")
                return

            # Append to existing config
            with open(ssh_config_path, "a") as f:
                f.write(config_block)
            logger.info(f"Appended ethoscope SSH config to {ssh_config_path}")
        else:
            # Create new config file
            with open(ssh_config_path, "w") as f:
                f.write(config_block.lstrip())
            logger.info(f"Created new SSH config at {ssh_config_path}")

        # Set proper permissions (readable by all users)
        os.chmod(ssh_config_path, 0o644)
        logger.info(f"Set permissions on {ssh_config_path}")

    except PermissionError as e:
        logger.warning(f"Permission denied updating system SSH config: {e}")
        logger.info("System SSH config requires root privileges to modify")
    except Exception as e:
        logger.error(f"Failed to setup system SSH config: {e}")


def ensure_ssh_keys(keys_dir: str = "/etc/ethoscope/keys") -> Tuple[str, str]:
    """
    Ensure SSH keys exist for ethoscope node authentication.

    Creates RSA key pair if it doesn't exist, sets proper permissions,
    and returns paths to the private and public keys.

    Args:
        keys_dir: Directory to store SSH keys

    Returns:
        Tuple of (private_key_path, public_key_path)

    Raises:
        ConfigurationError: If key generation or setup fails
    """
    logger = logging.getLogger(__name__)

    try:
        # Ensure keys directory exists
        keys_path = Path(keys_dir)
        keys_path.mkdir(parents=True, exist_ok=True)

        # Set directory permissions to 700 (drwx------)
        os.chmod(keys_path, 0o700)
        logger.debug(f"Created/verified SSH keys directory: {keys_path}")

        # Define key file paths
        private_key_path = keys_path / "id_rsa"
        public_key_path = keys_path / "id_rsa.pub"

        # Check if keys already exist
        if private_key_path.exists() and public_key_path.exists():
            logger.info(f"SSH keys already exist at {keys_dir}")
            # Verify permissions
            os.chmod(private_key_path, 0o600)
            os.chmod(public_key_path, 0o644)
            return str(private_key_path), str(public_key_path)

        # Generate new SSH key pair
        logger.info(f"Generating new SSH key pair in {keys_dir}")

        # Get hostname for key comment
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "ethoscope-node"

        comment = f"ethoscope-node@{hostname}"

        # Run ssh-keygen command
        ssh_keygen_cmd = [
            "ssh-keygen",
            "-t",
            "rsa",  # RSA key type
            "-b",
            "2048",  # 2048-bit key
            "-f",
            str(private_key_path),  # Output file
            "-N",
            "",  # Empty passphrase
            "-C",
            comment,  # Comment
        ]

        result = subprocess.run(
            ssh_keygen_cmd, capture_output=True, text=True, check=True
        )

        logger.info(f"Successfully generated SSH keys: {comment}")
        logger.debug(f"ssh-keygen output: {result.stdout}")

        # Set proper permissions
        os.chmod(private_key_path, 0o600)  # -rw-------
        os.chmod(public_key_path, 0o644)  # -rw-r--r--

        logger.info("Set proper permissions on SSH keys")
        logger.info(f"Private key: {private_key_path} (600)")
        logger.info(f"Public key: {public_key_path} (644)")

        # Set up system-wide SSH configuration for ethoscopes
        _setup_system_ssh_config(str(private_key_path))

        return str(private_key_path), str(public_key_path)

    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to generate SSH keys: {e.stderr}"
        logger.error(error_msg)
        raise ConfigurationError(error_msg)

    except PermissionError as e:
        error_msg = f"Permission denied creating SSH keys in {keys_dir}: {e}"
        logger.error(error_msg)
        raise ConfigurationError(error_msg)

    except Exception as e:
        error_msg = f"Unexpected error ensuring SSH keys: {e}"
        logger.error(error_msg)
        raise ConfigurationError(error_msg)


def main():
    """Example usage and testing."""
    try:
        c = EthoscopeConfiguration()

        # Add some example commands
        c.add_key(
            "commands",
            {
                "sync_command": {
                    "name": "Sync all data to Turing",
                    "description": "Sync all the ethoscope data to turing",
                    "command": "/etc/cron.hourly/sync",
                }
            },
        )

        c.add_key(
            "commands",
            {
                "cleanup_command": {
                    "name": "Delete old files",
                    "description": "Delete ethoscope data older than 90 days",
                    "command": "find /ethoscope_data/results -type f -mtime +90 -exec rm {} \\;",
                }
            },
        )

        print("Configuration sections:", c.list_sections())
        print("Commands:", c.content["commands"])

        c.save()
        print("Configuration saved successfully")

    except Exception as e:
        logging.error(f"Configuration test failed: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
