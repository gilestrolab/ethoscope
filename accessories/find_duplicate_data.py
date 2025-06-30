#!/usr/bin/env python3
"""
SQLite Database Duplicate Data Finder

This independent script recursively searches for SQLite database files and identifies
those containing duplicate data. It can check specific tables (VAR_MAP, METADATA) 
or all tables based on command-line options.

Usage:
    python find_duplicate_data.py [--path /path/to/search] [--full] [--verbose]

Options:
    --path, -p: Directory to search recursively (default: /ethoscope_data/results)
    --full, -f: Check all tables for duplicates (default: only VAR_MAP and METADATA)
    --verbose, -v: Enable verbose output with detailed logging
    --help, -h: Show this help message

Output:
    Returns a list of full paths to SQLite database files containing duplicates.
"""

import os
import sys
import sqlite3
import argparse
import logging
from typing import List, Set, Tuple
from pathlib import Path


class DuplicateDataFinder:
    """SQLite database duplicate data detection utility."""
    
    DEFAULT_TABLES = ['METADATA', 'VAR_MAP']
    
    def __init__(self, verbose: bool = False):
        """Initialize the duplicate finder."""
        self.verbose = verbose
        self.setup_logging()
        self.databases_with_duplicates: List[str] = []
        self.total_databases_checked = 0
        self.total_duplicates_found = 0
    
    def setup_logging(self):
        """Configure logging based on verbosity level."""
        level = logging.DEBUG if self.verbose else logging.CRITICAL  # Only critical errors in non-verbose mode
        logging.basicConfig(
            level=level,
            format='%(levelname)s: %(message)s',
            stream=sys.stderr
        )
        self.logger = logging.getLogger(__name__)
    
    def find_sqlite_files(self, root_path: str) -> List[str]:
        """
        Recursively find all SQLite database files in the given path.
        
        Args:
            root_path: Root directory to search
            
        Returns:
            List of full paths to SQLite database files
        """
        sqlite_files = []
        root_path = Path(root_path).resolve()
        
        if not root_path.exists():
            self.logger.error(f"Path does not exist: {root_path}")
            return []
        
        if not root_path.is_dir():
            self.logger.error(f"Path is not a directory: {root_path}")
            return []
        
        self.logger.info(f"Searching for SQLite files in: {root_path}")
        
        # Common SQLite file extensions
        sqlite_extensions = {'.db', '.sqlite', '.sqlite3'}
        
        try:
            for file_path in root_path.rglob('*'):
                if file_path.is_file() and file_path.suffix.lower() in sqlite_extensions:
                    # Verify it's actually a SQLite file by trying to open it
                    if self.is_sqlite_file(str(file_path)):
                        sqlite_files.append(str(file_path))
                        self.logger.debug(f"Found SQLite file: {file_path}")
        
        except PermissionError as e:
            self.logger.error(f"Permission denied accessing path: {e}")
        except Exception as e:
            self.logger.error(f"Error scanning directory: {e}")
        
        self.logger.info(f"Found {len(sqlite_files)} SQLite database files")
        return sqlite_files
    
    def is_sqlite_file(self, file_path: str) -> bool:
        """
        Check if a file is a valid SQLite database.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            True if the file is a valid SQLite database
        """
        try:
            with sqlite3.connect(file_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
                return True
        except (sqlite3.Error, OSError):
            return False
    
    def get_table_names(self, db_path: str) -> Set[str]:
        """
        Get all table names from a SQLite database.
        
        Args:
            db_path: Path to the SQLite database
            
        Returns:
            Set of table names
        """
        try:
            with sqlite3.connect(db_path, timeout=10.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """)
                return {row[0] for row in cursor.fetchall()}
        except sqlite3.Error as e:
            self.logger.error(f"Error getting table names from {db_path}: {e}")
            return set()
    
    def check_table_duplicates(self, db_path: str, table_name: str) -> bool:
        """
        Check if a specific table contains duplicate rows.
        Uses optimized id-based checking for tables with AUTO_INCREMENT PRIMARY KEY id fields.
        
        Args:
            db_path: Path to the SQLite database
            table_name: Name of the table to check
            
        Returns:
            True if duplicates are found, False otherwise
        """
        try:
            with sqlite3.connect(db_path, timeout=10.0) as conn:
                cursor = conn.cursor()
                
                # Get column names and info for the table
                cursor.execute(f"PRAGMA table_info(`{table_name}`)")
                columns_info = cursor.fetchall()
                
                if not columns_info:
                    self.logger.debug(f"No columns found in table {table_name}")
                    return False
                
                columns = [row[1] for row in columns_info]
                
                # Check if table has an 'id' column (indicates AUTO_INCREMENT PRIMARY KEY)
                has_id_column = 'id' in columns
                
                # Count total rows first
                cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                total_count = cursor.fetchone()[0]
                
                if total_count == 0:
                    self.logger.debug(f"Table {table_name} is empty")
                    return False
                
                if has_id_column:
                    # Fast method: check for gaps or duplicates in id sequence
                    # If ids are unique and sequential, max(id) should equal count(*)
                    cursor.execute(f"SELECT MAX(id) FROM `{table_name}`")
                    max_id = cursor.fetchone()[0]
                    
                    cursor.execute(f"SELECT COUNT(DISTINCT id) FROM `{table_name}`")
                    distinct_ids = cursor.fetchone()[0]
                    
                    # Check for duplicate IDs (this should never happen with AUTO_INCREMENT, but...)
                    id_duplicates = distinct_ids < total_count
                    
                    if id_duplicates:
                        duplicate_count = total_count - distinct_ids
                        self.logger.warning(f"CRITICAL: Duplicate IDs found in {table_name}: {duplicate_count} duplicate ID rows")
                        return True
                    
                    # For tracking tables (ROI_*, START_EVENTS, etc.), also check for data duplicates
                    # by comparing non-id columns only
                    if table_name.startswith('ROI_') or table_name in ['START_EVENTS', 'SENSORS', 'IMG_SNAPSHOTS', 'CSV_DAM_ACTIVITY']:
                        non_id_columns = [col for col in columns if col != 'id']
                        if non_id_columns:
                            column_list = ', '.join(f'`{col}`' for col in non_id_columns)
                            cursor.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {column_list} FROM `{table_name}`)")
                            distinct_data_count = cursor.fetchone()[0]
                            
                            data_duplicates = total_count > distinct_data_count
                            if data_duplicates:
                                duplicate_count = total_count - distinct_data_count
                                self.logger.info(f"Data duplicates found in {table_name}: {duplicate_count} duplicate data rows "
                                               f"({total_count} total, {distinct_data_count} unique data combinations)")
                                return True
                    
                    self.logger.debug(f"No duplicates in {table_name} ({total_count} rows, max_id={max_id})")
                    return False
                
                else:
                    # Slow method for tables without id (METADATA, VAR_MAP): check all columns
                    column_list = ', '.join(f'`{col}`' for col in columns)
                    
                    if not column_list.strip():
                        self.logger.debug(f"Table {table_name} has no valid columns for duplicate checking")
                        return False
                    
                    # Count distinct rows using a subquery approach that works with SQLite
                    cursor.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {column_list} FROM `{table_name}`)")
                    distinct_count = cursor.fetchone()[0]
                    
                    has_duplicates = total_count > distinct_count
                    
                    if has_duplicates:
                        duplicate_count = total_count - distinct_count
                        self.logger.info(f"Duplicates found in {table_name}: {duplicate_count} duplicate rows "
                                       f"({total_count} total, {distinct_count} unique)")
                    else:
                        self.logger.debug(f"No duplicates in {table_name} ({total_count} rows)")
                    
                    return has_duplicates
                
        except sqlite3.Error as e:
            self.logger.error(f"Error checking duplicates in table {table_name} of {db_path}: {e}")
            return False
    
    def check_database_duplicates(self, db_path: str, check_all_tables: bool = False) -> bool:
        """
        Check a database for duplicate data.
        
        Args:
            db_path: Path to the SQLite database
            check_all_tables: If True, check all tables; if False, only check DEFAULT_TABLES
            
        Returns:
            True if any duplicates are found, False otherwise
        """
        self.logger.debug(f"Checking database: {db_path}")
        
        try:
            # Get all table names
            all_tables = self.get_table_names(db_path)
            
            if not all_tables:
                self.logger.debug(f"No tables found in database: {db_path}")
                return False
            
            # Determine which tables to check
            if check_all_tables:
                tables_to_check = all_tables
                self.logger.debug(f"Checking all {len(tables_to_check)} tables")
            else:
                tables_to_check = {table for table in self.DEFAULT_TABLES if table in all_tables}
                self.logger.debug(f"Checking default tables: {tables_to_check}")
            
            if not tables_to_check:
                self.logger.debug(f"No tables to check in database: {db_path}")
                return False
            
            # Check each table for duplicates
            duplicates_found = False
            for table_name in sorted(tables_to_check):
                if self.check_table_duplicates(db_path, table_name):
                    duplicates_found = True
                    if not check_all_tables:
                        # For default mode, we can stop at the first duplicate found
                        break
            
            return duplicates_found
            
        except Exception as e:
            self.logger.error(f"Error checking database {db_path}: {e}")
            return False
    
    def find_databases_with_duplicates(self, root_path: str, check_all_tables: bool = False) -> List[str]:
        """
        Find all SQLite databases containing duplicate data.
        
        Args:
            root_path: Root directory to search
            check_all_tables: If True, check all tables; if False, only check DEFAULT_TABLES
            
        Returns:
            List of full paths to databases containing duplicates
        """
        self.logger.info(f"Starting duplicate data search in: {root_path}")
        self.logger.info(f"Mode: {'All tables' if check_all_tables else f'Default tables only ({self.DEFAULT_TABLES})'}")
        
        # Find all SQLite files
        sqlite_files = self.find_sqlite_files(root_path)
        
        if not sqlite_files:
            self.logger.warning("No SQLite database files found")
            return []
        
        # Check each database for duplicates
        databases_with_duplicates = []
        
        for i, db_path in enumerate(sqlite_files, 1):
            self.logger.info(f"Checking database {i}/{len(sqlite_files)}: {os.path.basename(db_path)}")
            
            try:
                if self.check_database_duplicates(db_path, check_all_tables):
                    databases_with_duplicates.append(db_path)
                    self.total_duplicates_found += 1
                    self.logger.warning(f"DUPLICATES FOUND: {db_path}")
                
                self.total_databases_checked += 1
                
            except Exception as e:
                self.logger.error(f"Failed to check database {db_path}: {e}")
        
        # Summary
        self.logger.info(f"Scan complete: {self.total_databases_checked} databases checked, "
                        f"{self.total_duplicates_found} contain duplicates")
        
        return databases_with_duplicates


def main():
    """Main function with command-line argument parsing."""
    parser = argparse.ArgumentParser(
        description='Find SQLite databases containing duplicate data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Search default directory for METADATA/VAR_MAP duplicates
  %(prog)s --path /my/data --full             # Search all tables in /my/data
  %(prog)s --verbose                          # Enable verbose logging
        """
    )
    
    parser.add_argument(
        '--path', '-p',
        default='/ethoscope_data/results',
        help='Directory to search recursively (default: /ethoscope_data/results)'
    )
    
    parser.add_argument(
        '--full', '-f',
        action='store_true',
        help='Check all tables for duplicates (default: only METADATA and VAR_MAP)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        default=False,
        help='Enable verbose output with detailed logging'
    )
    
    args = parser.parse_args()
    
    # Create finder instance
    finder = DuplicateDataFinder(verbose=args.verbose)
    
    try:
        # Find databases with duplicates
        duplicate_databases = finder.find_databases_with_duplicates(
            args.path, 
            check_all_tables=args.full
        )
        
        # Output results
        if duplicate_databases:
            print(f"Found {len(duplicate_databases)} databases with duplicates:")
            for db_path in duplicate_databases:
                print(db_path)
            sys.exit(1)  # Exit with error code to indicate duplicates found
        else:
            if args.verbose:
                print("No databases with duplicates found.")
            sys.exit(0)  # Success
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()