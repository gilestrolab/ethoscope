"""
MySQL Backup Module - Low-level Database Operations

This module handles the core database operations for backing up MySQL data to SQLite files.
It provides the fundamental database connectivity, schema management, and data transfer 
functionality that powers the ethoscope backup system.

Key Responsibilities:
====================

1. DATABASE CONNECTIVITY & MANAGEMENT:
   - Establishes and manages MySQL connections to remote ethoscope devices
   - Creates and manages local SQLite backup files
   - Handles database schema replication from MySQL to SQLite
   - Provides connection pooling and timeout management

2. INCREMENTAL DATA SYNCHRONIZATION:
   - Implements max(id) based incremental backup strategy to avoid data duplication
   - Synchronizes ROI tables (ROI_0, ROI_1, etc.) with new tracking data
   - Updates auxiliary tables (CSV_DAM_ACTIVITY, START_EVENTS, IMG_SNAPSHOTS, SENSORS)
   - Maintains data integrity during incremental updates

3. DATA INTEGRITY & VALIDATION:
   - Compares local vs remote database contents to verify backup completeness
   - Detects potential data duplication issues (when local > remote)
   - Provides fast and slow comparison modes for different accuracy needs
   - Handles schema conversion between MySQL and SQLite data types

4. LOW-LEVEL TABLE OPERATIONS:
   - Copies complete table schemas and static reference data (METADATA, VAR_MAP, ROI_MAP)
   - Performs batched data transfers to optimize memory usage and performance
   - Handles special table types (IMG_SNAPSHOTS with BLOB data, CSV_DAM_ACTIVITY with file export)
   - Manages table recreation when local schema is outdated

Classes:
========
- DatabaseConnectionManager: Context manager for MySQL connections
- BaseSQLConnector: Base class providing common database operations
- MySQLdbToSQLite: Main backup class handling MySQL→SQLite replication
- DBDiff: Database comparison utilities

This module is used by backups_helpers.py for the actual backup orchestration.
"""

import mysql.connector
import sqlite3
import os
import logging
import contextlib
import time
from typing import Dict, Optional, Any, Tuple
import threading

SQL_CHARSET = 'latin1'

class DBNotReadyError(Exception):
    pass

class DatabaseConnectionManager:
    """Context manager for database connections with proper cleanup."""
    
    def __init__(self, host: str, user: str, password: str, database: str = None):
        self.connection_params = {
            'host': host,
            'user': user,
            'passwd': password,
            'buffered': True,
            'charset': SQL_CHARSET,
            'collation': 'latin1_swedish_ci',
            'use_unicode': True,
            'connect_timeout': 45
        }
        if database:
            self.connection_params['db'] = database
    
    def __enter__(self):
        self.connection = mysql.connector.connect(**self.connection_params)
        return self.connection
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()

