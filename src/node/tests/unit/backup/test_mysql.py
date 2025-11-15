"""
Unit tests for MySQL backup module.

Tests cover:
- DatabaseConnectionManager context manager
- BaseSQLConnector database operations (remote/local info retrieval, comparison)
- MySQLdbToSQLite initialization and setup
- Schema extraction and conversion (MySQL -> SQLite)
- Table creation with constraints and migration
- Incremental backup strategy (update_all_tables, _update_table_with_ID, _update_table_without_ID)
- Data type mapping and transformations
- Error handling and recovery
- get_backup_path_from_database function
- DBDiff comparison utilities
"""

import os
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock, Mock, call, patch

import mysql.connector
import pytest

from ethoscope_node.backup.mysql import (
    BaseSQLConnector,
    DatabaseConnectionManager,
    DBDiff,
    DBNotReadyError,
    MySQLdbToSQLite,
    get_backup_path_from_database,
)


class TestDatabaseConnectionManager:
    """Test DatabaseConnectionManager context manager for MySQL connections."""

    def test_connection_manager_initialization(self):
        """Test DatabaseConnectionManager initializes with correct parameters."""
        manager = DatabaseConnectionManager(
            host="192.168.1.100",
            user="ethoscope",
            password="ethoscope",
            database="test_db",
        )

        assert manager.connection_params["host"] == "192.168.1.100"
        assert manager.connection_params["user"] == "ethoscope"
        assert manager.connection_params["passwd"] == "ethoscope"
        assert manager.connection_params["db"] == "test_db"
        assert manager.connection_params["buffered"] is True
        assert manager.connection_params["charset"] == "latin1"
        assert manager.connection_params["connect_timeout"] == 45

    def test_connection_manager_no_database(self):
        """Test DatabaseConnectionManager without database parameter."""
        manager = DatabaseConnectionManager(
            host="localhost",
            user="root",
            password="password",
        )

        assert "db" not in manager.connection_params
        assert manager.connection_params["host"] == "localhost"

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_connection_manager_context_entry(self, mock_connect):
        """Test context manager __enter__ establishes connection."""
        mock_connection = Mock()
        mock_connect.return_value = mock_connection

        manager = DatabaseConnectionManager(
            host="localhost", user="test", password="test"
        )

        with manager as conn:
            assert conn is mock_connection
            mock_connect.assert_called_once()

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_connection_manager_context_exit_closes_connection(self, mock_connect):
        """Test context manager __exit__ closes connection properly."""
        mock_connection = Mock()
        mock_connect.return_value = mock_connection

        manager = DatabaseConnectionManager(
            host="localhost", user="test", password="test"
        )

        with manager:
            pass

        mock_connection.close.assert_called_once()

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_connection_manager_handles_exception(self, mock_connect):
        """Test context manager closes connection even on exception."""
        mock_connection = Mock()
        mock_connect.return_value = mock_connection

        manager = DatabaseConnectionManager(
            host="localhost", user="test", password="test"
        )

        try:
            with manager:
                raise ValueError("Test exception")
        except ValueError:
            pass

        mock_connection.close.assert_called_once()


