"""
Unit tests for ethoscope_node.utils.configuration module.

Tests cover:
- Configuration file loading and parsing
- Settings validation
- Default value handling
- Error handling for invalid configurations
- File I/O operations
- Migration functionality
- User/incubator/sensor management
- Setup workflow
- Tunnel configuration
- SSH key management
"""

import datetime
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from ethoscope_node.utils.configuration import (
    INCUBATORS_KEYS,
    USERS_KEYS,
    ConfigurationError,
    ConfigurationValidationError,
    EthoscopeConfiguration,
    ensure_ssh_keys,
    migrate_conf_file,
    set_default_config_file,
)


class TestConfigurationConstants:
    """Test configuration constants and module-level functions."""

    def test_users_keys_defined(self):
        """Test that USERS_KEYS constant is properly defined."""
        assert isinstance(USERS_KEYS, list)
        assert "name" in USERS_KEYS
        assert "email" in USERS_KEYS
        assert "PIN" in USERS_KEYS
        assert "isAdmin" in USERS_KEYS

    def test_incubators_keys_defined(self):
        """Test that INCUBATORS_KEYS constant is properly defined."""
        assert isinstance(INCUBATORS_KEYS, list)
        assert "id" in INCUBATORS_KEYS
        assert "name" in INCUBATORS_KEYS
        assert "location" in INCUBATORS_KEYS

    def test_set_default_config_file(self):
        """Test setting the default configuration file path."""
        original_path = "/etc/ethoscope/ethoscope.conf"
        test_path = "/tmp/test-config.conf"

        set_default_config_file(test_path)

        # Import the module variable to check it was set
        from ethoscope_node.utils import configuration

        assert configuration._default_config_file == test_path

        # Reset to original
        set_default_config_file(original_path)


class TestConfigurationExceptions:
    """Test custom configuration exceptions."""

    def test_configuration_error_inheritance(self):
        """Test that ConfigurationError inherits from Exception."""
        error = ConfigurationError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"

    def test_configuration_validation_error_inheritance(self):
        """Test that ConfigurationValidationError inherits from ConfigurationError."""
        error = ConfigurationValidationError("Validation failed")
        assert isinstance(error, ConfigurationError)
        assert isinstance(error, Exception)
        assert str(error) == "Validation failed"


class TestMigrateConfFile:
    """Test configuration file migration functionality."""

    def test_migrate_nonexistent_file(self):
        """Test migration returns False for nonexistent file."""
        result = migrate_conf_file("/nonexistent/file.conf", "/tmp")
        assert result is False

    def test_migrate_file_success(self):
        """Test successful file migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            source_file = source_dir / "test.conf"
            source_file.write_text('{"test": "data"}')

            # Migrate to destination
            dest_dir = Path(tmpdir) / "dest"
            result = migrate_conf_file(str(source_file), str(dest_dir))

            assert result is True
            assert not source_file.exists()
            assert (dest_dir / "test.conf").exists()
            assert (dest_dir / "test.conf").read_text() == '{"test": "data"}'

    def test_migrate_file_creates_destination_directory(self):
        """Test that migration creates destination directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_file = Path(tmpdir) / "test.conf"
            source_file.write_text('{"test": "data"}')

            dest_dir = Path(tmpdir) / "new" / "nested" / "dir"
            result = migrate_conf_file(str(source_file), str(dest_dir))

            assert result is True
            assert dest_dir.exists()
            assert (dest_dir / "test.conf").exists()

    def test_migrate_file_error_handling(self):
        """Test migration error handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_file = Path(tmpdir) / "test.conf"
            source_file.write_text('{"test": "data"}')

            # Try to migrate to invalid destination
            with patch("shutil.move", side_effect=PermissionError("Access denied")):
                with pytest.raises(ConfigurationError) as exc_info:
                    migrate_conf_file(str(source_file), "/invalid/path")

                assert "Failed to migrate configuration file" in str(exc_info.value)


class TestEthoscopeConfigurationInit:
    """Test EthoscopeConfiguration initialization."""

    def test_init_creates_default_config_if_missing(self):
        """Test initialization creates default config if file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration(str(config_file))

            assert config.file_exists
            assert config._settings == EthoscopeConfiguration.DEFAULT_SETTINGS

    def test_init_with_custom_path(self):
        """Test initialization with custom config path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "custom.conf"

            config = EthoscopeConfiguration(str(config_file))

            assert config._config_file == config_file

    def test_init_uses_default_path_if_none_provided(self):
        """Test initialization uses module default if no path provided."""
        with patch(
            "ethoscope_node.utils.configuration._default_config_file",
            "/tmp/default.conf",
        ):
            with patch.object(EthoscopeConfiguration, "_migrate_legacy_files"):
                with patch.object(EthoscopeConfiguration, "load"):
                    config = EthoscopeConfiguration()
                    assert str(config._config_file) == "/tmp/default.conf"

    def test_init_performs_migration(self):
        """Test that initialization attempts legacy file migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            with patch.object(
                EthoscopeConfiguration, "_migrate_legacy_files"
            ) as mock_migrate:
                EthoscopeConfiguration(str(config_file))
                mock_migrate.assert_called_once()