class BaseSQLConnector:
    """
    Base class for SQL operations with improved error handling and resource management.
    """

    _TABLE_WITHOUT_KEY = ["ROI_MAP", "VAR_MAP", "METADATA"]
    
    def __init__(self, remote_host: str = "localhost", remote_user: str = "ethoscope", 
                 remote_pass: str = "ethoscope", dst_path: str = None, 
                 remote_db_name: str = None):
        self._remote_host = remote_host
        self._remote_user = remote_user
        self._remote_pass = remote_pass
        self._dst_path = dst_path
        self._remote_db_name = remote_db_name
        self._lock = threading.RLock()
    
    def _get_remote_db_info(self) -> Dict[str, int]:
        """Fast method using INFORMATION_SCHEMA (may be inaccurate with InnoDB)."""
        with DatabaseConnectionManager(self._remote_host, self._remote_user, self._remote_pass):
            with DatabaseConnectionManager(self._remote_host, self._remote_user, self._remote_pass) as conn:
                cursor = conn.cursor(buffered=True)
                query = """
                    SELECT table_name, table_rows 
                    FROM INFORMATION_SCHEMA.tables 
                    WHERE table_schema LIKE %s
                """
                cursor.execute(query, ("ETHOSCOPE%",))
                tables = cursor.fetchall()
                return {table_name: row_count for table_name, row_count in tables}
    
    def _get_remote_db_info_slow(self) -> Dict[str, Dict[str, int]]:
        """Accurate method using direct table queries."""
        with DatabaseConnectionManager(self._remote_host, self._remote_user, self._remote_pass) as conn:
            cursor = conn.cursor(buffered=True)
            
            # Get all ETHOSCOPE databases and their tables
            query = """
                SELECT TABLE_SCHEMA, TABLE_NAME 
                FROM information_schema.tables 
                WHERE TABLE_SCHEMA LIKE %s
            """
            cursor.execute(query, ("ETHOSCOPE%",))
            tables = cursor.fetchall()
            
            # Group by database
            db_info = {}
            for db_name, table_name in tables:
                if db_name not in db_info:
                    db_info[db_name] = {}
                
                # Choose appropriate count method based on table type
                if table_name in self._TABLE_WITHOUT_KEY:
                    query = "SELECT COUNT(*) FROM `{}`.`{}`".format(db_name, table_name)
                else:
                    query = "SELECT COALESCE(MAX(id), 0) FROM `{}`.`{}`".format(db_name, table_name)
                
                try:
                    cursor.execute(query)
                    result = cursor.fetchone()
                    db_info[db_name][table_name] = result[0] if result and result[0] is not None else 0
                except mysql.connector.Error as e:
                    logging.warning(f"Error querying table {db_name}.{table_name}: {e}")
                    db_info[db_name][table_name] = 0
            
            return db_info
    
    def _get_local_db_info(self) -> Dict[str, int]:
        """Get information about local SQLite database."""
        if not os.path.exists(self._dst_path):
            logging.error(f"No db file at {self._dst_path}")
            return {}
        
        try:
            with sqlite3.connect(self._dst_path, timeout=10.0) as conn:
                cursor = conn.cursor()
                
                # Get all non-system tables
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """)
                tables = cursor.fetchall()
                
                table_info = {}
                for (table_name,) in tables:
                    try:
                        if table_name not in self._TABLE_WITHOUT_KEY:
                            cursor.execute("SELECT COALESCE(MAX(id), 0) FROM `{}`".format(table_name))
                        else:
                            cursor.execute("SELECT COUNT(*) FROM `{}`".format(table_name))
                        
                        result = cursor.fetchone()
                        table_info[table_name] = result[0] if result and result[0] is not None else 0
                    except sqlite3.Error as e:
                        logging.warning(f"Error querying local table {table_name}: {e}")
                        table_info[table_name] = 0
                
                return table_info
                
        except sqlite3.Error as e:
            logging.error(f"SQLite error: {e}")
            return {}
    
    def compare_databases(self, use_fast_mode: bool = False) -> float:
        """
        Compare remote and local databases.
        Returns percentage match (0-100) or -1 for errors.
        """
        try:
            # Get remote database info
            if use_fast_mode:
                remote_info = self._get_remote_db_info()
                # Convert to nested dict format for consistency
                if self._remote_db_name:
                    remote_tables_info = {self._remote_db_name: remote_info}
                else:
                    remote_tables_info = {"default": remote_info}
            else:
                remote_tables_info = self._get_remote_db_info_slow()
            
            # Get local database info
            local_tables_info = self._get_local_db_info()
            
            if not local_tables_info:
                return -1
            
            # Get all unique table names from both remote and local
            if use_fast_mode:
                remote_tables = set(remote_tables_info.get("default", {}).keys())
            else:
                db_name = self._remote_db_name or list(remote_tables_info.keys())[0]
                remote_tables = set(remote_tables_info.get(db_name, {}).keys())
            
            local_tables = set(local_tables_info.keys())
            all_tables = remote_tables.union(local_tables)
            
            total_remote = 0
            total_local = 0
            
            for table_name in all_tables:
                # Get remote count
                remote_count = 0
                if use_fast_mode:
                    remote_count = remote_tables_info.get("default", {}).get(table_name, 0)
                else:
                    db_name = self._remote_db_name or list(remote_tables_info.keys())[0]
                    remote_count = remote_tables_info.get(db_name, {}).get(table_name, 0)
                
                # Get local count
                local_count = local_tables_info.get(table_name, 0)
                
                if remote_count is None:
                    remote_count = 0
                if local_count is None:
                    local_count = 0
                
                total_remote += int(remote_count)
                total_local += int(local_count)
            
            if total_remote == 0:
                return -1
            
            # Calculate match percentage
            match_percentage = (total_local / total_remote) * 100
            
            # Log warning if local exceeds remote (indicates duplicate data issue)
            if match_percentage > 100.0:
                logging.warning(f"Local database has more records than remote ({match_percentage:.2f}% - this may indicate duplicate data)")
            
            return match_percentage
            
        except Exception as e:
            logging.error(f"Error comparing databases: {e}")
            return -1

def get_backup_path_from_database(host, ethoscope_number=None):
    """Connect directly to ethoscope's database and get backup filename from METADATA table."""
    logging.info(f"Querying METADATA table directly from {host}...")
    
    # Determine database name - try to extract from host or use provided number
    db_name = "ethoscope_db"  # Default fallback
    
    if ethoscope_number is not None:
        db_name = f"ETHOSCOPE_{ethoscope_number:03d}_db"
        logging.info(f"Using database name from ethoscope number: {db_name}")
    elif host:
        # Try to extract ethoscope number from hostname or IP
        import re
        # Look for ethoscope number in hostname like "ethoscope070.local"
        hostname_match = re.search(r'ethoscope(\d+)', host)
        if hostname_match:
            number = int(hostname_match.group(1))
            db_name = f"ETHOSCOPE_{number:03d}_db"
            logging.info(f"Extracted database name from hostname: {db_name}")
        # Look for ethoscope number in IP like 192.168.1.27 (where 27 = 20 + 007)
        elif re.match(r'192\.168\.1\.(\d+)', host):
            ip_match = re.match(r'192\.168\.1\.(\d+)', host)
            ip_last_octet = int(ip_match.group(1))
            if ip_last_octet >= 21:  # Standard ethoscope IP range starts at .21
                ethoscope_num = ip_last_octet - 20
                db_name = f"ETHOSCOPE_{ethoscope_num:03d}_db"
                logging.info(f"Extracted database name from IP: {db_name}")
    
    try:
        # Connect to ethoscope's MariaDB database
        connection = mysql.connector.connect(
            host=host,
            port=3306,
            user='node',
            password='node',
            database=db_name,
            connect_timeout=10,
            autocommit=True,
            charset='utf8mb4',
            collation='utf8mb4_general_ci'
        )
        
        cursor = connection.cursor()
        
        # Query METADATA table for backup filename
        cursor.execute("SELECT DISTINCT value FROM METADATA WHERE field = 'backup_filename' AND value IS NOT NULL")
        result = cursor.fetchone()
        
        if result and result[0]:
            backup_filename = result[0]
            logging.info(f"Found backup filename from {host}: {backup_filename}")
            return backup_filename
        else:
            raise ValueError(f"No backup_filename found in METADATA table on {host}")
            
    except mysql.connector.Error as e:
        raise ConnectionError(f"Failed to connect to database on {host}: {e}")
    except Exception as e:
        raise RuntimeError(f"Error querying METADATA table on {host}: {e}")
    finally:
        try:
            if 'cursor' in locals():
                cursor.close()
            if 'connection' in locals():
                connection.close()
        except:
            pass