class TestBaseSQLConnector:
    """Test BaseSQLConnector base class operations."""

    def test_base_sql_connector_initialization(self):
        """Test BaseSQLConnector initialization with default parameters."""
        connector = BaseSQLConnector(
            remote_host="192.168.1.100",
            remote_user="ethoscope",
            remote_pass="ethoscope",
            dst_path="/tmp/test.db",
            remote_db_name="ETHOSCOPE_001_db",
        )

        assert connector._remote_host == "192.168.1.100"
        assert connector._remote_user == "ethoscope"
        assert connector._remote_pass == "ethoscope"
        assert connector._dst_path == "/tmp/test.db"
        assert connector._remote_db_name == "ETHOSCOPE_001_db"

    def test_base_sql_connector_default_values(self):
        """Test BaseSQLConnector uses correct default values."""
        connector = BaseSQLConnector()

        assert connector._remote_host == "localhost"
        assert connector._remote_user == "ethoscope"
        assert connector._remote_pass == "ethoscope"
        assert connector._dst_path is None
        assert connector._remote_db_name is None

    def test_base_sql_connector_table_without_key_constant(self):
        """Test _TABLE_WITHOUT_KEY constant."""
        assert "ROI_MAP" in BaseSQLConnector._TABLE_WITHOUT_KEY
        assert "VAR_MAP" in BaseSQLConnector._TABLE_WITHOUT_KEY
        assert "METADATA" in BaseSQLConnector._TABLE_WITHOUT_KEY

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_get_remote_db_info_fast(self, mock_manager):
        """Test _get_remote_db_info using fast INFORMATION_SCHEMA method."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("METADATA", 10),
            ("VAR_MAP", 5),
            ("ROI_1", 1000),
        ]

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        connector = BaseSQLConnector()
        result = connector._get_remote_db_info()

        assert result["METADATA"] == 10
        assert result["VAR_MAP"] == 5
        assert result["ROI_1"] == 1000

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_get_remote_db_info_slow_with_regular_tables(self, mock_manager):
        """Test _get_remote_db_info_slow using direct queries for tables with IDs."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # First call returns list of databases and tables
        mock_cursor.fetchall.return_value = [
            ("ETHOSCOPE_001_db", "ROI_1"),
            ("ETHOSCOPE_001_db", "ROI_2"),
            ("ETHOSCOPE_001_db", "METADATA"),
        ]

        # Subsequent calls for max(id) queries
        mock_cursor.fetchone.side_effect = [(1000,), (2000,), (5,)]

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        connector = BaseSQLConnector()
        result = connector._get_remote_db_info_slow()

        assert result["ETHOSCOPE_001_db"]["ROI_1"] == 1000
        assert result["ETHOSCOPE_001_db"]["ROI_2"] == 2000
        assert result["ETHOSCOPE_001_db"]["METADATA"] == 5

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_get_remote_db_info_slow_handles_errors(self, mock_manager):
        """Test _get_remote_db_info_slow handles query errors gracefully."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            ("ETHOSCOPE_001_db", "GOOD_TABLE"),
            ("ETHOSCOPE_001_db", "BAD_TABLE"),
        ]

        def execute_side_effect(query, params=None):
            if "BAD_TABLE" in query:
                raise mysql.connector.Error("Table error")

        mock_cursor.execute.side_effect = execute_side_effect
        mock_cursor.fetchone.return_value = (100,)

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        connector = BaseSQLConnector()
        result = connector._get_remote_db_info_slow()

        # BAD_TABLE should have 0 count due to error
        assert result["ETHOSCOPE_001_db"]["BAD_TABLE"] == 0

    def test_get_local_db_info_empty_database(self, tmp_path):
        """Test _get_local_db_info with empty SQLite database."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        connector = BaseSQLConnector(dst_path=str(db_path))
        result = connector._get_local_db_info()

        assert result == {}

    def test_get_local_db_info_with_tables(self, tmp_path):
        """Test _get_local_db_info with populated SQLite database."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY)")
        cursor.execute("CREATE TABLE METADATA (field TEXT, value TEXT)")
        cursor.execute("INSERT INTO ROI_1 (id) VALUES (100)")
        cursor.execute("INSERT INTO METADATA VALUES ('test', 'value')")
        conn.commit()
        conn.close()

        connector = BaseSQLConnector(dst_path=str(db_path))
        result = connector._get_local_db_info()

        assert result["ROI_1"] == 100  # max(id)
        assert result["METADATA"] == 1  # count(*)

    def test_get_local_db_info_nonexistent_file(self):
        """Test _get_local_db_info with nonexistent database file."""
        connector = BaseSQLConnector(dst_path="/nonexistent/path.db")
        result = connector._get_local_db_info()

        assert result == {}

    def test_get_local_db_info_handles_query_errors(self, tmp_path):
        """Test _get_local_db_info handles query errors gracefully."""
        db_path = tmp_path / "test.db"

        # Create database with table that will cause issues
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER)")
        conn.commit()
        conn.close()

        connector = BaseSQLConnector(dst_path=str(db_path))

        # Mock sqlite3.connect to simulate query error
        with patch("ethoscope_node.backup.mysql.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = Mock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor

            mock_cursor.fetchall.return_value = [("test_table",)]
            mock_cursor.execute.side_effect = sqlite3.Error("Query error")

            result = connector._get_local_db_info()

            # Should return empty or handle gracefully
            assert isinstance(result, dict)

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_compare_databases_fast_mode(self, mock_manager, tmp_path):
        """Test compare_databases with fast mode enabled."""
        db_path = tmp_path / "test.db"

        # Create local database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO ROI_1 (id) VALUES (50)")
        conn.commit()
        conn.close()

        # Mock remote database info
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("ROI_1", 100)]

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        connector = BaseSQLConnector(dst_path=str(db_path))
        percentage = connector.compare_databases(use_fast_mode=True)

        # Local has 50, remote has 100 = 50% match
        assert percentage == 50.0

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_compare_databases_slow_mode(self, mock_manager, tmp_path):
        """Test compare_databases with slow mode (accurate)."""
        db_path = tmp_path / "test.db"

        # Create local database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO ROI_1 (id) VALUES (75)")
        conn.commit()
        conn.close()

        # Mock remote database info
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("ETHOSCOPE_001_db", "ROI_1")]
        mock_cursor.fetchone.return_value = (100,)

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        connector = BaseSQLConnector(
            dst_path=str(db_path), remote_db_name="ETHOSCOPE_001_db"
        )
        percentage = connector.compare_databases(use_fast_mode=False)

        # Local has 75, remote has 100 = 75% match
        assert percentage == 75.0

    def test_compare_databases_no_local_data(self):
        """Test compare_databases when local database doesn't exist."""
        connector = BaseSQLConnector(dst_path="/nonexistent/path.db")
        percentage = connector.compare_databases()

        assert percentage == -1

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_compare_databases_no_remote_data(self, mock_manager, tmp_path):
        """Test compare_databases when remote database is empty."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO ROI_1 (id) VALUES (100)")
        conn.commit()
        conn.close()

        # Mock empty remote database
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        connector = BaseSQLConnector(dst_path=str(db_path))
        percentage = connector.compare_databases(use_fast_mode=True)

        assert percentage == -1

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_compare_databases_local_exceeds_remote(self, mock_manager, tmp_path):
        """Test compare_databases when local has more data than remote."""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO ROI_1 (id) VALUES (150)")
        conn.commit()
        conn.close()

        # Mock remote database with less data
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("ROI_1", 100)]

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        connector = BaseSQLConnector(dst_path=str(db_path))
        percentage = connector.compare_databases(use_fast_mode=True)

        # Should log warning but still return percentage > 100
        assert percentage > 100.0


class TestGetBackupPathFromDatabase:
    """Test get_backup_path_from_database utility function."""

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_get_backup_path_success(self, mock_connect):
        """Test successful retrieval of backup path from database."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("ETHOSCOPE_001/ETHOSCOPE_001_db.db",)
        mock_connect.return_value = mock_connection

        result = get_backup_path_from_database("192.168.1.100", ethoscope_number=1)

        assert result == "ETHOSCOPE_001/ETHOSCOPE_001_db.db"
        mock_cursor.execute.assert_called_once()
        mock_cursor.close.assert_called_once()
        mock_connection.close.assert_called_once()

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_get_backup_path_from_hostname(self, mock_connect):
        """Test extracting database name from hostname."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("ETHOSCOPE_070/ETHOSCOPE_070_db.db",)
        mock_connect.return_value = mock_connection

        result = get_backup_path_from_database("ethoscope070.local")

        assert result == "ETHOSCOPE_070/ETHOSCOPE_070_db.db"
        # Should connect to ETHOSCOPE_070_db
        assert "ETHOSCOPE_070_db" in str(mock_connect.call_args)

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_get_backup_path_from_ip_address(self, mock_connect):
        """Test extracting database name from IP address."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("ETHOSCOPE_027/ETHOSCOPE_027_db.db",)
        mock_connect.return_value = mock_connection

        # IP 192.168.1.47 = ethoscope 27 (47 - 20)
        result = get_backup_path_from_database("192.168.1.47")

        assert result == "ETHOSCOPE_027/ETHOSCOPE_027_db.db"

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_get_backup_path_no_result(self, mock_connect):
        """Test handling when no backup_filename is found."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_connect.return_value = mock_connection

        # Should raise RuntimeError (which wraps ValueError)
        with pytest.raises(RuntimeError, match="Error querying METADATA"):
            get_backup_path_from_database("192.168.1.100", ethoscope_number=1)

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_get_backup_path_connection_error(self, mock_connect):
        """Test handling of database connection errors."""
        mock_connect.side_effect = mysql.connector.Error("Connection refused")

        with pytest.raises(ConnectionError, match="Failed to connect"):
            get_backup_path_from_database("192.168.1.100", ethoscope_number=1)

    @patch("ethoscope_node.backup.mysql.mysql.connector.connect")
    def test_get_backup_path_query_error(self, mock_connect):
        """Test handling of query execution errors."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Query failed")
        mock_connect.return_value = mock_connection

        with pytest.raises(RuntimeError, match="Error querying METADATA"):
            get_backup_path_from_database("192.168.1.100", ethoscope_number=1)