class TestEthoscopeConfigurationValidation:
    """Test configuration validation functionality."""

    def test_validate_missing_required_sections(self):
        """Test validation fails for missing required sections."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        incomplete_config = {"folders": {}}

        with pytest.raises(ConfigurationValidationError) as exc_info:
            config._validate_configuration(incomplete_config)

        assert "Missing required sections" in str(exc_info.value)

    def test_validate_missing_required_folders(self):
        """Test validation fails for missing required folders."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        # All required sections but missing folders
        incomplete_config = {
            section: {} for section in EthoscopeConfiguration.REQUIRED_SECTIONS
        }
        incomplete_config["folders"] = {"results": {"path": "/tmp"}}

        with pytest.raises(ConfigurationValidationError) as exc_info:
            config._validate_configuration(incomplete_config)

        assert "Missing required folders" in str(exc_info.value)

    def test_validate_folder_not_dict(self):
        """Test validation fails if folder is not a dictionary."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        invalid_config = {
            section: {} for section in EthoscopeConfiguration.REQUIRED_SECTIONS
        }
        invalid_config["folders"] = {
            "results": "not a dict",
            "video": {"path": "/tmp"},
            "temporary": {"path": "/tmp"},
        }

        with pytest.raises(ConfigurationValidationError) as exc_info:
            config._validate_configuration(invalid_config)

        assert "must be a dictionary" in str(exc_info.value)

    def test_validate_folder_missing_path(self):
        """Test validation fails if folder is missing path field."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        invalid_config = {
            section: {} for section in EthoscopeConfiguration.REQUIRED_SECTIONS
        }
        invalid_config["folders"] = {
            "results": {"description": "no path"},
            "video": {"path": "/tmp"},
            "temporary": {"path": "/tmp"},
        }

        with pytest.raises(ConfigurationValidationError) as exc_info:
            config._validate_configuration(invalid_config)

        assert "missing 'path' field" in str(exc_info.value)

    def test_validate_folder_path_not_string(self):
        """Test validation fails if folder path is not a string."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        invalid_config = {
            section: {} for section in EthoscopeConfiguration.REQUIRED_SECTIONS
        }
        invalid_config["folders"] = {
            "results": {"path": 123},
            "video": {"path": "/tmp"},
            "temporary": {"path": "/tmp"},
        }

        with pytest.raises(ConfigurationValidationError) as exc_info:
            config._validate_configuration(invalid_config)

        assert "path must be a string" in str(exc_info.value)

    def test_validate_valid_configuration(self):
        """Test validation passes for valid configuration."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        valid_config = EthoscopeConfiguration.DEFAULT_SETTINGS.copy()

        # Should not raise
        config._validate_configuration(valid_config)


