import mysql.connector
import sqlite3
import os
import logging
import contextlib
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
                if table_name in ["ROI_MAP", "VAR_MAP"] or table_name.startswith("METADATA"):
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
                        if table_name not in ["ROI_MAP", "VAR_MAP", "METADATA"]:
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
            
            total_remote = 0
            total_local = 0
            
            for table_name, local_count in local_tables_info.items():
                # Find remote count
                remote_count = 0
                if use_fast_mode:
                    remote_count = remote_tables_info.get("default", {}).get(table_name, 0)
                else:
                    db_name = self._remote_db_name or list(remote_tables_info.keys())[0]
                    remote_count = remote_tables_info.get(db_name, {}).get(table_name, 0)
                
                if remote_count is None:
                    remote_count = 0
                if local_count is None:
                    local_count = 0
                
                total_remote += int(remote_count)
                total_local += int(local_count)
            
            if total_remote == 0:
                return -1
            
            return (total_local / total_remote) * 100
            
        except Exception as e:
            logging.error(f"Error comparing databases: {e}")
            return -1

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
            try:
                if table_name == "CSV_DAM_ACTIVITY":
                    self._copy_table(table_name, mysql_conn, sqlite_conn, dump_csv=True)
                else:
                    self._copy_table(table_name, mysql_conn, sqlite_conn)
            except Exception as e:
                logging.error(f"Error copying table {table_name}: {e}")
                raise
    
    def _copy_table(self, table_name: str, mysql_conn, sqlite_conn, dump_csv: bool = False):
        """Copy a single table from MySQL to SQLite."""
        mysql_cursor = mysql_conn.cursor(buffered=True)
        sqlite_cursor = sqlite_conn.cursor()
        
        # Get table schema
        mysql_cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        columns = []
        for col_info in mysql_cursor.fetchall():
            col_name, col_type = col_info[0], col_info[1]
            columns.append(f"`{col_name}` {self._convert_mysql_type_to_sqlite(col_type)}")
        
        # Create table if it doesn't exist
        create_sql = f"CREATE TABLE IF NOT EXISTS `{table_name}` ({', '.join(columns)})"
        try:
            sqlite_cursor.execute(create_sql)
        except sqlite3.OperationalError as e:
            logging.debug(f"Table {table_name} already exists: {e}")
            return
        
        # Copy data
        if table_name == "IMG_SNAPSHOTS":
            self._copy_image_data(table_name, mysql_conn, sqlite_conn)
        else:
            self._copy_regular_data(table_name, mysql_conn, sqlite_conn, dump_csv)
    
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
    
    def _copy_image_data(self, table_name: str, mysql_conn, sqlite_conn):
        """Copy image data with proper BLOB handling."""
        mysql_cursor = mysql_conn.cursor(buffered=True)
        sqlite_cursor = sqlite_conn.cursor()
        
        mysql_cursor.execute(f"SELECT id, t, img FROM `{table_name}`")
        
        batch = []
        for row in mysql_cursor:
            batch.append((row[0], row[1], row[2]))  # id, t, img_blob
            
            if len(batch) >= self.MAX_BATCH_SIZE:
                sqlite_cursor.executemany(
                    f"INSERT INTO `{table_name}` (id, t, img) VALUES (?, ?, ?)", 
                    batch
                )
                sqlite_conn.commit()
                batch = []
        
        # Insert remaining rows
        if batch:
            sqlite_cursor.executemany(
                f"INSERT INTO `{table_name}` (id, t, img) VALUES (?, ?, ?)", 
                batch
            )
            sqlite_conn.commit()
    
    def _copy_regular_data(self, table_name: str, mysql_conn, sqlite_conn, dump_csv: bool = False):
        """Copy regular table data with batching."""
        mysql_cursor = mysql_conn.cursor(buffered=True)
        sqlite_cursor = sqlite_conn.cursor()
        
        mysql_cursor.execute(f"SELECT * FROM `{table_name}`")
        
        # Get column count for placeholder generation
        column_count = len(mysql_cursor.description)
        placeholders = ','.join(['?'] * column_count)
        
        batch = []
        for row in mysql_cursor:
            batch.append(row)
            
            if len(batch) >= self.MAX_BATCH_SIZE:
                sqlite_cursor.executemany(
                    f"INSERT INTO `{table_name}` VALUES ({placeholders})", 
                    batch
                )
                sqlite_conn.commit()
                
                if dump_csv:
                    self._write_to_dam_file(batch)
                
                batch = []
        
        # Insert remaining rows
        if batch:
            sqlite_cursor.executemany(
                f"INSERT INTO `{table_name}` VALUES ({placeholders})", 
                batch
            )
            sqlite_conn.commit()
            
            if dump_csv:
                self._write_to_dam_file(batch)
    
    def _write_to_dam_file(self, batch):
        """Write batch data to DAM file."""
        try:
            with open(self._dam_file_name, 'a') as f:
                for row in batch:
                    line = '\t'.join(str(val) for val in row)
                    f.write(line + '\n')
        except IOError as e:
            logging.warning(f"Could not write to DAM file: {e}")
    
    def update_roi_tables(self):
        """Update ROI tables with new data."""
        try:
            with DatabaseConnectionManager(self._remote_host, self._remote_user,
                                         self._remote_pass, self._remote_db_name) as mysql_conn:
                with sqlite3.connect(self._dst_path, timeout=30.0) as sqlite_conn:
                    self._update_all_roi_tables(mysql_conn, sqlite_conn)
        except Exception as e:
            logging.error(f"Error updating ROI tables: {e}")
            raise
    
    def _update_all_roi_tables(self, mysql_conn, sqlite_conn):
        """Update all ROI-related tables."""
        sqlite_cursor = sqlite_conn.cursor()
        
        # Get ROI indices
        sqlite_cursor.execute("SELECT DISTINCT roi_idx FROM ROI_MAP")
        roi_indices = [row[0] for row in sqlite_cursor.fetchall()]
        
        # Update each ROI table
        for roi_idx in roi_indices:
            self._update_single_table(f"ROI_{roi_idx}", mysql_conn, sqlite_conn)
        
        # Update other tables
        for table_name in ["CSV_DAM_ACTIVITY", "START_EVENTS", "IMG_SNAPSHOTS", "SENSORS"]:
            try:
                dump_csv = (table_name == "CSV_DAM_ACTIVITY")
                self._update_single_table(table_name, mysql_conn, sqlite_conn, dump_csv)
            except mysql.connector.Error as e:
                logging.warning(f"Could not update table {table_name}: {e}")
    
    def _update_single_table(self, table_name: str, mysql_conn, sqlite_conn, dump_csv: bool = False):
        """Update a single table with new records."""
        mysql_cursor = mysql_conn.cursor(buffered=True)
        sqlite_cursor = sqlite_conn.cursor()
        
        # Get the last ID in local table
        try:
            sqlite_cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM `{table_name}`")
            last_local_id = sqlite_cursor.fetchone()[0] or 0
        except sqlite3.OperationalError:
            logging.warning(f"Table {table_name} doesn't exist locally, recreating...")
            # Table doesn't exist, copy entirely
            self._copy_table(table_name, mysql_conn, sqlite_conn, dump_csv)
            return
        
        # Get new records from MySQL
        mysql_cursor.execute(f"SELECT * FROM `{table_name}` WHERE id > %s", (last_local_id,))
        
        # Get column count for placeholder generation
        if mysql_cursor.description:
            column_count = len(mysql_cursor.description)
            placeholders = ','.join(['?'] * column_count)
            
            batch = []
            for row in mysql_cursor:
                batch.append(row)
                
                if len(batch) >= self.MAX_BATCH_SIZE:
                    sqlite_cursor.executemany(
                        f"INSERT INTO `{table_name}` VALUES ({placeholders})", 
                        batch
                    )
                    sqlite_conn.commit()
                    
                    if dump_csv:
                        self._write_to_dam_file(batch)
                    
                    batch = []
            
            # Insert remaining rows
            if batch:
                sqlite_cursor.executemany(
                    f"INSERT INTO `{table_name}` VALUES ({placeholders})", 
                    batch
                )
                sqlite_conn.commit()
                
                if dump_csv:
                    self._write_to_dam_file(batch)

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