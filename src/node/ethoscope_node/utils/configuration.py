import os
import json
import datetime
import logging
import shutil
import subprocess
import socket
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

# Configuration validation constants
USERS_KEYS = ['name', 'fullname', 'PIN', 'email', 'telephone', 'group', 'active', 'isAdmin', 'created']
INCUBATORS_KEYS = ['id', 'name', 'location', 'owner', 'description']


class ConfigurationError(Exception):
    """Custom exception for configuration-related errors."""
    pass


class ConfigurationValidationError(ConfigurationError):
    """Exception for configuration validation errors."""
    pass


def migrate_conf_file(file_path: str, destination: str = '/etc/ethoscope/') -> bool:
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
        'folders': {
            'results': {
                'path': '/ethoscope_data/results',
                'description': 'Where tracking data will be saved by the backup daemon.'
            },
            'video': {
                'path': '/ethoscope_data/videos',
                'description': 'Where video chunks (h264) will be saved by the backup daemon'
            },
            'temporary': {
                'path': '/ethoscope_data/results',
                'description': 'A temporary location for downloading data.'
            }
        },
        'users': {
            'admin': {
                'id': 1,
                'name': 'admin',
                'fullname': '',
                'PIN': 9999,
                'email': '',
                'telephone': '',
                'group': '',
                'active': False,
                'isAdmin': True,
                'created': datetime.datetime.now().timestamp()
            }
        },
        'incubators': {
            'incubator 1': {
                'id': 1,
                'name': 'Incubator 1',
                'location': '',
                'owner': '',
                'description': ''
            }
        },
        'sensors': {},
        'commands': {
            'command_1': {
                'name': 'List ethoscope files.',
                'description': 'Show ethoscope data folders on the node. Just an example of how to write a command',
                'command': 'ls -lh /ethoscope_data/results'
            }
        },
        'custom': {
            'UPDATE_SERVICE_URL': 'http://localhost:8888'
        }
    }
    
    REQUIRED_SECTIONS = ['folders', 'users', 'incubators', 'sensors', 'commands', 'custom']
    REQUIRED_FOLDERS = ['results', 'video', 'temporary']
    
    def __init__(self, config_file: str = "/etc/ethoscope/ethoscope.conf"):
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to configuration file
        """
        self._config_file = Path(config_file)
        self._settings = {}
        self._logger = logging.getLogger(self.__class__.__name__)
        
        # Perform migration if needed
        self._migrate_legacy_files()
        
        # Load configuration
        self.load()
    
    def _migrate_legacy_files(self):
        """Migrate legacy configuration files to new location."""
        legacy_paths = [
            '/etc/ethoscope.conf',
            '/etc/node.conf'  # Add other legacy paths as needed
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
            raise ConfigurationValidationError(f"Missing required sections: {missing_sections}")
        
        # Validate folders section
        folders = config_data.get('folders', {})
        missing_folders = set(self.REQUIRED_FOLDERS) - set(folders.keys())
        if missing_folders:
            raise ConfigurationValidationError(f"Missing required folders: {missing_folders}")
        
        # Validate folder structure
        for folder_name, folder_config in folders.items():
            if not isinstance(folder_config, dict):
                raise ConfigurationValidationError(f"Folder '{folder_name}' must be a dictionary")
            
            if 'path' not in folder_config:
                raise ConfigurationValidationError(f"Folder '{folder_name}' missing 'path' field")
            
            if not isinstance(folder_config['path'], str):
                raise ConfigurationValidationError(f"Folder '{folder_name}' path must be a string")
        
        # Validate users section
        users = config_data.get('users', {})
        if not isinstance(users, dict):
            raise ConfigurationValidationError("Users section must be a dictionary")
        
        # Validate user structure
        for user_name, user_data in users.items():
            if not isinstance(user_data, dict):
                raise ConfigurationValidationError(f"User '{user_name}' must be a dictionary")
            
            missing_user_keys = set(USERS_KEYS) - set(user_data.keys())
            if missing_user_keys:
                self._logger.warning(f"User '{user_name}' missing fields: {missing_user_keys}")
    
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
                if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                    deep_merge(target[key], value)
                else:
                    target[key] = value
            return target
        
        return deep_merge(merged, config_data)
    
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
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, indent=4, sort_keys=True, ensure_ascii=False)
            
            self._logger.info(f'Saved ethoscope configuration to {self._config_file}')
            
        except Exception as e:
            raise ConfigurationError(f'Failed to write configuration file {self._config_file}: {e}')
    
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
            with open(self._config_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
                if not content:
                    raise ValueError("Configuration file is empty")
                
                try:
                    loaded_config = json.loads(content)
                except json.JSONDecodeError as e:
                    raise ConfigurationError(f"Invalid JSON in configuration file: {e}")
            
            # Validate configuration
            self._validate_configuration(loaded_config)
            
            # Merge with defaults
            self._settings = self._merge_with_defaults(loaded_config)
            
            # Save merged configuration back to file
            self.save()
            
            self._logger.info(f"Configuration loaded successfully from {self._config_file}")
            return self._settings
            
        except Exception as e:
            if isinstance(e, (ConfigurationError, ConfigurationValidationError)):
                raise
            else:
                raise ConfigurationError(f"Failed to load configuration file {self._config_file}: {e}")
    
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
        self._logger.info(f"Updated section '{section}' with new keys: {list(obj.keys())}")
    
    def add_user(self, userdata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new user to configuration.
        
        Args:
            userdata: User data dictionary
            
        Returns:
            Result dictionary with success/failure status
            
        Raises:
            ValueError: If user data is invalid
        """
        if 'name' not in userdata:
            raise ValueError("User data must include 'name' field")
        
        name = userdata['name']
        
        try:
            # Validate user data
            for key in USERS_KEYS:
                if key not in userdata and key not in ['created']:
                    self._logger.warning(f"User '{name}' missing field: {key}")
            
            # Set creation timestamp
            userdata['created'] = datetime.datetime.now().timestamp()
            
            # Add user
            if 'users' not in self._settings:
                self._settings['users'] = {}
            
            self._settings['users'][name] = userdata
            self.save()
            
            self._logger.info(f"Added user: {name}")
            return {'result': 'success', 'data': self._settings['users']}
            
        except Exception as e:
            error_msg = f"Failed to add user '{name}': {e}"
            self._logger.error(error_msg)
            raise ValueError(error_msg)
    
    def add_incubator(self, incubatordata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new incubator to configuration.
        
        Args:
            incubatordata: Incubator data dictionary
            
        Returns:
            Result dictionary with success/failure status
            
        Raises:
            ValueError: If incubator data is invalid
        """
        if 'name' not in incubatordata:
            raise ValueError("Incubator data must include 'name' field")
        
        name = incubatordata['name']
        
        try:
            # Validate incubator data
            for key in INCUBATORS_KEYS:
                if key not in incubatordata:
                    self._logger.warning(f"Incubator '{name}' missing field: {key}")
            
            # Add incubator
            if 'incubators' not in self._settings:
                self._settings['incubators'] = {}
            
            self._settings['incubators'][name] = incubatordata
            self.save()
            
            self._logger.info(f"Added incubator: {name}")
            return {'result': 'success', 'data': self._settings['incubators']}
            
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
        if 'name' not in sensordata:
            raise ValueError("Sensor data must include 'name' field")
        
        name = sensordata['name']
        
        try:
            # Add sensor
            if 'sensors' not in self._settings:
                self._settings['sensors'] = {}
            
            self._settings['sensors'][name] = sensordata
            self.save()
            
            self._logger.info(f"Added sensor: {name}")
            return {'result': 'success', 'data': self._settings['sensors']}
            
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
        custom_section = self._settings.get('custom', {})
        
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
        if 'custom' not in self._settings:
            self._settings['custom'] = {}
        
        self._settings['custom'][name] = value
        self.save()
        self._logger.info(f"Updated custom setting '{name}'")
    
    def remove_user(self, username: str) -> bool:
        """
        Remove a user from configuration.
        
        Args:
            username: Name of user to remove
            
        Returns:
            True if user was removed, False if not found
        """
        if 'users' not in self._settings or username not in self._settings['users']:
            return False
        
        del self._settings['users'][username]
        self.save()
        self._logger.info(f"Removed user: {username}")
        return True
    
    def get_folder_path(self, folder_name: str) -> Optional[str]:
        """
        Get path for a specific folder.
        
        Args:
            folder_name: Name of folder (e.g., 'results', 'video')
            
        Returns:
            Folder path or None if not found
        """
        folders = self._settings.get('folders', {})
        folder_config = folders.get(folder_name, {})
        return folder_config.get('path')
    
    def reload(self) -> Dict[str, Any]:
        """
        Reload configuration from file.
        
        Returns:
            Reloaded configuration settings
        """
        self._logger.info("Reloading configuration from file")
        return self.load()


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
            "-t", "rsa",           # RSA key type
            "-b", "2048",          # 2048-bit key
            "-f", str(private_key_path),  # Output file
            "-N", "",              # Empty passphrase
            "-C", comment          # Comment
        ]
        
        result = subprocess.run(
            ssh_keygen_cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        logger.info(f"Successfully generated SSH keys: {comment}")
        logger.debug(f"ssh-keygen output: {result.stdout}")
        
        # Set proper permissions
        os.chmod(private_key_path, 0o600)  # -rw-------
        os.chmod(public_key_path, 0o644)   # -rw-r--r--
        
        logger.info(f"Set proper permissions on SSH keys")
        logger.info(f"Private key: {private_key_path} (600)")
        logger.info(f"Public key: {public_key_path} (644)")
        
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
        c.add_key('commands', {
            'sync_command': {
                'name': 'Sync all data to Turing',
                'description': 'Sync all the ethoscope data to turing',
                'command': '/etc/cron.hourly/sync'
            }
        })
        
        c.add_key('commands', {
            'cleanup_command': {
                'name': 'Delete old files',
                'description': 'Delete ethoscope data older than 90 days',
                'command': 'find /ethoscope_data/results -type f -mtime +90 -exec rm {} \\;'
            }
        })
        
        print("Configuration sections:", c.list_sections())
        print("Commands:", c.content['commands'])
        
        c.save()
        print("Configuration saved successfully")
        
    except Exception as e:
        logging.error(f"Configuration test failed: {e}")
        raise


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()