class TestEthoscopeConfigurationMerge:
    """Test configuration merging with defaults."""

    def test_merge_empty_config_returns_defaults(self):
        """Test merging empty config returns defaults."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        result = config._merge_with_defaults({})

        assert result == EthoscopeConfiguration.DEFAULT_SETTINGS

    def test_merge_preserves_custom_values(self):
        """Test merging preserves custom values."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        custom_config = {
            "folders": {"results": {"path": "/custom/path"}},
            "custom": {"MY_SETTING": "custom_value"},
        }

        result = config._merge_with_defaults(custom_config)

        assert result["folders"]["results"]["path"] == "/custom/path"
        assert result["custom"]["MY_SETTING"] == "custom_value"
        # Default values should still be present
        assert "video" in result["folders"]
        assert "UPDATE_SERVICE_URL" in result["custom"]

    def test_merge_deep_merge_nested_dicts(self):
        """Test deep merging of nested dictionaries."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        custom_config = {
            "smtp": {"enabled": True, "host": "mail.example.com"},
            "alerts": {"enabled": False},
        }

        result = config._merge_with_defaults(custom_config)

        # Custom values
        assert result["smtp"]["enabled"] is True
        assert result["smtp"]["host"] == "mail.example.com"
        assert result["alerts"]["enabled"] is False

        # Default values preserved
        assert result["smtp"]["port"] == 587
        assert result["alerts"]["cooldown_seconds"] == 3600

    def test_merge_migrates_authentication_from_tunnel(self):
        """Test migration of authentication_enabled from tunnel to authentication section."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        old_config = {
            "tunnel": {"enabled": True, "authentication_enabled": True},
        }

        result = config._merge_with_defaults(old_config)

        # authentication_enabled should be moved to authentication section
        assert result["authentication"]["enabled"] is True
        assert "authentication_enabled" not in result["tunnel"]


class TestEthoscopeConfigurationLoadSave:
    """Test configuration loading and saving."""

    def test_load_creates_default_if_not_exists(self):
        """Test load creates default config if file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._logger = MagicMock()
            config._settings = {}

            with patch.object(config, "save") as mock_save:
                result = config.load()

                assert result == EthoscopeConfiguration.DEFAULT_SETTINGS
                mock_save.assert_called_once()

    def test_load_reads_existing_config(self):
        """Test load reads existing configuration file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"
            test_config = EthoscopeConfiguration.DEFAULT_SETTINGS.copy()
            test_config["custom"]["TEST"] = "value"
            config_file.write_text(json.dumps(test_config))

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._logger = MagicMock()
            config._settings = {}

            with patch.object(config, "save"):
                result = config.load()

                assert result["custom"]["TEST"] == "value"

    def test_load_handles_empty_file(self):
        """Test load handles empty configuration file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"
            config_file.write_text("")

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._logger = MagicMock()
            config._settings = {}

            with pytest.raises(ConfigurationError) as exc_info:
                config.load()

            assert "Configuration file is empty" in str(exc_info.value)

    def test_load_handles_invalid_json(self):
        """Test load handles invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"
            config_file.write_text("not valid json {")

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._logger = MagicMock()
            config._settings = {}

            with pytest.raises(ConfigurationError) as exc_info:
                config.load()

            assert "Invalid JSON" in str(exc_info.value)

    def test_save_creates_directory(self):
        """Test save creates parent directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "nested" / "dir" / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._logger = MagicMock()
            config._settings = {"test": "data"}

            config.save()

            assert config_file.parent.exists()
            assert config_file.exists()

    def test_save_writes_json_properly(self):
        """Test save writes properly formatted JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._logger = MagicMock()
            config._settings = {"test": "data", "number": 123}

            config.save()

            content = json.loads(config_file.read_text())
            assert content == {"test": "data", "number": 123}

    def test_save_error_handling(self):
        """Test save handles errors properly."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._config_file = Path("/invalid/path/test.conf")
        config._logger = MagicMock()
        config._settings = {"test": "data"}

        with pytest.raises(ConfigurationError) as exc_info:
            config.save()

        assert "Failed to write configuration file" in str(exc_info.value)


class TestEthoscopeConfigurationProperties:
    """Test configuration properties and accessors."""

    def test_content_property(self):
        """Test content property returns settings."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"test": "data"}

        assert config.content == {"test": "data"}

    def test_file_exists_property_true(self):
        """Test file_exists returns True for existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"
            config_file.write_text("{}")

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file

            assert config.file_exists is True

    def test_file_exists_property_false(self):
        """Test file_exists returns False for nonexistent file."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._config_file = Path("/nonexistent/file.conf")

        assert config.file_exists is False