class TestMySQLdbToSQLite:
    """Test MySQLdbToSQLite main backup class."""

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    def test_mysql_to_sqlite_initialization(self, mock_setup, mock_init, tmp_path):
        """Test MySQLdbToSQLite initialization."""
        dst_path = str(tmp_path / "backup.db")

        backup = MySQLdbToSQLite(
            dst_path=dst_path,
            remote_db_name="ETHOSCOPE_001_db",
            remote_host="192.168.1.100",
            remote_user="ethoscope",
            remote_pass="ethoscope",
        )

        assert backup._dst_path == dst_path
        assert backup._remote_db_name == "ETHOSCOPE_001_db"
        assert backup._remote_host == "192.168.1.100"
        assert backup._dam_file_name == str(tmp_path / "backup.txt")

        mock_setup.assert_called_once()
        mock_init.assert_called_once()

    def test_setup_destination_creates_directories(self, tmp_path):
        """Test _setup_destination creates necessary directories."""
        dst_path = tmp_path / "subdir" / "nested" / "backup.db"

        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database"):
            MySQLdbToSQLite(dst_path=str(dst_path))

        # Directory should be created
        assert dst_path.parent.exists()

    def test_setup_destination_overwrite_removes_files(self, tmp_path):
        """Test _setup_destination removes existing files when overwrite=True."""
        dst_path = tmp_path / "backup.db"
        dam_path = tmp_path / "backup.txt"

        # Create existing files
        dst_path.touch()
        dam_path.touch()

        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database"):
            MySQLdbToSQLite(dst_path=str(dst_path), overwrite=True)

        # Files should be removed and recreated
        assert not dst_path.exists() or dst_path.stat().st_size == 0

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_initialize_database_copies_schema(self, mock_manager, tmp_path):
        """Test _initialize_database copies schema and static data."""
        dst_path = tmp_path / "backup.db"

        mock_mysql_conn = Mock()
        mock_cursor = Mock()
        mock_mysql_conn.cursor.return_value = mock_cursor

        # Mock VAR_MAP check
        mock_cursor.fetchone.return_value = (10,)
        # Mock SHOW TABLES
        mock_cursor.fetchall.return_value = [("METADATA",), ("VAR_MAP",)]

        mock_manager.return_value.__enter__ = Mock(return_value=mock_mysql_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination"):
            with patch(
                "ethoscope_node.backup.mysql.MySQLdbToSQLite._ensure_table_schema",
                return_value=True,
            ):
                MySQLdbToSQLite(dst_path=str(dst_path))

        assert os.path.exists(str(dst_path))

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_initialize_database_handles_db_not_ready(self, mock_manager, tmp_path):
        """Test _initialize_database raises DBNotReadyError when VAR_MAP is empty."""
        dst_path = tmp_path / "backup.db"

        mock_mysql_conn = Mock()
        mock_cursor = Mock()
        mock_mysql_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (0,)  # Empty VAR_MAP

        mock_manager.return_value.__enter__ = Mock(return_value=mock_mysql_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination"):
            with pytest.raises(DBNotReadyError):
                MySQLdbToSQLite(dst_path=str(dst_path))

    def test_convert_mysql_type_to_sqlite_integer_types(self):
        """Test _convert_mysql_type_to_sqlite handles integer types."""
        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination"):
            with patch(
                "ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database"
            ):
                backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        assert backup._convert_mysql_type_to_sqlite("int") == "INTEGER"
        assert backup._convert_mysql_type_to_sqlite("bigint") == "INTEGER"
        assert backup._convert_mysql_type_to_sqlite("smallint") == "INTEGER"
        assert backup._convert_mysql_type_to_sqlite("tinyint") == "INTEGER"

    def test_convert_mysql_type_to_sqlite_text_types(self):
        """Test _convert_mysql_type_to_sqlite handles text types."""
        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination"):
            with patch(
                "ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database"
            ):
                backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        assert backup._convert_mysql_type_to_sqlite("varchar(255)") == "TEXT"
        assert backup._convert_mysql_type_to_sqlite("text") == "TEXT"
        assert backup._convert_mysql_type_to_sqlite("char(10)") == "TEXT"

    def test_convert_mysql_type_to_sqlite_numeric_types(self):
        """Test _convert_mysql_type_to_sqlite handles numeric types."""
        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination"):
            with patch(
                "ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database"
            ):
                backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        assert backup._convert_mysql_type_to_sqlite("float") == "REAL"
        assert backup._convert_mysql_type_to_sqlite("double") == "REAL"
        assert backup._convert_mysql_type_to_sqlite("decimal(10,2)") == "REAL"

    def test_convert_mysql_type_to_sqlite_blob_type(self):
        """Test _convert_mysql_type_to_sqlite handles blob types."""
        with patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination"):
            with patch(
                "ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database"
            ):
                backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        assert backup._convert_mysql_type_to_sqlite("blob") == "BLOB"
        assert backup._convert_mysql_type_to_sqlite("longblob") == "BLOB"

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_get_mysql_table_schema_basic(self, mock_init, mock_setup):
        """Test _get_mysql_table_schema extracts schema correctly."""
        backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Mock SHOW COLUMNS result
        mock_cursor.fetchall.return_value = [
            ("id", "int(11)", "NO", "PRI", None, "auto_increment"),
            ("name", "varchar(255)", "YES", "", None, ""),
            ("value", "text", "YES", "", None, ""),
        ]

        schema = backup._get_mysql_table_schema("test_table", mock_conn)

        assert schema["primary_key"] == "id"
        assert schema["has_auto_increment"] is True
        assert len(schema["columns"]) == 3
        assert schema["columns"][0]["name"] == "id"
        assert schema["columns"][0]["type"] == "INTEGER"
        assert schema["columns"][0]["is_primary"] is True

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_get_mysql_table_schema_no_primary_key(self, mock_init, mock_setup):
        """Test _get_mysql_table_schema for table without primary key."""
        backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # METADATA table has no primary key
        mock_cursor.fetchall.return_value = [
            ("field", "varchar(255)", "YES", "", None, ""),
            ("value", "text", "YES", "", None, ""),
        ]

        schema = backup._get_mysql_table_schema("METADATA", mock_conn)

        assert schema["primary_key"] is None
        assert schema["has_auto_increment"] is False

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_create_table_with_constraints(self, mock_init, mock_setup, tmp_path):
        """Test _create_table_with_constraints creates table with PRIMARY KEY."""
        backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))

        schema = {
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "is_primary": True,
                    "null": False,
                    "default": None,
                },
                {
                    "name": "data",
                    "type": "TEXT",
                    "is_primary": False,
                    "null": True,
                    "default": None,
                },
            ],
            "primary_key": "id",
        }

        result = backup._create_table_with_constraints("test_table", conn, schema)
        conn.close()

        assert result is True

        # Verify table was created with PRIMARY KEY
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(test_table)")
        columns = cursor.fetchall()
        conn.close()

        # Check that id column is PRIMARY KEY
        id_column = [col for col in columns if col[1] == "id"][0]
        assert id_column[5] == 1  # pk flag

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_table_has_proper_constraints_true(self, mock_init, mock_setup, tmp_path):
        """Test _table_has_proper_constraints returns True for valid table."""
        backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, data TEXT)")
        conn.commit()

        expected_schema = {"primary_key": "id"}

        result = backup._table_has_proper_constraints(
            "test_table", conn, expected_schema
        )
        conn.close()

        assert result is True

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_table_has_proper_constraints_false(self, mock_init, mock_setup, tmp_path):
        """Test _table_has_proper_constraints returns False for table without PK."""
        backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE test_table (id INTEGER, data TEXT)"
        )  # No PRIMARY KEY
        conn.commit()

        expected_schema = {"primary_key": "id"}

        result = backup._table_has_proper_constraints(
            "test_table", conn, expected_schema
        )
        conn.close()

        assert result is False

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_migrate_table_schema_success(self, mock_init, mock_setup, tmp_path):
        """Test _migrate_table_schema successfully migrates table."""
        backup = MySQLdbToSQLite(dst_path="/tmp/test.db")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create old table without PRIMARY KEY
        cursor.execute("CREATE TABLE test_table (id INTEGER, data TEXT)")
        cursor.execute("INSERT INTO test_table VALUES (1, 'test1')")
        cursor.execute("INSERT INTO test_table VALUES (2, 'test2')")
        conn.commit()

        schema = {
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "is_primary": True,
                    "null": False,
                    "default": None,
                },
                {
                    "name": "data",
                    "type": "TEXT",
                    "is_primary": False,
                    "null": True,
                    "default": None,
                },
            ],
            "primary_key": "id",
        }

        result = backup._migrate_table_schema("test_table", conn, schema)
        conn.commit()
        conn.close()

        assert result is True

        # Verify data was preserved
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test_table ORDER BY id")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0] == (1, "test1")

    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_write_to_dam_file(self, mock_init, mock_setup, tmp_path):
        """Test _write_to_dam_file writes CSV data correctly."""
        dam_path = tmp_path / "test.txt"
        backup = MySQLdbToSQLite(dst_path=str(tmp_path / "test.db"))
        backup._dam_file_name = str(dam_path)

        batch = [
            (1, 100, 50, 25),
            (2, 200, 75, 30),
        ]

        backup._write_to_dam_file(batch)

        content = dam_path.read_text()
        lines = content.strip().split("\n")

        assert len(lines) == 2
        assert lines[0] == "1\t100\t50\t25"
        assert lines[1] == "2\t200\t75\t30"

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_update_table_with_id_incremental(
        self, mock_init, mock_setup, mock_manager, tmp_path
    ):
        """Test _update_table_with_ID performs incremental backup correctly."""
        db_path = tmp_path / "backup.db"
        backup = MySQLdbToSQLite(dst_path=str(db_path))

        # Create local database with existing data
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY, t INTEGER, data TEXT)"
        )
        cursor.execute("INSERT INTO ROI_1 VALUES (1, 100, 'old')")
        cursor.execute("INSERT INTO ROI_1 VALUES (2, 200, 'old')")
        conn.commit()

        # Mock MySQL connection and data
        mock_mysql_conn = Mock()
        mock_mysql_cursor = Mock()
        mock_mysql_conn.cursor.return_value = mock_mysql_cursor

        # Mock column description
        mock_mysql_cursor.description = [("id",), ("t",), ("data",)]

        # First fetch returns new rows (id > 2)
        mock_mysql_cursor.fetchall.side_effect = [
            [(3, 300, "new1"), (4, 400, "new2")],  # First batch
            [],  # Second batch (empty, stops iteration)
        ]

        # Mock ensure_table_schema
        with patch.object(backup, "_ensure_table_schema", return_value=True):
            backup._update_table_with_ID("ROI_1", mock_mysql_conn, conn)

        conn.commit()

        # Verify new data was added
        cursor.execute("SELECT COUNT(*) FROM ROI_1")
        count = cursor.fetchone()[0]
        assert count == 4

        cursor.execute("SELECT id, data FROM ROI_1 WHERE id > 2 ORDER BY id")
        new_rows = cursor.fetchall()
        assert new_rows[0] == (3, "new1")
        assert new_rows[1] == (4, "new2")

        conn.close()

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_update_table_without_id(
        self, mock_init, mock_setup, mock_manager, tmp_path
    ):
        """Test _update_table_without_ID performs row-by-row sync."""
        db_path = tmp_path / "backup.db"
        backup = MySQLdbToSQLite(dst_path=str(db_path))

        # Create local database with existing METADATA
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE METADATA (field TEXT, value TEXT)")
        cursor.execute("INSERT INTO METADATA VALUES ('existing', 'value')")
        conn.commit()

        # Mock MySQL connection and data
        mock_mysql_conn = Mock()
        mock_mysql_cursor = Mock()
        mock_mysql_conn.cursor.return_value = mock_mysql_cursor

        # Mock remote METADATA rows
        mock_mysql_cursor.fetchall.side_effect = [
            [("existing", "value"), ("new_field", "new_value")],  # Remote rows
            [("field",), ("value",)],  # DESCRIBE columns
        ]

        backup._update_table_without_ID("METADATA", mock_mysql_conn, conn)
        conn.commit()

        # Verify new row was added but existing row was not duplicated
        cursor.execute("SELECT COUNT(*) FROM METADATA")
        count = cursor.fetchone()[0]
        assert count == 2

        cursor.execute("SELECT field, value FROM METADATA WHERE field = 'new_field'")
        new_row = cursor.fetchone()
        assert new_row == ("new_field", "new_value")

        conn.close()

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._setup_destination")
    @patch("ethoscope_node.backup.mysql.MySQLdbToSQLite._initialize_database")
    def test_update_all_tables(self, mock_init, mock_setup, mock_manager, tmp_path):
        """Test update_all_tables orchestrates backup of all tables."""
        db_path = tmp_path / "backup.db"
        backup = MySQLdbToSQLite(dst_path=str(db_path))

        # Create local database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE METADATA (field TEXT, value TEXT)")
        cursor.execute("CREATE TABLE VAR_MAP (var_name TEXT, sql_type TEXT)")
        cursor.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY, data TEXT)")
        conn.commit()
        conn.close()

        # Mock MySQL connection
        mock_mysql_conn = Mock()
        mock_mysql_cursor = Mock()
        mock_mysql_conn.cursor.return_value = mock_mysql_cursor

        # Mock SHOW TABLES
        mock_mysql_cursor.fetchall.return_value = [
            ("METADATA",),
            ("VAR_MAP",),
            ("ROI_1",),
        ]

        mock_manager.return_value.__enter__ = Mock(return_value=mock_mysql_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        # Mock table update methods
        with patch.object(backup, "_update_table_without_ID") as mock_without_id:
            with patch.object(backup, "_update_table_with_ID") as mock_with_id:
                backup.update_all_tables()

        # Verify table-specific methods were called
        assert mock_without_id.call_count == 2  # METADATA, VAR_MAP
        assert mock_with_id.call_count == 1  # ROI_1


class TestDBDiff:
    """Test DBDiff database comparison utilities."""

    def test_dbdiff_initialization(self):
        """Test DBDiff initialization."""
        diff = DBDiff(
            db_name="ETHOSCOPE_001_db",
            remote_host="192.168.1.100",
            filename="/tmp/backup.db",
        )

        assert diff._remote_db_name == "ETHOSCOPE_001_db"
        assert diff._remote_host == "192.168.1.100"
        assert diff._dst_path == "/tmp/backup.db"

    @patch("ethoscope_node.backup.mysql.DatabaseConnectionManager")
    def test_dbdiff_compare_databases(self, mock_manager, tmp_path):
        """Test DBDiff can compare databases using inherited method."""
        db_path = tmp_path / "backup.db"

        # Create local database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO ROI_1 (id) VALUES (80)")
        conn.commit()
        conn.close()

        # Mock remote database - need to handle nested context manager calls
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # First call gets database list, second call gets table info
        mock_cursor.fetchall.side_effect = [
            [("ETHOSCOPE_001_db", "ROI_1")],  # Database and table list
        ]
        mock_cursor.fetchone.return_value = (100,)  # max(id) for ROI_1

        mock_manager.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_manager.return_value.__exit__ = Mock(return_value=None)

        diff = DBDiff(
            db_name="ETHOSCOPE_001_db",
            remote_host="192.168.1.100",
            filename=str(db_path),
        )

        # Use slow mode for more predictable behavior
        percentage = diff.compare_databases(use_fast_mode=False)

        # 80/100 = 80% match
        assert percentage == 80.0
