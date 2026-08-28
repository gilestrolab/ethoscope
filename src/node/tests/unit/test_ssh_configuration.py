"""
Unit tests for SSH configuration setup functionality.

Tests the SSH key generation and system-wide SSH configuration
setup used for ethoscope device connections.
"""

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, call, mock_open, patch

import pytest

from ethoscope_node.utils.configuration import (
    SSH_KEYS_DIR_MODE,
    SSH_PRIVATE_KEY_MODE,
    SSH_PUBLIC_KEY_MODE,
    ConfigurationError,
    _setup_system_ssh_config,
    ensure_ssh_keys,
    get_ssh_key_paths,
)


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

            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch(
                    "ethoscope_node.utils.configuration._setup_system_ssh_config"
                ):
                    ensure_ssh_keys(keys_dir)

                assert os.path.exists(keys_dir)
                # Group-readable (drwxr-x---): the node advertises this key to
                # every user on the machine via /etc/ssh/ssh_config.
                stat_info = os.stat(keys_dir)
                assert stat.S_IMODE(stat_info.st_mode) == SSH_KEYS_DIR_MODE

    def test_returns_existing_keys(self):
        """Test returns paths to existing keys without regenerating."""
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = temp_dir
            private_key = os.path.join(keys_dir, "id_rsa")
            public_key = os.path.join(keys_dir, "id_rsa.pub")

            # Create dummy key files
            Path(private_key).touch()
            Path(public_key).touch()

            with patch("subprocess.run") as mock_run:
                private_path, public_path = ensure_ssh_keys(keys_dir)

                # Should not call ssh-keygen if keys exist
                mock_run.assert_not_called()
                assert private_path == private_key
                assert public_path == public_key

    @patch("socket.gethostname")
    @patch("subprocess.run")
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

            with patch("ethoscope_node.utils.configuration._setup_system_ssh_config"):
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

    @patch("subprocess.run")
    def test_sets_key_permissions(self, mock_run):
        """Test sets group-readable permissions on generated keys."""

        def mock_subprocess_run(cmd, **kwargs):
            # ssh-keygen is mocked, so stand in for the files it would write:
            # the permissions are applied to real paths, not to mock calls.
            if cmd[0] == "ssh-keygen":
                private_key = cmd[cmd.index("-f") + 1]
                Path(private_key).touch()
                Path(private_key + ".pub").touch()
            return Mock(stdout="Generated key", stderr="")

        mock_run.side_effect = mock_subprocess_run

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("ethoscope_node.utils.configuration._setup_system_ssh_config"):
                private_path, public_path = ensure_ssh_keys(temp_dir)

            assert stat.S_IMODE(os.stat(private_path).st_mode) == SSH_PRIVATE_KEY_MODE
            assert stat.S_IMODE(os.stat(public_path).st_mode) == SSH_PUBLIC_KEY_MODE
            # The private key must not be world-readable whatever else changes.
            assert not stat.S_IMODE(os.stat(private_path).st_mode) & stat.S_IROTH

    @patch("subprocess.run")
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

            with patch(
                "ethoscope_node.utils.configuration._setup_system_ssh_config"
            ) as mock_setup:
                ensure_ssh_keys(keys_dir)

                # Should call SSH config setup with private key path
                mock_setup.assert_called_once()
                private_key_path = os.path.join(keys_dir, "id_rsa")
                mock_setup.assert_called_with(private_key_path)

    @patch("subprocess.run")
    def test_handles_ssh_keygen_failure(self, mock_run):
        """Test handles ssh-keygen command failure."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "ssh-keygen", stderr="Key generation failed"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = temp_dir

            with pytest.raises(ConfigurationError) as exc_info:
                ensure_ssh_keys(keys_dir)

            assert "Failed to generate SSH keys" in str(exc_info.value)

    def test_handles_permission_error(self):
        """Test handles permission errors when creating keys directory."""
        # Try to create keys in a directory we can't write to
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")

            with pytest.raises(ConfigurationError) as exc_info:
                ensure_ssh_keys("/root/test_keys")

            assert "Permission denied creating SSH keys" in str(exc_info.value)


class TestSetupSystemSshConfig:
    """Test system SSH configuration setup."""

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_creates_new_config_file(self, mock_get_pattern):
        """Test creates new SSH config file when none exists."""
        mock_get_pattern.return_value = "192.168.1.*"

        with tempfile.TemporaryDirectory() as temp_dir:
            os.path.join(temp_dir, "ssh_config")
            private_key_path = "/etc/ethoscope/keys/id_rsa"

            with patch(
                "ethoscope_node.utils.configuration.os.path.exists"
            ) as mock_exists:
                mock_exists.return_value = False

                with patch("builtins.open", mock_open()) as mock_file:
                    with patch("os.chmod"):
                        _setup_system_ssh_config(private_key_path)

                        # Should create new file
                        mock_file.assert_called_once()
                        written_content = mock_file().write.call_args[0][0]

                        assert "# Ethoscope SSH configuration" in written_content
                        assert "Host 192.168.1.* ethoscope*" in written_content
                        assert "User ethoscope" in written_content
                        assert "StrictHostKeyChecking no" in written_content
                        assert f"IdentityFile {private_key_path}" in written_content

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_appends_to_existing_config(self, mock_get_pattern):
        """Test appends to existing SSH config file."""
        mock_get_pattern.return_value = "10.0.*.*"
        existing_content = "# Existing SSH config\nHost example.com\n    User test\n"

        with patch("builtins.open", mock_open(read_data=existing_content)) as mock_file:
            with patch("os.path.exists") as mock_exists:
                mock_exists.return_value = True

                with patch("os.chmod"):
                    _setup_system_ssh_config("/test/key/path")

                    # Should read existing file first, then append
                    assert mock_file().read.called
                    assert mock_file().write.called

                    written_content = mock_file().write.call_args[0][0]
                    assert "# Ethoscope SSH configuration" in written_content
                    assert "Host 10.0.*.* ethoscope*" in written_content

    @staticmethod
    def _rendered_block(ip_pattern, key_path):
        """The stanza _setup_system_ssh_config writes, as a string."""
        with patch(
            "ethoscope_node.utils.network.get_private_ip_pattern",
            return_value=ip_pattern,
        ):
            with patch("os.path.exists", return_value=False):
                with patch("builtins.open", mock_open()) as mock_file:
                    with patch("os.chmod"):
                        _setup_system_ssh_config(key_path)
        return mock_file().write.call_args[0][0]

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_skips_if_config_is_current(self, mock_get_pattern):
        """An identical stanza is left alone."""
        mock_get_pattern.return_value = "192.168.1.*"
        existing_content = "# Existing\nHost example.com\n\n" + self._rendered_block(
            "192.168.1.*", "/test/key/path"
        )

        with patch("builtins.open", mock_open(read_data=existing_content)) as mock_file:
            with patch("os.path.exists") as mock_exists:
                mock_exists.return_value = True

                _setup_system_ssh_config("/test/key/path")

                # Should only read, not write
                assert mock_file().read.called
                # Should not write (append mode not opened)
                write_calls = [
                    call for call in mock_file().method_calls if "write" in str(call)
                ]
                assert len(write_calls) == 0

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_refreshes_stale_key_path(self, mock_get_pattern):
        """A stanza naming a key path that has since moved is rewritten."""
        mock_get_pattern.return_value = "192.168.1.*"
        # The shape written before the end marker existed, naming the old
        # pre-config-move key location.
        existing_content = (
            "Host example.com\n    User test\n"
            "\n# Ethoscope SSH configuration\n"
            "Host 192.168.1.* ethoscope*\n"
            "     User ethoscope\n"
            "     IdentityFile /etc/ethoscope/keys/id_rsa\n"
            "     ConnectTimeout 10\n"
            "\nHost after.example.com\n    User later\n"
        )

        with patch("builtins.open", mock_open(read_data=existing_content)) as mock_file:
            with patch("os.path.exists") as mock_exists:
                mock_exists.return_value = True
                with patch("os.chmod"):
                    _setup_system_ssh_config("/ethoscope_data/config/keys/id_rsa")

        written = mock_file().write.call_args[0][0]
        assert "IdentityFile /ethoscope_data/config/keys/id_rsa" in written
        assert "/etc/ethoscope/keys/id_rsa" not in written
        # Exactly one stanza left, and the neighbouring hosts survive.
        assert written.count("# Ethoscope SSH configuration") == 1
        assert "Host example.com" in written
        assert "Host after.example.com" in written

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_uses_detected_ip_pattern(self, mock_get_pattern):
        """Test uses IP pattern from network detection."""
        mock_get_pattern.return_value = "172.16.*.*"

        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False

            with patch("builtins.open", mock_open()) as mock_file:
                with patch("os.chmod"):
                    _setup_system_ssh_config("/test/key/path")

                    written_content = mock_file().write.call_args[0][0]
                    assert "Host 172.16.*.* ethoscope*" in written_content

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_sets_config_permissions(self, mock_get_pattern):
        """Test sets proper permissions on SSH config file."""
        mock_get_pattern.return_value = "192.168.1.*"

        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False

            with patch("builtins.open", mock_open()):
                with patch("os.chmod") as mock_chmod:
                    _setup_system_ssh_config("/test/key/path")

                    # Should set 644 permissions (readable by all)
                    mock_chmod.assert_called_with("/etc/ssh/ssh_config", 0o644)

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_handles_permission_error(self, mock_get_pattern):
        """Test handles permission errors gracefully."""
        mock_get_pattern.return_value = "192.168.1.*"

        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False

            with patch("builtins.open") as mock_file:
                mock_file.side_effect = PermissionError("Permission denied")

                # Should not raise exception, just log warning
                _setup_system_ssh_config("/test/key/path")

    @patch("ethoscope_node.utils.network.get_private_ip_pattern")
    def test_includes_connection_settings(self, mock_get_pattern):
        """Test includes proper connection timeout and keepalive settings."""
        mock_get_pattern.return_value = "192.168.1.*"

        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False

            with patch("builtins.open", mock_open()) as mock_file:
                with patch("os.chmod"):
                    _setup_system_ssh_config("/test/key/path")

                    written_content = mock_file().write.call_args[0][0]
                    assert "ConnectTimeout 10" in written_content
                    assert "ServerAliveInterval 30" in written_content
                    assert "ServerAliveCountMax 3" in written_content


class TestGetSshKeyPaths:
    """The accessor must hand out paths without rewriting permissions."""

    @staticmethod
    def _make_key_pair(keys_dir):
        """Create a dummy key pair with deliberately loosened permissions."""
        private_key = Path(keys_dir) / "id_rsa"
        public_key = Path(keys_dir) / "id_rsa.pub"
        private_key.touch()
        public_key.touch()
        os.chmod(keys_dir, 0o755)
        os.chmod(private_key, 0o644)
        return private_key, public_key

    def test_existing_keys_are_left_exactly_as_they_are(self):
        """
        Regression: the backup loop and the scanner call this every few minutes.

        They used to call ensure_ssh_keys(), whose "verify permissions" branch
        re-applied the modes on every call, so an admin who deliberately
        loosened the key to share it with other accounts on the node saw it
        clamped back within minutes.
        """
        with tempfile.TemporaryDirectory() as keys_dir:
            private_key, _ = self._make_key_pair(keys_dir)

            with patch("os.chmod") as mock_chmod:
                with patch("os.chown") as mock_chown:
                    returned_private, returned_public = get_ssh_key_paths(keys_dir)

            mock_chmod.assert_not_called()
            mock_chown.assert_not_called()
            assert returned_private == str(private_key)
            assert returned_public == str(private_key) + ".pub"
            # And the loosened modes really did survive the call.
            assert stat.S_IMODE(os.stat(private_key).st_mode) == 0o644
            assert stat.S_IMODE(os.stat(keys_dir).st_mode) == 0o755

    @patch("subprocess.run")
    def test_missing_keys_are_generated_once(self, mock_run):
        """With no key pair present, fall through to the full setup."""

        def mock_subprocess_run(cmd, **kwargs):
            if cmd[0] == "ssh-keygen":
                private_key = cmd[cmd.index("-f") + 1]
                Path(private_key).touch()
                Path(private_key + ".pub").touch()
            return Mock(stdout="Generated key", stderr="")

        mock_run.side_effect = mock_subprocess_run

        with tempfile.TemporaryDirectory() as temp_dir:
            keys_dir = os.path.join(temp_dir, "keys")
            with patch("ethoscope_node.utils.configuration._setup_system_ssh_config"):
                private_path, public_path = get_ssh_key_paths(keys_dir)

            assert os.path.exists(private_path)
            assert stat.S_IMODE(os.stat(private_path).st_mode) == SSH_PRIVATE_KEY_MODE
            assert stat.S_IMODE(os.stat(public_path).st_mode) == SSH_PUBLIC_KEY_MODE


class TestSshKeyModes:
    """The modes themselves, independently of any filesystem."""

    def test_private_key_is_not_readable_beyond_its_owner(self):
        """OpenSSH refuses to load a key with any group or other bit set."""
        assert SSH_PRIVATE_KEY_MODE & 0o077 == 0

    def test_group_can_reach_the_directory_and_public_key(self):
        """The half of the sharing that ssh does allow stays in place."""
        assert SSH_KEYS_DIR_MODE & 0o050 == 0o050
        assert SSH_PUBLIC_KEY_MODE & 0o040 == 0o040


class TestSshKeyGroup:
    """Group ownership of the key material."""

    @staticmethod
    def _existing_pair(keys_dir):
        """Put a key pair in place so ensure_ssh_keys takes the existing path."""
        Path(keys_dir, "id_rsa").touch()
        Path(keys_dir, "id_rsa.pub").touch()

    def test_configured_group_is_applied_to_dir_and_keys(self, monkeypatch):
        """The group named by ETHOSCOPE_SSH_KEY_GROUP gets read access."""
        monkeypatch.setenv("ETHOSCOPE_SSH_KEY_GROUP", "labgroup")

        fake_group = Mock(gr_gid=4242)
        with tempfile.TemporaryDirectory() as keys_dir:
            self._existing_pair(keys_dir)

            with patch("grp.getgrnam", return_value=fake_group) as mock_getgrnam:
                with patch("os.chown") as mock_chown:
                    ensure_ssh_keys(keys_dir)

            mock_getgrnam.assert_called_once_with("labgroup")
            # Directory and both keys, with the user half left alone (-1).
            assert mock_chown.call_count == 3
            for chown_call in mock_chown.call_args_list:
                assert chown_call[0][1] == -1
                assert chown_call[0][2] == 4242

    def test_missing_group_warns_but_still_sets_modes(self, caplog, monkeypatch):
        """An absent group must not break the node, just say what to do."""
        monkeypatch.setenv("ETHOSCOPE_SSH_KEY_GROUP", "nosuchgroup")

        with tempfile.TemporaryDirectory() as keys_dir:
            self._existing_pair(keys_dir)

            with patch("grp.getgrnam", side_effect=KeyError("nosuchgroup")):
                with patch("os.chown") as mock_chown:
                    private_path, _ = ensure_ssh_keys(keys_dir)

            mock_chown.assert_not_called()
            assert stat.S_IMODE(os.stat(private_path).st_mode) == SSH_PRIVATE_KEY_MODE
            assert "nosuchgroup" in caplog.text
            assert "groupadd" in caplog.text

    def test_unprivileged_group_change_is_not_fatal(self, monkeypatch):
        """Without root the group cannot be set; the node carries on anyway."""
        monkeypatch.setenv("ETHOSCOPE_SSH_KEY_GROUP", "labgroup")

        with tempfile.TemporaryDirectory() as keys_dir:
            self._existing_pair(keys_dir)

            with patch("grp.getgrnam", return_value=Mock(gr_gid=4242)):
                with patch("os.chown", side_effect=PermissionError("not root")):
                    private_path, public_path = ensure_ssh_keys(keys_dir)

            assert private_path == os.path.join(keys_dir, "id_rsa")
            assert stat.S_IMODE(os.stat(public_path).st_mode) == SSH_PUBLIC_KEY_MODE