class TestEthoscopeConfigurationSections:
    """Test section management functionality."""

    def test_add_section_new(self):
        """Test adding a new section."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {}
        config._logger = MagicMock()

        config.add_section("new_section")

        assert "new_section" in config._settings
        assert config._settings["new_section"] == {}

    def test_add_section_already_exists(self):
        """Test adding section that already exists raises error."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"existing": {}}
        config._logger = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            config.add_section("existing")

        assert "already exists" in str(exc_info.value)

    def test_list_sections(self):
        """Test listing all sections."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"section1": {}, "section2": {}, "section3": {}}

        sections = config.list_sections()

        assert sorted(sections) == ["section1", "section2", "section3"]

    def test_list_subsection_existing(self):
        """Test listing subsections of existing section."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"section": {"key1": "val1", "key2": "val2"}}

        subsections = config.list_subsection("section")

        assert sorted(subsections) == ["key1", "key2"]

    def test_list_subsection_nonexistent(self):
        """Test listing subsections of nonexistent section returns empty list."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {}

        subsections = config.list_subsection("nonexistent")

        assert subsections == []

    def test_add_key_to_existing_section(self):
        """Test adding keys to existing section."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"section": {"old": "value"}}
        config._logger = MagicMock()

        config.add_key("section", {"new": "data"})

        assert config._settings["section"]["old"] == "value"
        assert config._settings["section"]["new"] == "data"

    def test_add_key_creates_section_if_missing(self):
        """Test adding keys creates section if it doesn't exist."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {}
        config._logger = MagicMock()

        config.add_key("new_section", {"key": "value"})

        assert "new_section" in config._settings
        assert config._settings["new_section"]["key"] == "value"


class TestEthoscopeConfigurationUsers:
    """Test user management functionality."""

    def test_add_user_missing_name(self):
        """Test add_user raises error if name is missing."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            config.add_user({})

        assert "must include 'name' field" in str(exc_info.value)

    def test_add_user_success(self):
        """Test successful user addition."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.addUser.return_value = 1
        mock_db.getAllUsers.return_value = {"user1": {"username": "user1"}}

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            result = config.add_user(
                {
                    "name": "testuser",
                    "fullname": "Test User",
                    "PIN": "1234",
                    "email": "test@example.com",
                    "isAdmin": True,
                }
            )

        assert result["result"] == "success"
        mock_db.addUser.assert_called_once()

    def test_add_user_database_failure(self):
        """Test add_user handles database failure."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.addUser.return_value = 0  # Failure

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            with pytest.raises(ValueError) as exc_info:
                config.add_user({"name": "testuser"})

        assert "Failed to add user" in str(exc_info.value)

    def test_remove_user_success(self):
        """Test successful user removal."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.deactivateUser.return_value = 1

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            result = config.remove_user("testuser")

        assert result is True
        mock_db.deactivateUser.assert_called_once_with(username="testuser")

    def test_remove_user_not_found(self):
        """Test removing user that doesn't exist."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.deactivateUser.return_value = 0

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            result = config.remove_user("nonexistent")

        assert result is False


class TestEthoscopeConfigurationIncubators:
    """Test incubator management functionality."""

    def test_add_incubator_missing_name(self):
        """Test add_incubator raises error if name is missing."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            config.add_incubator({})

        assert "must include 'name' field" in str(exc_info.value)

    def test_add_incubator_success(self):
        """Test successful incubator addition."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.addIncubator.return_value = 1
        mock_db.getAllIncubators.return_value = {"inc1": {"name": "inc1"}}

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            result = config.add_incubator(
                {
                    "name": "Test Incubator",
                    "location": "Lab A",
                    "owner": "researcher",
                    "description": "Test",
                }
            )

        assert result["result"] == "success"
        mock_db.addIncubator.assert_called_once()

    def test_add_incubator_database_failure(self):
        """Test add_incubator handles database failure."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.addIncubator.return_value = 0

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            with pytest.raises(ValueError) as exc_info:
                config.add_incubator({"name": "Test Incubator"})

        assert "Failed to add incubator" in str(exc_info.value)


class TestEthoscopeConfigurationSensors:
    """Test sensor management functionality."""

    def test_add_sensor_missing_name(self):
        """Test add_sensor raises error if name is missing."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            config.add_sensor({})

        assert "must include 'name' field" in str(exc_info.value)

    def test_add_sensor_success(self):
        """Test successful sensor addition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {"sensors": {}}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                result = config.add_sensor(
                    {"name": "temp_sensor", "type": "temperature", "location": "room1"}
                )

            assert result["result"] == "success"
            assert "temp_sensor" in config._settings["sensors"]

    def test_add_sensor_creates_sensors_section(self):
        """Test add_sensor creates sensors section if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                config.add_sensor({"name": "sensor1"})

            assert "sensors" in config._settings