class MySQLdbToSQLite(BaseSQLConnector):
    """Optimized MySQL to SQLite backup class."""
    
    MAX_BATCH_SIZE = 10000
    
    def __init__(self, dst_path: str, remote_db_name: str = "ethoscope_db",
                 remote_host: str = "localhost", remote_user: str = "ethoscope",
                 remote_pass: str = "ethoscope", overwrite: bool = False):
        
        super().__init__(remote_host=remote_host, remote_user=remote_user,
                        remote_pass=remote_pass, dst_path=dst_path,
                        remote_db_name=remote_db_name)
        
        self._dam_file_name = os.path.splitext(dst_path)[0] + ".txt"
        
        # Setup destination
        self._setup_destination(overwrite)
        
        # Initialize database structure
        self._initialize_database()
    
    def _setup_destination(self, overwrite: bool):
        """Setup destination files and directories."""
        if overwrite:
            for file_path in [self._dst_path, self._dam_file_name]:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logging.info(f"Removed existing file: {file_path}")
                except OSError as e:
                    logging.warning(f"Could not remove {file_path}: {e}")
        
        # Create directory structure
        os.makedirs(os.path.dirname(self._dst_path), exist_ok=True)
        
        # Ensure DAM file exists
        with open(self._dam_file_name, 'a'):
            pass
    
    def _initialize_database(self):
        """Initialize the SQLite database with remote schema."""
        try:
            with DatabaseConnectionManager(self._remote_host, self._remote_user, 
                                         self._remote_pass, self._remote_db_name) as mysql_conn:
                with sqlite3.connect(self._dst_path, timeout=30.0) as sqlite_conn:
                    self._copy_schema_and_static_data(mysql_conn, sqlite_conn)
        except mysql.connector.Error as e:
            logging.error(f"MySQL connection error during initialization: {e}")
            raise
        except sqlite3.Error as e:
            logging.error(f"SQLite error during initialization: {e}")
            raise


    def _copy_schema_and_static_data(self, mysql_conn, sqlite_conn):
        """Copy database schema and static data."""
        mysql_cursor = mysql_conn.cursor(buffered=True)
        
        # Check if database is ready
        mysql_cursor.execute("SELECT COUNT(*) FROM VAR_MAP")
        if mysql_cursor.fetchone()[0] == 0:
            raise DBNotReadyError("No data available in VAR_MAP table")
        
        # Get all tables
        mysql_cursor.execute("SHOW TABLES")
        tables = [row[0] for row in mysql_cursor.fetchall()]
        
        for table_name in tables:
            if not self._ensure_table_schema(table_name, mysql_conn, sqlite_conn):
                logging.error(f"Failed to create/verify table schema for {table_name}")
                return

    def _ensure_table_schema(self, table_name: str, mysql_conn, sqlite_conn) -> bool:
        """
        Ensure SQLite table exists with proper schema including PRIMARY KEY constraints.
        Handles both new table creation and migration of existing tables.
        """
        mysql_cursor = mysql_conn.cursor(buffered=True)
        sqlite_cursor = sqlite_conn.cursor()
        
        try:
            # Get the correct MySQL schema with constraints
            table_schema = self._get_mysql_table_schema(table_name, mysql_conn)
            if not table_schema:
                logging.error(f"Could not retrieve schema for table {table_name}")
                return False
            
            # Check if table exists in SQLite
            sqlite_cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            table_exists = sqlite_cursor.fetchone() is not None
            
            if table_exists:
                # Check if existing table has proper constraints
                if self._table_has_proper_constraints(table_name, sqlite_conn, table_schema):
                    logging.debug(f"Table {table_name} already exists with proper constraints")
                    return True
                else:
                    # Need to migrate existing table
                    logging.info(f"Table {table_name} exists but lacks proper constraints, migrating...")
                    return self._migrate_table_schema(table_name, sqlite_conn, table_schema)
            else:
                # Create new table with proper constraints
                logging.debug(f"Creating new table {table_name} with constraints")
                return self._create_table_with_constraints(table_name, sqlite_conn, table_schema)
                
        except Exception as e:
            logging.error(f"Error ensuring table schema for {table_name}: {e}")
            return False
    
    def _get_mysql_table_schema(self, table_name: str, mysql_conn) -> dict:
        """
        Get comprehensive table schema from MySQL including constraints.
        Returns dict with column info and primary key details.
        """
        mysql_cursor = mysql_conn.cursor(buffered=True)
        
        try:
            # Get column information
            mysql_cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
            columns_info = mysql_cursor.fetchall()
            
            schema = {
                'columns': [],
                'primary_key': None,
                'has_auto_increment': False
            }
            
            for col_info in columns_info:
                col_name = col_info[0]      # Field name
                col_type = col_info[1]      # Data type
                col_null = col_info[2]      # NULL allowed
                col_key = col_info[3]       # Key type (PRI, UNI, MUL, etc.)
                col_default = col_info[4]   # Default value
                col_extra = col_info[5]     # Extra info (auto_increment, etc.)
                
                column_def = {
                    'name': col_name,
                    'type': self._convert_mysql_type_to_sqlite(col_type),
                    'null': col_null == 'YES',
                    'default': col_default,
                    'is_primary': col_key == 'PRI',
                    'is_auto_increment': 'auto_increment' in col_extra.lower()
                }
                
                schema['columns'].append(column_def)
                
                # Track primary key and auto increment
                if column_def['is_primary']:
                    schema['primary_key'] = col_name
                    schema['has_auto_increment'] = column_def['is_auto_increment']
            
            return schema
            
        except mysql.connector.Error as e:
            logging.error(f"Error getting MySQL schema for {table_name}: {e}")
            return None
    
    def _table_has_proper_constraints(self, table_name: str, sqlite_conn, expected_schema: dict) -> bool:
        """Check if SQLite table has the expected PRIMARY KEY constraints."""
        sqlite_cursor = sqlite_conn.cursor()
        
        try:
            # Get table info from SQLite
            sqlite_cursor.execute(f"PRAGMA table_info(`{table_name}`)")
            sqlite_columns = sqlite_cursor.fetchall()
            
            # Check if we have a primary key where expected
            expected_pk = expected_schema.get('primary_key')
            if expected_pk:
                # Look for primary key in SQLite table info
                for col_info in sqlite_columns:
                    col_name = col_info[1]
                    is_pk = col_info[5] == 1  # pk column in PRAGMA table_info
                    
                    if col_name == expected_pk and is_pk:
                        logging.debug(f"Table {table_name} has proper PRIMARY KEY constraint on {expected_pk}")
                        return True
                
                logging.debug(f"Table {table_name} missing PRIMARY KEY constraint on {expected_pk}")
                return False
            else:
                # Table shouldn't have a primary key (like METADATA, VAR_MAP)
                return True
                
        except sqlite3.Error as e:
            logging.error(f"Error checking SQLite table constraints for {table_name}: {e}")
            return False
    
    def _create_table_with_constraints(self, table_name: str, sqlite_conn, schema: dict) -> bool:
        """Create a new SQLite table with proper constraints."""
        sqlite_cursor = sqlite_conn.cursor()
        
        try:
            # Build column definitions
            column_defs = []
            for col in schema['columns']:
                col_def = f"`{col['name']}` {col['type']}"
                
                # Add PRIMARY KEY constraint
                if col['is_primary']:
                    col_def += " PRIMARY KEY"
                    # Note: SQLite handles auto-increment automatically for INTEGER PRIMARY KEY
                
                # Add NOT NULL if needed (usually implied with PRIMARY KEY)
                elif not col['null'] and col['default'] is None:
                    col_def += " NOT NULL"
                    
                column_defs.append(col_def)
            
            # Create table SQL
            create_sql = f"CREATE TABLE `{table_name}` ({', '.join(column_defs)})"
            
            logging.debug(f"Creating table {table_name} with SQL: {create_sql}")
            sqlite_cursor.execute(create_sql)
            sqlite_conn.commit()
            
            logging.info(f"Successfully created table {table_name} with PRIMARY KEY constraints")
            return True
            
        except sqlite3.Error as e:
            logging.error(f"Error creating table {table_name} with constraints: {e}")
            return False
    
    def _migrate_table_schema(self, table_name: str, sqlite_conn, schema: dict) -> bool:
        """
        Migrate existing SQLite table to include proper constraints.
        This is complex and risky, so we use a safe backup-and-recreate approach.
        """
        sqlite_cursor = sqlite_conn.cursor()
        
        try:
            logging.info(f"Starting schema migration for table {table_name}")
            
            # Step 1: Backup existing data
            backup_table = f"{table_name}_backup_{int(time.time())}"
            sqlite_cursor.execute(f"CREATE TABLE `{backup_table}` AS SELECT * FROM `{table_name}`")
            
            # Step 2: Drop original table
            sqlite_cursor.execute(f"DROP TABLE `{table_name}`")
            
            # Step 3: Create new table with proper constraints
            if not self._create_table_with_constraints(table_name, sqlite_conn, schema):
                # Restore from backup if creation failed
                sqlite_cursor.execute(f"ALTER TABLE `{backup_table}` RENAME TO `{table_name}`")
                sqlite_conn.commit()
                logging.error(f"Failed to create new table {table_name}, restored from backup")
                return False
            
            # Step 4: Copy data back (with duplicate handling for PRIMARY KEY tables)
            primary_key = schema.get('primary_key')
            if primary_key:
                # For tables with PRIMARY KEY, use INSERT OR IGNORE to handle potential duplicates
                columns = [col['name'] for col in schema['columns']]
                columns_str = ', '.join(f"`{col}`" for col in columns)
                placeholders = ', '.join(['?'] * len(columns))
                
                # Get all data from backup
                sqlite_cursor.execute(f"SELECT {columns_str} FROM `{backup_table}` ORDER BY `{primary_key}`")
                backup_data = sqlite_cursor.fetchall()
                
                # Insert with duplicate protection
                sqlite_cursor.executemany(
                    f"INSERT OR IGNORE INTO `{table_name}` ({columns_str}) VALUES ({placeholders})",
                    backup_data
                )
                
                # Check for any skipped duplicates
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM `{backup_table}`")
                original_count = sqlite_cursor.fetchone()[0]
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                migrated_count = sqlite_cursor.fetchone()[0]
                
                if migrated_count < original_count:
                    duplicates_removed = original_count - migrated_count
                    logging.warning(f"Migration of {table_name}: removed {duplicates_removed} duplicate rows")
                else:
                    logging.info(f"Migration of {table_name}: all {migrated_count} rows migrated successfully")
            else:
                # For tables without PRIMARY KEY, copy all data
                sqlite_cursor.execute(f"INSERT INTO `{table_name}` SELECT * FROM `{backup_table}`")
            
            # Step 5: Clean up backup table
            sqlite_cursor.execute(f"DROP TABLE `{backup_table}`")
            sqlite_conn.commit()
            
            logging.info(f"Successfully migrated table {table_name} to include PRIMARY KEY constraints")
            return True
            
        except sqlite3.Error as e:
            logging.error(f"Error migrating table schema for {table_name}: {e}")
            # Try to restore from backup if it exists
            try:
                sqlite_cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (backup_table,))
                if sqlite_cursor.fetchone():
                    sqlite_cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
                    sqlite_cursor.execute(f"ALTER TABLE `{backup_table}` RENAME TO `{table_name}`")
                    sqlite_conn.commit()
                    logging.info(f"Restored {table_name} from backup after migration failure")
            except:
                pass
            return False
    
    def _convert_mysql_type_to_sqlite(self, mysql_type: str) -> str:
        """Convert MySQL data types to SQLite equivalents."""
        mysql_type = mysql_type.lower()
        
        if 'int' in mysql_type:
            return 'INTEGER'
        elif any(t in mysql_type for t in ['varchar', 'text', 'char']):
            return 'TEXT'
        elif any(t in mysql_type for t in ['float', 'double', 'decimal']):
            return 'REAL'
        elif 'blob' in mysql_type:
            return 'BLOB'
        else:
            return 'TEXT'  # Default fallback
    
    def _write_to_dam_file(self, batch):
        """Write batch data to DAM file."""
        try:
            with open(self._dam_file_name, 'a') as f:
                for row in batch:
                    line = '\t'.join(str(val) for val in row)
                    f.write(line + '\n')
        except IOError as e:
            logging.warning(f"Could not write to DAM file: {e}")
    
    def update_all_tables(self):
        """Update ROI tables with new data."""
        try:
            with DatabaseConnectionManager(self._remote_host, self._remote_user, self._remote_pass, self._remote_db_name) as mysql_conn:
                with sqlite3.connect(self._dst_path, timeout=30.0) as sqlite_conn:

                    # Get all tables from database and iterate through each one
                    mysql_cursor = mysql_conn.cursor(buffered=True)
                    mysql_cursor.execute("SHOW TABLES")
                    all_db_tables = [row[0] for row in mysql_cursor.fetchall()]
                    
                    logging.info(f"Starting incremental backup for {len(all_db_tables)} tables")
                    
                    # Single iteration with clear categorization
                    for table_name in all_db_tables:
                        try:
                            if table_name in self._TABLE_WITHOUT_KEY:
                                # Tables without ID: METADATA, VAR_MAP, ROI_MAP
                                logging.debug(f"Updating table without ID: {table_name}")
                                self._update_table_without_ID(table_name, mysql_conn, sqlite_conn)
                            elif table_name.startswith("ROI_"):
                                # ROI tables: ROI_1, ROI_2, etc.
                                logging.debug(f"Updating ROI table: {table_name}")
                                self._update_table_with_ID(table_name, mysql_conn, sqlite_conn)
                            elif table_name == "CSV_DAM_ACTIVITY":
                                # CSV export table
                                logging.debug(f"Updating CSV table: {table_name}")
                                self._update_table_with_ID(table_name, mysql_conn, sqlite_conn, dump_csv=True)
                            elif table_name in ["START_EVENTS", "IMG_SNAPSHOTS", "SENSORS"]:
                                # Regular tables with ID
                                logging.debug(f"Updating regular table: {table_name}")
                                self._update_table_with_ID(table_name, mysql_conn, sqlite_conn)
                            else:
                                logging.debug(f"Skipping unknown table: {table_name}")
                        except mysql.connector.Error as e:
                            logging.warning(f"MySQL error updating table {table_name}: {e}")
                        except sqlite3.Error as e:
                            logging.warning(f"SQLite error updating table {table_name}: {e}")
                    
                    logging.info(f"Completed incremental backup for all tables")
        
        except Exception as e:
            logging.error(f"Error during database backup operation: {e}")
            raise
    
    
    def _update_table_with_ID(self, table_name: str, mysql_conn, sqlite_conn, dump_csv: bool = False):
        """
        Update a single table with new records using efficient chunked incremental backup.
        
        Strategy:
        1. Ensure table has proper schema with PRIMARY KEY constraints
        2. Get max(id) from local SQLite table as starting point
        3. Query remote MySQL for 200 rows AFTER that ID  
        4. Write those rows to SQLite using INSERT OR IGNORE
        5. Repeat until fewer than 100 rows returned
        """
        mysql_cursor = mysql_conn.cursor(buffered=True)
        sqlite_cursor = sqlite_conn.cursor()
        
        # Step 0: Ensure table has proper schema including PRIMARY KEY constraints
        if not self._ensure_table_schema(table_name, mysql_conn, sqlite_conn):
            logging.error(f"Failed to ensure proper schema for table {table_name}")
            return
        
        # Step 1: Get the max ID in local table as our starting point
        try:
            sqlite_cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM `{table_name}`")
            current_max_id = sqlite_cursor.fetchone()[0] or 0
        except sqlite3.OperationalError:
            logging.warning(f"Table {table_name} doesn't exist locally, starting from beginning...")
            # Table doesn't exist, start incremental backup from ID 0
            current_max_id = 0
        
        logging.debug(f"Table {table_name}: Starting incremental backup from ID {current_max_id}")
        
        # Handle IMG_SNAPSHOTS table specially for BLOB data
        if table_name == "IMG_SNAPSHOTS":
            select_columns = "id, t, img"
            insert_columns = "(id, t, img)"
            placeholders = "?, ?, ?"
        else:
            # Get column count for placeholder generation (do this once)
            mysql_cursor.execute(f"SELECT * FROM `{table_name}` LIMIT 1")
            if not mysql_cursor.description:
                logging.debug(f"Table {table_name}: No data structure found")
                return
                
            column_count = len(mysql_cursor.description)
            select_columns = "*"
            insert_columns = ""
            placeholders = ','.join(['?'] * column_count)
        
        total_inserted = 0
        chunk_size = 200
        min_chunk_threshold = 100
        
        # Iterative chunked backup
        while True:
            # Step 2: Query remote MySQL for next chunk of rows AFTER current_max_id
            mysql_cursor.execute(
                f"SELECT {select_columns} FROM `{table_name}` WHERE id > %s ORDER BY id LIMIT %s", 
                (current_max_id, chunk_size)
            )
            
            rows = mysql_cursor.fetchall()
            rows_count = len(rows)
            
            logging.debug(f"Table {table_name}: Retrieved {rows_count} rows starting after ID {current_max_id}")
            
            # Step 3: Write rows to SQLite if we got any
            if rows_count > 0:
                # Use INSERT OR IGNORE to handle any potential duplicates gracefully
                # This is safe now that we have PRIMARY KEY constraints
                if insert_columns:
                    # For IMG_SNAPSHOTS with specific columns
                    sqlite_cursor.executemany(
                        f"INSERT OR IGNORE INTO `{table_name}` {insert_columns} VALUES ({placeholders})", 
                        rows
                    )
                else:
                    # For regular tables
                    sqlite_cursor.executemany(
                        f"INSERT OR IGNORE INTO `{table_name}` VALUES ({placeholders})", 
                        rows
                    )
                sqlite_conn.commit()
                
                # Check how many rows were actually inserted (some might have been ignored due to duplicates)
                rows_inserted = sqlite_cursor.rowcount if sqlite_cursor.rowcount > 0 else rows_count
                total_inserted += rows_inserted
                
                if rows_inserted < rows_count:
                    duplicates_skipped = rows_count - rows_inserted
                    logging.warning(f"Table {table_name}: Skipped {duplicates_skipped} duplicate rows during incremental backup")
                
                # Update current_max_id to the highest ID we just inserted
                current_max_id = rows[-1][0]  # First column is always id
                
                logging.debug(f"Table {table_name}: Inserted {rows_count} rows, new max_id = {current_max_id}")
                
                # Handle CSV export if needed
                if dump_csv:
                    self._write_to_dam_file(rows)
            
            # Step 4: Stop if we got fewer than threshold rows (indicates we're caught up)
            if rows_count < min_chunk_threshold:
                break
        
        if total_inserted > 0:
            logging.info(f"Table {self._remote_db_name}.{table_name}: Incremental backup completed - inserted {total_inserted} new records")
        else:
            logging.debug(f"Table {self._remote_db_name}.{table_name}: No new records to backup")
    
    def _update_table_without_ID(self, table_name: str, mysql_conn, sqlite_conn):
        """
        Update tables without ID fields (e.g., METADATA, VAR_MAP, ROI_MAP) using row-by-row duplicate checking.
        These are small tables so we can afford to check each row individually.
        """
        mysql_cursor = mysql_conn.cursor(buffered=True)
        sqlite_cursor = sqlite_conn.cursor()
        
        logging.debug(f"Table {table_name}: Starting row-by-row sync (no ID field)")
        
        # Get all rows from remote MySQL table
        mysql_cursor.execute(f"SELECT * FROM `{table_name}`")
        remote_rows = mysql_cursor.fetchall()
        
        if not remote_rows:
            logging.debug(f"Table {table_name}: No data in remote table")
            return
        
        # Get column info to build proper WHERE clauses
        mysql_cursor.execute(f"DESCRIBE `{table_name}`")
        columns = [row[0] for row in mysql_cursor.fetchall()]
        
        if not columns:
            logging.warning(f"Table {table_name}: No column information available")
            return
        
        # Build placeholders for queries
        column_list = ', '.join(f'`{col}`' for col in columns)
        where_conditions = ' AND '.join(f'`{col}` = ?' for col in columns)
        insert_placeholders = ', '.join(['?'] * len(columns))
        
        inserted_count = 0
        skipped_count = 0
        
        # Check each remote row against local table
        for row in remote_rows:
            # Check if this exact row already exists locally
            sqlite_cursor.execute(
                f"SELECT 1 FROM `{table_name}` WHERE {where_conditions} LIMIT 1",
                row
            )
            
            if sqlite_cursor.fetchone() is None:
                # Row doesn't exist, insert it
                sqlite_cursor.execute(
                    f"INSERT INTO `{table_name}` ({column_list}) VALUES ({insert_placeholders})",
                    row
                )
                inserted_count += 1
            else:
                # Row already exists, skip it
                skipped_count += 1
        
        # Commit all inserts
        sqlite_conn.commit()
        
        if inserted_count > 0:
            logging.info(f"Table {table_name}: Row-by-row sync completed - inserted {inserted_count} new rows, skipped {skipped_count} duplicates")
        else:
            logging.debug(f"Table {table_name}: No new rows to insert, {skipped_count} rows already present")

class DBDiff(BaseSQLConnector):
    """Optimized database comparison class."""
    
    def __init__(self, db_name: str, remote_host: str, filename: str):
        super().__init__(
            remote_host=remote_host,
            remote_user="ethoscope", 
            remote_pass="ethoscope",
            dst_path=filename,
            remote_db_name=db_name
        )