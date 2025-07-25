"""
Unit tests for SSH configuration setup functionality.

Tests the SSH key generation and system-wide SSH configuration
setup used for ethoscope device connections.
"""

import pytest
import tempfile
import shutil
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, Mock, mock_open, call
from ethoscope_node.utils.configuration import ensure_ssh_keys, _setup_system_ssh_config, ConfigurationError


class TestEnsureSshKeys:
    """Test SSH key generation and setup."""
    
    def test_creates_keys_directory(self):
        """Test that keys directory is created with proper permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = os.path.join(temp_dir, "test_keys")
            
            def mock_subprocess_run(cmd, **kwargs):
                # Create fake key files when ssh-keygen is called
                if cmd[0] == "ssh-keygen":
                    private_key = cmd[cmd.index("-f") + 1]
                    public_key = private_key + ".pub"
                    Path(private_key).touch()
                    Path(public_key).touch()
                return Mock(stdout="Generated key", stderr="")
            
            with patch('subprocess.run', side_effect=mock_subprocess_run):
                with patch('ethoscope_node.utils.configuration._setup_system_ssh_config'):
                    ensure_ssh_keys(keys_dir)
                
                assert os.path.exists(keys_dir)
                # Check directory permissions are 700 (drwx------)
                stat_info = os.stat(keys_dir)
                assert oct(stat_info.st_mode)[-3:] == '700'
    
    def test_returns_existing_keys(self):
        """Test returns paths to existing keys without regenerating."""
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = temp_dir
            private_key = os.path.join(keys_dir, "id_rsa")
            public_key = os.path.join(keys_dir, "id_rsa.pub")
            
            # Create dummy key files
            Path(private_key).touch()
            Path(public_key).touch()
            
            with patch('subprocess.run') as mock_run:
                private_path, public_path = ensure_ssh_keys(keys_dir)
                
                # Should not call ssh-keygen if keys exist
                mock_run.assert_not_called()
                assert private_path == private_key
                assert public_path == public_key
    
    @patch('socket.gethostname')
    @patch('subprocess.run')
    def test_generates_new_keys(self, mock_run, mock_hostname):
        """Test generates new SSH keys when they don't exist."""
        mock_hostname.return_value = "test-node"
        
        def mock_subprocess_run(cmd, **kwargs):
            # Create fake key files when ssh-keygen is called
            if cmd[0] == "ssh-keygen":
                private_key = cmd[cmd.index("-f") + 1]
                public_key = private_key + ".pub"
                Path(private_key).touch()
                Path(public_key).touch()
            return Mock(stdout="Generated key", stderr="")
        
        mock_run.side_effect = mock_subprocess_run
        
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = temp_dir
            
            with patch('ethoscope_node.utils.configuration._setup_system_ssh_config'):
                private_path, public_path = ensure_ssh_keys(keys_dir)
            
            # Should call ssh-keygen with correct parameters
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "ssh-keygen"
            assert "-t" in call_args and "rsa" in call_args
            assert "-b" in call_args and "2048" in call_args
            assert "-f" in call_args
            assert "-N" in call_args and "" in call_args  # empty passphrase
            assert "-C" in call_args and "ethoscope-node@test-node" in call_args
            
            assert private_path == os.path.join(keys_dir, "id_rsa")
            assert public_path == os.path.join(keys_dir, "id_rsa.pub")
    
    @patch('subprocess.run')
    def test_sets_key_permissions(self, mock_run):
        """Test sets proper permissions on generated keys."""
        mock_run.return_value = Mock(stdout="Generated key", stderr="")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = temp_dir
            
            # Mock os.chmod to verify permissions are set
            with patch('os.chmod') as mock_chmod:
                ensure_ssh_keys(keys_dir)
                
                # Check that chmod was called for private key (600) and public key (644)
                chmod_calls = mock_chmod.call_args_list
                private_key_path = os.path.join(keys_dir, "id_rsa")
                public_key_path = os.path.join(keys_dir, "id_rsa.pub")
                
                # Find the chmod calls for the key files (ignore directory chmod)
                key_chmod_calls = [call for call in chmod_calls 
                                 if str(call[0][0]).endswith(('id_rsa', 'id_rsa.pub'))]
                
                assert len(key_chmod_calls) >= 2
    
    @patch('subprocess.run')
    def test_calls_ssh_config_setup(self, mock_run):
        """Test that SSH configuration setup is called."""
        def mock_subprocess_run(cmd, **kwargs):
            # Create fake key files when ssh-keygen is called
            if cmd[0] == "ssh-keygen":
                private_key = cmd[cmd.index("-f") + 1]
                public_key = private_key + ".pub"
                Path(private_key).touch()
                Path(public_key).touch()
            return Mock(stdout="Generated key", stderr="")
        
        mock_run.side_effect = mock_subprocess_run
        
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = temp_dir
            
            with patch('ethoscope_node.utils.configuration._setup_system_ssh_config') as mock_setup:
                ensure_ssh_keys(keys_dir)
                
                # Should call SSH config setup with private key path
                mock_setup.assert_called_once()
                private_key_path = os.path.join(keys_dir, "id_rsa")
                mock_setup.assert_called_with(private_key_path)
    
    @patch('subprocess.run')
    def test_handles_ssh_keygen_failure(self, mock_run):
        """Test handles ssh-keygen command failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "ssh-keygen", stderr="Key generation failed")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = temp_dir
            
            with pytest.raises(ConfigurationError) as exc_info:
                ensure_ssh_keys(keys_dir)
            
            assert "Failed to generate SSH keys" in str(exc_info.value)
    
    def test_handles_permission_error(self):
        """Test handles permission errors when creating keys directory."""
        # Try to create keys in a directory we can't write to
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")
            
            with pytest.raises(ConfigurationError) as exc_info:
                ensure_ssh_keys("/root/test_keys")
            
            assert "Permission denied creating SSH keys" in str(exc_info.value)


class TestSetupSystemSshConfig:
    """Test system SSH configuration setup."""
    
    @patch('ethoscope_node.utils.network.get_private_ip_pattern')
    def test_creates_new_config_file(self, mock_get_pattern):
        """Test creates new SSH config file when none exists."""
        mock_get_pattern.return_value = "192.168.1.*"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            ssh_config_path = os.path.join(temp_dir, "ssh_config")
            private_key_path = "/etc/ethoscope/keys/id_rsa"
            
            with patch('ethoscope_node.utils.configuration.os.path.exists') as mock_exists:
                mock_exists.return_value = False
                
                with patch('builtins.open', mock_open()) as mock_file:
                    with patch('os.chmod') as mock_chmod:
                        _setup_system_ssh_config(private_key_path)
                        
                        # Should create new file
                        mock_file.assert_called_once()
                        written_content = mock_file().write.call_args[0][0]
                        
                        assert "# Ethoscope SSH configuration" in written_content
                        assert "Host 192.168.1.* ethoscope*" in written_content
                        assert "User ethoscope" in written_content
                        assert "StrictHostKeyChecking no" in written_content
                        assert f"IdentityFile {private_key_path}" in written_content
    
    @patch('ethoscope_node.utils.network.get_private_ip_pattern')
    def test_appends_to_existing_config(self, mock_get_pattern):
        """Test appends to existing SSH config file."""
        mock_get_pattern.return_value = "10.0.*.*"
        existing_content = "# Existing SSH config\nHost example.com\n    User test\n"
        
        with patch('builtins.open', mock_open(read_data=existing_content)) as mock_file:
            with patch('os.path.exists') as mock_exists:
                mock_exists.return_value = True
                
                with patch('os.chmod') as mock_chmod:
                    _setup_system_ssh_config("/test/key/path")
                    
                    # Should read existing file first, then append
                    assert mock_file().read.called
                    assert mock_file().write.called
                    
                    written_content = mock_file().write.call_args[0][0]
                    assert "# Ethoscope SSH configuration" in written_content
                    assert "Host 10.0.*.* ethoscope*" in written_content
    
    @patch('ethoscope_node.utils.network.get_private_ip_pattern')
    def test_skips_if_config_exists(self, mock_get_pattern):
        """Test skips configuration if ethoscope config already exists."""
        mock_get_pattern.return_value = "192.168.1.*"
        existing_content = "# Ethoscope SSH configuration\nHost 192.168.1.*\n    User ethoscope\n"
        
        with patch('builtins.open', mock_open(read_data=existing_content)) as mock_file:
            with patch('os.path.exists') as mock_exists:
                mock_exists.return_value = True
                
                _setup_system_ssh_config("/test/key/path")
                
                # Should only read, not write
                assert mock_file().read.called
                # Should not write (append mode not opened)
                write_calls = [call for call in mock_file().method_calls if 'write' in str(call)]
                assert len(write_calls) == 0
    
    @patch('ethoscope_node.utils.network.get_private_ip_pattern')
    def test_uses_detected_ip_pattern(self, mock_get_pattern):
        """Test uses IP pattern from network detection."""
        mock_get_pattern.return_value = "172.16.*.*"
        
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = False
            
            with patch('builtins.open', mock_open()) as mock_file:
                with patch('os.chmod'):
                    _setup_system_ssh_config("/test/key/path")
                    
                    written_content = mock_file().write.call_args[0][0]
                    assert "Host 172.16.*.* ethoscope*" in written_content
    
    @patch('ethoscope_node.utils.network.get_private_ip_pattern')
    def test_sets_config_permissions(self, mock_get_pattern):
        """Test sets proper permissions on SSH config file."""
        mock_get_pattern.return_value = "192.168.1.*"
        
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = False
            
            with patch('builtins.open', mock_open()):
                with patch('os.chmod') as mock_chmod:
                    _setup_system_ssh_config("/test/key/path")
                    
                    # Should set 644 permissions (readable by all)
                    mock_chmod.assert_called_with("/etc/ssh/ssh_config", 0o644)
    
    @patch('ethoscope_node.utils.network.get_private_ip_pattern')
    def test_handles_permission_error(self, mock_get_pattern):
        """Test handles permission errors gracefully."""
        mock_get_pattern.return_value = "192.168.1.*"
        
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = False
            
            with patch('builtins.open') as mock_file:
                mock_file.side_effect = PermissionError("Permission denied")
                
                # Should not raise exception, just log warning
                _setup_system_ssh_config("/test/key/path")
    
    @patch('ethoscope_node.utils.network.get_private_ip_pattern')
    def test_includes_connection_settings(self, mock_get_pattern):
        """Test includes proper connection timeout and keepalive settings."""
        mock_get_pattern.return_value = "192.168.1.*"
        
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = False
            
            with patch('builtins.open', mock_open()) as mock_file:
                with patch('os.chmod'):
                    _setup_system_ssh_config("/test/key/path")
                    
                    written_content = mock_file().write.call_args[0][0]
                    assert "ConnectTimeout 10" in written_content
                    assert "ServerAliveInterval 30" in written_content
                    assert "ServerAliveCountMax 3" in written_content