class TestEthoscopeConfigurationCustom:
    """Test custom configuration value management."""

    def test_get_custom_all(self):
        """Test getting all custom values."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"custom": {"KEY1": "val1", "KEY2": "val2"}}

        result = config.get_custom()

        assert result == {"KEY1": "val1", "KEY2": "val2"}

    def test_get_custom_specific_key(self):
        """Test getting specific custom value."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"custom": {"KEY1": "val1", "KEY2": "val2"}}

        result = config.get_custom("KEY1")

        assert result == "val1"

    def test_get_custom_nonexistent_key(self):
        """Test getting nonexistent custom value returns None."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"custom": {}}

        result = config.get_custom("NONEXISTENT")

        assert result is None

    def test_custom_legacy_method(self):
        """Test legacy custom() method works."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"custom": {"KEY": "value"}}

        result = config.custom("KEY")

        assert result == "value"

    def test_update_custom_existing_section(self):
        """Test updating custom value in existing section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {"custom": {"OLD": "value"}}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                config.update_custom("NEW", "new_value")

            assert config._settings["custom"]["NEW"] == "new_value"
            assert config._settings["custom"]["OLD"] == "value"

    def test_update_custom_creates_section(self):
        """Test update_custom creates custom section if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                config.update_custom("KEY", "value")

            assert config._settings["custom"]["KEY"] == "value"


class TestEthoscopeConfigurationFolders:
    """Test folder path management."""

    def test_get_folder_path_existing(self):
        """Test getting path for existing folder."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {
            "folders": {"results": {"path": "/data/results", "description": "Results"}}
        }

        path = config.get_folder_path("results")

        assert path == "/data/results"

    def test_get_folder_path_nonexistent(self):
        """Test getting path for nonexistent folder returns None."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"folders": {}}

        path = config.get_folder_path("nonexistent")

        assert path is None

    def test_get_folder_path_missing_path_key(self):
        """Test getting folder path when path key is missing."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"folders": {"results": {"description": "No path"}}}

        path = config.get_folder_path("results")

        assert path is None


class TestEthoscopeConfigurationSetup:
    """Test setup workflow functionality."""

    def test_is_setup_completed_true(self):
        """Test is_setup_completed returns True when setup is done."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"setup": {"completed": True}}

        assert config.is_setup_completed() is True

    def test_is_setup_completed_false(self):
        """Test is_setup_completed returns False when setup not done."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"setup": {"completed": False}}

        assert config.is_setup_completed() is False

    def test_is_setup_required_when_completed(self):
        """Test is_setup_required returns False when setup completed."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"setup": {"completed": True}}

        assert config.is_setup_required() is False

    def test_is_setup_required_no_admin_users(self):
        """Test is_setup_required returns True when no admin users exist."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"setup": {"completed": False}}
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {}

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            result = config.is_setup_required()

        assert result is True

    def test_is_setup_required_with_default_admin(self):
        """Test is_setup_required returns True with default admin users."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"setup": {"completed": False}}
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {
            "admin": {"username": "admin", "isadmin": 1, "email": "admin@localhost"}
        }

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            result = config.is_setup_required()

        assert result is True

    def test_get_setup_status(self):
        """Test getting detailed setup status."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {
            "setup": {
                "completed": True,
                "steps_completed": ["step1", "step2"],
                "setup_started": "2025-01-01T00:00:00",
                "setup_completed": "2025-01-01T01:00:00",
                "setup_version": "1.0",
            },
            "smtp": {"enabled": False},
            "mattermost": {"enabled": False},
            "slack": {"enabled": False},
        }
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {"user1": {"isadmin": 1}}
        mock_db.getAllIncubators.return_value = {"inc1": {}}

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            status = config.get_setup_status()

        assert status["completed"] is True
        assert status["steps_completed"] == ["step1", "step2"]
        assert "system_info" in status

    def test_mark_setup_step_completed(self):
        """Test marking a setup step as completed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {"setup": {"steps_completed": ["step1"]}}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                config.mark_setup_step_completed("step2")

            assert "step2" in config._settings["setup"]["steps_completed"]
            assert config._settings["setup"]["setup_started"] is not None

    def test_complete_setup(self):
        """Test marking setup as completed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {"setup": {"completed": False}}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                config.complete_setup()

            assert config._settings["setup"]["completed"] is True
            assert config._settings["setup"]["setup_completed"] is not None

    def test_reset_setup(self):
        """Test resetting setup status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {
                "setup": {
                    "completed": True,
                    "steps_completed": ["step1", "step2"],
                    "setup_started": "2025-01-01",
                }
            }
            config._logger = MagicMock()

            with patch.object(config, "save"):
                config.reset_setup()

            assert (
                config._settings["setup"]
                == EthoscopeConfiguration.DEFAULT_SETTINGS["setup"]
            )


class TestEthoscopeConfigurationTunnel:
    """Test tunnel configuration functionality."""

    def test_get_tunnel_node_id_manual(self):
        """Test getting manually set tunnel node ID."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"tunnel": {"node_id": "custom-node-123"}}
        config._logger = MagicMock()

        node_id = config.get_tunnel_node_id()

        assert node_id == "custom-node-123"

    def test_get_tunnel_node_id_auto_with_admin(self):
        """Test automatic node ID generation with admin user."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"tunnel": {"node_id": "auto"}}
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {
            "admin": {"name": "AdminUser", "isAdmin": True}
        }

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            node_id = config.get_tunnel_node_id()

        assert node_id == "node-adminuser"

    def test_get_tunnel_node_id_auto_fallback_hostname(self):
        """Test automatic node ID falls back to hostname."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"tunnel": {"node_id": "auto"}}
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {}

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            with patch(
                "ethoscope_node.utils.configuration.socket.gethostname",
                return_value="test-host",
            ):
                node_id = config.get_tunnel_node_id()

        assert node_id == "node-test-host"

    def test_update_tunnel_config(self):
        """Test updating tunnel configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {"tunnel": {"enabled": False}}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                result = config.update_tunnel_config(
                    {"enabled": True, "mode": "ethoscope_net", "token": "abc123"}
                )

            assert result["enabled"] is True
            assert result["mode"] == "ethoscope_net"
            assert result["token"] == "abc123"

    def test_update_tunnel_config_updates_timestamp(self):
        """Test tunnel config update sets timestamp when status changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {"tunnel": {}}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                config.update_tunnel_config({"status": "connected"})

            assert config._settings["tunnel"]["last_connected"] is not None

    def test_get_tunnel_config_paid_mode(self):
        """Test getting tunnel config in paid mode."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"tunnel": {"mode": "ethoscope_net", "node_id": "test-node"}}
        config._logger = MagicMock()

        result = config.get_tunnel_config()

        assert result["is_paid_mode"] is True
        assert result["effective_domain"] == "ethoscope.net"
        assert result["full_domain"] == "test-node.ethoscope.net"

    def test_get_tunnel_config_free_mode(self):
        """Test getting tunnel config in free mode."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {
            "tunnel": {
                "mode": "custom",
                "node_id": "test-node",
                "custom_domain": "example.com",
            }
        }
        config._logger = MagicMock()

        result = config.get_tunnel_config()

        assert result["is_paid_mode"] is False
        assert result["effective_domain"] == "example.com"
        assert result["full_domain"] == "test-node.example.com"


class TestEthoscopeConfigurationAuthentication:
    """Test authentication configuration functionality."""

    def test_get_authentication_config(self):
        """Test getting authentication configuration."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"authentication": {"enabled": True}}

        result = config.get_authentication_config()

        assert result["enabled"] is True

    def test_update_authentication_config(self):
        """Test updating authentication configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._settings = {"authentication": {"enabled": False}}
            config._logger = MagicMock()

            with patch.object(config, "save"):
                result = config.update_authentication_config({"enabled": True})

            assert result["enabled"] is True


class TestEthoscopeConfigurationPINMigration:
    """Test PIN migration functionality."""

    def test_migrate_user_pins_no_users(self):
        """Test PIN migration with no users."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {}

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            count = config.migrate_user_pins()

        assert count == 0

    def test_migrate_user_pins_dry_run(self):
        """Test PIN migration in dry run mode."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {"user1": {"pin": "1234"}}

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            count = config.migrate_user_pins(dry_run=True)

        assert count == 1
        mock_db.migrate_plaintext_pins.assert_not_called()

    def test_migrate_user_pins_success(self):
        """Test successful PIN migration."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()
        config._settings = {"setup": {}}
        config._config_file = Path("/tmp/test.conf")

        mock_db = MagicMock()
        mock_db.getAllUsers.return_value = {"user1": {"pin": "1234"}}
        mock_db.migrate_plaintext_pins.return_value = 1

        with patch("ethoscope_node.utils.etho_db.ExperimentalDB", return_value=mock_db):
            with patch.object(config, "save"):
                count = config.migrate_user_pins()

        assert count == 1
        assert "pin_migration" in config._settings["setup"].get("steps_completed", [])


class TestEthoscopeConfigurationReload:
    """Test configuration reload functionality."""

    def test_reload(self):
        """Test reloading configuration from file."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        with patch.object(config, "load", return_value={"test": "data"}) as mock_load:
            result = config.reload()

        assert result == {"test": "data"}
        mock_load.assert_called_once()


class TestSSHKeyManagement:
    """Test SSH key management functionality."""

    def test_ensure_ssh_keys_creates_directory(self):
        """Test ensure_ssh_keys creates keys directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            keys_dir = Path(tmpdir) / "keys"

            def mock_ssh_keygen(*args, **kwargs):
                # Create the key files that ssh-keygen would create
                private_key_file = keys_dir / "id_rsa"
                public_key_file = keys_dir / "id_rsa.pub"
                private_key_file.write_text("fake private key")
                public_key_file.write_text("fake public key")
                return Mock(stdout="Key generated")

            with patch("subprocess.run", side_effect=mock_ssh_keygen):
                with patch(
                    "ethoscope_node.utils.configuration._setup_system_ssh_config"
                ):
                    private_key, public_key = ensure_ssh_keys(str(keys_dir))

                    assert keys_dir.exists()
                    assert private_key == str(keys_dir / "id_rsa")
                    assert public_key == str(keys_dir / "id_rsa.pub")

    def test_ensure_ssh_keys_returns_existing(self):
        """Test ensure_ssh_keys returns existing keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            keys_dir = Path(tmpdir) / "keys"
            keys_dir.mkdir()

            private_key_path = keys_dir / "id_rsa"
            public_key_path = keys_dir / "id_rsa.pub"
            private_key_path.write_text("private")
            public_key_path.write_text("public")

            private_key, public_key = ensure_ssh_keys(str(keys_dir))

            assert private_key == str(private_key_path)
            assert public_key == str(public_key_path)

    def test_ensure_ssh_keys_generates_new_keys(self):
        """Test ensure_ssh_keys generates new key pair."""
        with tempfile.TemporaryDirectory() as tmpdir:
            keys_dir = Path(tmpdir) / "keys"

            def mock_ssh_keygen(*args, **kwargs):
                # Create the key files that ssh-keygen would create
                private_key_file = keys_dir / "id_rsa"
                public_key_file = keys_dir / "id_rsa.pub"
                private_key_file.write_text("fake private key")
                public_key_file.write_text("fake public key")
                return Mock(stdout="Keys generated")

            with patch("subprocess.run", side_effect=mock_ssh_keygen) as mock_run:
                with patch(
                    "ethoscope_node.utils.configuration._setup_system_ssh_config"
                ):
                    with patch(
                        "ethoscope_node.utils.configuration.socket.gethostname",
                        return_value="test-host",
                    ):
                        private_key, public_key = ensure_ssh_keys(str(keys_dir))

                        # Verify ssh-keygen was called with correct parameters
                        call_args = mock_run.call_args[0][0]
                        assert "ssh-keygen" in call_args
                        assert "-t" in call_args
                        assert "rsa" in call_args

    def test_ensure_ssh_keys_handles_generation_failure(self):
        """Test ensure_ssh_keys handles key generation failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            keys_dir = Path(tmpdir) / "keys"

            with patch("subprocess.run") as mock_run:
                with patch(
                    "ethoscope_node.utils.configuration._setup_system_ssh_config"
                ):
                    mock_run.side_effect = subprocess.CalledProcessError(
                        1, "ssh-keygen", stderr="Generation failed"
                    )

                    with pytest.raises(ConfigurationError) as exc_info:
                        ensure_ssh_keys(str(keys_dir))

                    assert "Failed to generate SSH keys" in str(exc_info.value)

    def test_ensure_ssh_keys_handles_permission_error(self):
        """Test ensure_ssh_keys handles permission errors."""
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Access denied")

            with pytest.raises(ConfigurationError) as exc_info:
                ensure_ssh_keys("/protected/path")

            assert "Permission denied" in str(exc_info.value)


class TestConfigurationEdgeCases:
    """Test edge cases and error conditions."""

    def test_load_with_validation_error_is_not_wrapped(self):
        """Test that ConfigurationValidationError is raised properly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"
            # Invalid config with folder path not being a string
            invalid_config = {
                section: {} for section in EthoscopeConfiguration.REQUIRED_SECTIONS
            }
            invalid_config["folders"] = {
                "results": {"path": 123},  # Invalid: path must be string
                "video": {"path": "/tmp"},
                "temporary": {"path": "/tmp"},
            }
            config_file.write_text(json.dumps(invalid_config))

            config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
            config._config_file = config_file
            config._logger = MagicMock()
            config._settings = {}

            with pytest.raises(ConfigurationValidationError) as exc_info:
                config.load()

            assert "path must be a string" in str(exc_info.value)

    def test_add_user_with_exception(self):
        """Test add_user handles database exceptions."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        with patch(
            "ethoscope_node.utils.etho_db.ExperimentalDB",
            side_effect=Exception("Database error"),
        ):
            with pytest.raises(ValueError) as exc_info:
                config.add_user({"name": "testuser"})

            assert "Failed to add user" in str(exc_info.value)

    def test_get_setup_status_handles_database_error(self):
        """Test get_setup_status handles database errors gracefully."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._settings = {"setup": {"completed": True}}
        config._logger = MagicMock()

        with patch(
            "ethoscope_node.utils.etho_db.ExperimentalDB",
            side_effect=Exception("DB error"),
        ):
            status = config.get_setup_status()

        assert status["system_info"] == {}

    def test_migrate_user_pins_handles_error(self):
        """Test PIN migration handles errors."""
        config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
        config._logger = MagicMock()

        with patch(
            "ethoscope_node.utils.etho_db.ExperimentalDB",
            side_effect=Exception("Migration error"),
        ):
            with pytest.raises(ConfigurationError) as exc_info:
                config.migrate_user_pins()

            assert "PIN migration failed" in str(exc_info.value)


class TestConfigurationIntegration:
    """Integration tests for complete workflows."""

    def test_full_initialization_workflow(self):
        """Test complete initialization workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "ethoscope.conf"

            # Initialize - should create config with defaults
            config = EthoscopeConfiguration(str(config_file))

            # Verify file was created
            assert config_file.exists()

            # Verify all required sections are present
            for section in EthoscopeConfiguration.REQUIRED_SECTIONS:
                assert section in config._settings

            # Verify content matches defaults
            assert config._settings == EthoscopeConfiguration.DEFAULT_SETTINGS

    def test_load_save_reload_preserves_data(self):
        """Test that load/save/reload cycle preserves all data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test.conf"

            # Create config with custom data
            config1 = EthoscopeConfiguration(str(config_file))
            config1.update_custom("TEST_KEY", "test_value")
            config1.add_key("commands", {"test_cmd": {"name": "Test"}})

            # Reload into new instance
            config2 = EthoscopeConfiguration(str(config_file))

            # Verify data was preserved
            assert config2.get_custom("TEST_KEY") == "test_value"
            assert "test_cmd" in config2._settings["commands"]

    def test_configuration_with_legacy_migration(self):
        """Test configuration initialization with legacy file migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create legacy config file
            legacy_file = Path(tmpdir) / "ethoscope.conf"
            legacy_config = {
                "folders": {
                    "results": {"path": "/old/path"},
                    "video": {"path": "/old/video"},
                    "temporary": {"path": "/tmp"},
                },
                "tunnel": {"enabled": False, "authentication_enabled": True},
            }
            legacy_file.write_text(json.dumps(legacy_config))

            # New config location
            new_dir = Path(tmpdir) / "new"
            new_file = new_dir / "ethoscope.conf"

            # Migrate and load
            migrate_conf_file(str(legacy_file), str(new_dir))
            config = EthoscopeConfiguration(str(new_file))

            # Verify migration happened
            assert not legacy_file.exists()
            assert new_file.exists()

            # Verify authentication was migrated from tunnel section
            assert config._settings["authentication"]["enabled"] is True
