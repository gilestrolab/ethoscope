#!/usr/bin/env python3
"""
Utility script to detect and remove duplicate rows from SQLite databases.

This script scans for SQLite database files and removes duplicate rows based on the 'id' column,
keeping only the first occurrence of each duplicate set.

Usage:
    python cleanup_duplicate_db_rows.py [--directory /path/to/results] [--dry-run] [--verbose]
"""

import sqlite3
import os
import argparse
import logging
import glob
from typing import Dict, List, Tuple, Optional
import tempfile
import shutil
from pathlib import Path


class SQLiteDuplicateCleaner:
    """Class to handle duplicate row detection and removal in SQLite databases."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.setup_logging()
        
    def setup_logging(self):
        """Setup logging configuration."""
        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)
    
    def find_database_files(self, directory: str) -> List[str]:
        """Find all SQLite database files in the given directory."""
        patterns = ['*.db', '*.sqlite', '*.sqlite3']
        db_files = []
        
        for pattern in patterns:
            search_pattern = os.path.join(directory, '**', pattern)
            db_files.extend(glob.glob(search_pattern, recursive=True))
        
        # Also check for files without extension that might be SQLite
        for root, dirs, files in os.walk(directory):
            for file in files:
                if '.' not in file and file != 'lost+found':
                    filepath = os.path.join(root, file)
                    if self.is_sqlite_file(filepath):
                        db_files.append(filepath)
        
        return sorted(set(db_files))
    
    def is_sqlite_file(self, filepath: str) -> bool:
        """Check if a file is a SQLite database."""
        try:
            with open(filepath, 'rb') as f:
                header = f.read(16)
                return header.startswith(b'SQLite format 3\x00')
        except (IOError, OSError):
            return False
    
    def get_table_info(self, db_path: str) -> Dict[str, Dict]:
        """Get information about tables and their columns."""
        try:
            with sqlite3.connect(db_path, timeout=10.0) as conn:
                cursor = conn.cursor()
                
                # Get all non-system tables
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """)
                tables = [row[0] for row in cursor.fetchall()]
                
                table_info = {}
                for table in tables:
                    # Get column information
                    cursor.execute(f"PRAGMA table_info(`{table}`)")
                    columns = cursor.fetchall()
                    
                    # Check if table has an 'id' column
                    has_id = any(col[1] == 'id' for col in columns)
                    
                    table_info[table] = {
                        'columns': [col[1] for col in columns],
                        'has_id': has_id
                    }
                
                return table_info
                
        except sqlite3.Error as e:
            self.logger.error(f"Error reading database {db_path}: {e}")
            return {}
    
    def detect_duplicates(self, db_path: str, table_name: str, has_id: bool = True) -> Tuple[int, int]:
        """Detect duplicate rows in a table based on 'id' column or all columns."""
        try:
            with sqlite3.connect(db_path, timeout=10.0) as conn:
                cursor = conn.cursor()
                
                # Count total rows
                cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                total_rows = cursor.fetchone()[0]
                
                if has_id:
                    # Count unique IDs
                    cursor.execute(f"SELECT COUNT(DISTINCT id) FROM `{table_name}`")
                    unique_rows = cursor.fetchone()[0]
                else:
                    # For tables without ID, check for duplicate rows based on all columns
                    # Get all column names
                    cursor.execute(f"PRAGMA table_info(`{table_name}`)")
                    columns = [col[1] for col in cursor.fetchall()]
                    columns_str = ', '.join(f"`{col}`" for col in columns)
                    
                    # Count distinct rows
                    cursor.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {columns_str} FROM `{table_name}`)")
                    unique_rows = cursor.fetchone()[0]
                
                duplicates = total_rows - unique_rows
                return total_rows, duplicates
                
        except sqlite3.Error as e:
            self.logger.error(f"Error detecting duplicates in {db_path}.{table_name}: {e}")
            return 0, 0
    
    def remove_duplicates(self, db_path: str, table_name: str, has_id: bool = True) -> Tuple[int, int]:
        """Remove duplicate rows, keeping the first occurrence."""

        total, duplicates = self.detect_duplicates(db_path, table_name, has_id)

        if self.dry_run:
            self.logger.info(f"[DRY RUN] Would remove {duplicates} duplicate rows from {table_name}")
            return total, duplicates
        
        if duplicates == 0:
            return 0, 0

        try:
            with sqlite3.connect(db_path, timeout=30.0) as conn:
                cursor = conn.cursor()
                
                # Count before
                cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                before_count = cursor.fetchone()[0]
                
                # Create temporary table with unique rows (keeping first occurrence)
                temp_table = f"{table_name}_temp_{int(time.time())}"
                
                # Get all column names
                cursor.execute(f"PRAGMA table_info(`{table_name}`)")
                columns = [col[1] for col in cursor.fetchall()]
                columns_str = ', '.join(f"`{col}`" for col in columns)
                
                # Create temp table with same structure
                cursor.execute(f"CREATE TABLE `{temp_table}` AS SELECT {columns_str} FROM `{table_name}` WHERE 1=0")
                
                # Insert unique rows
                if has_id:
                    # For tables with ID column, group by ID
                    cursor.execute(f"""
                        INSERT INTO `{temp_table}` 
                        SELECT {columns_str} FROM `{table_name}` 
                        WHERE rowid IN (
                            SELECT MIN(rowid) FROM `{table_name}` GROUP BY id
                        )
                    """)
                else:
                    # For tables without ID (like metadata), use DISTINCT to remove duplicates
                    cursor.execute(f"""
                        INSERT INTO `{temp_table}` 
                        SELECT DISTINCT {columns_str} FROM `{table_name}`
                    """)
                
                # Count temp table
                cursor.execute(f"SELECT COUNT(*) FROM `{temp_table}`")
                after_count = cursor.fetchone()[0]
                
                # Replace original table
                cursor.execute(f"DROP TABLE `{table_name}`")
                cursor.execute(f"ALTER TABLE `{temp_table}` RENAME TO `{table_name}`")
                
                conn.commit()
            
            # Vacuum to reclaim space (must be outside transaction)
            with sqlite3.connect(db_path, timeout=30.0) as vacuum_conn:
                vacuum_conn.execute("VACUUM")
            
            removed = before_count - after_count
            self.logger.info(f"Removed {removed} duplicate rows from {table_name} ({before_count} → {after_count})")
            
            return before_count, removed
                
        except sqlite3.Error as e:
            self.logger.error(f"Error removing duplicates from {db_path}.{table_name}: {e}")
            # Restore backup if something went wrong
            if os.path.exists(backup_path) and not self.dry_run:
                shutil.copy2(backup_path, db_path)
                self.logger.info(f"Restored from backup due to error")
            return 0, 0
    
    def get_file_size(self, filepath: str) -> int:
        """Get file size in bytes."""
        try:
            return os.path.getsize(filepath)
        except OSError:
            return 0
    
    def format_size(self, size_bytes: int) -> str:
        """Format size in human readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
    
    def process_database(self, db_path: str) -> Dict:
        """Process a single database file."""
        self.logger.info(f"Processing: {db_path}")
        
        initial_size = self.get_file_size(db_path)
        
        if not self.dry_run:
            backup_path = f"{db_path}.backup_{int(time.time())}"
            shutil.copy2(db_path, backup_path)
            self.logger.info(f"Created backup: {backup_path}")


        # Get table information
        table_info = self.get_table_info(db_path)
        if not table_info:
            return {'error': 'Could not read database', 'initial_size': initial_size}
        
        results = {
            'path': db_path,
            'initial_size': initial_size,
            'tables_processed': 0,
            'total_duplicates_removed': 0,
            'tables': {}
        }
        
        # Process each table (with or without 'id' column)
        for table_name, info in table_info.items():
            has_id = info['has_id']
            
            # Check if table has duplicates first
            total_rows, potential_duplicates = self.detect_duplicates(db_path, table_name, has_id)
            
            if potential_duplicates > 0 or has_id:  # Process tables with ID or tables that have duplicates
                actual_total, duplicates_removed = self.remove_duplicates(db_path, table_name, has_id)
                results['tables'][table_name] = {
                    'total_rows': actual_total,
                    'duplicates_removed': duplicates_removed,
                    'has_id': has_id
                }
                results['total_duplicates_removed'] += duplicates_removed
                results['tables_processed'] += 1
                
                if duplicates_removed > 0:
                    self.logger.info(f"Table {table_name}: removed {duplicates_removed} duplicate rows")
            else:
                self.logger.debug(f"Skipping table {table_name} (no duplicates found)")
        
        final_size = self.get_file_size(db_path)
        results['final_size'] = final_size
        results['size_saved'] = initial_size - final_size
        
        if results['total_duplicates_removed'] > 0:
            self.logger.info(f"Database {db_path}: removed {results['total_duplicates_removed']} duplicates, "
                           f"saved {self.format_size(results['size_saved'])}")
        
        return results
    
    def cleanup_directory(self, directory: str) -> Dict:
        """Clean up duplicate rows in all databases in the directory."""
        self.logger.info(f"Scanning directory: {directory}")
        
        db_files = self.find_database_files(directory)
        self.logger.info(f"Found {len(db_files)} database files")
        
        if not db_files:
            return {'databases': [], 'total_duplicates_removed': 0, 'total_size_saved': 0}
        
        results = {
            'databases': [],
            'total_duplicates_removed': 0,
            'total_size_saved': 0
        }
        
        for db_path in db_files:
            db_result = self.process_database(db_path)
            results['databases'].append(db_result)
            
            if 'total_duplicates_removed' in db_result:
                results['total_duplicates_removed'] += db_result['total_duplicates_removed']
            if 'size_saved' in db_result:
                results['total_size_saved'] += db_result['size_saved']
        
        return results


def main():
    parser = argparse.ArgumentParser(description='Clean duplicate rows from SQLite databases')
    parser.add_argument('--directory', '-d', 
                       help='Directory to scan for databases (default: /ethoscope_data/results)')
    parser.add_argument('--file', '-f',
                       help='Process a single database file')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.file and args.directory:
        print("Error: Cannot specify both --file and --directory")
        return 1
    
    if not args.file and not args.directory:
        args.directory = '/ethoscope_data/results'  # Set default
    
    cleaner = SQLiteDuplicateCleaner(dry_run=args.dry_run, verbose=args.verbose)
    
    if args.file:
        # Process single file
        if not os.path.exists(args.file):
            print(f"Error: File {args.file} does not exist")
            return 1
        
        if not cleaner.is_sqlite_file(args.file):
            print(f"Error: {args.file} is not a SQLite database")
            return 1
        
        print(f"{'DRY RUN: ' if args.dry_run else ''}Cleaning duplicate rows in {args.file}")
        
        db_result = cleaner.process_database(args.file)
        results = {
            'databases': [db_result],
            'total_duplicates_removed': db_result.get('total_duplicates_removed', 0),
            'total_size_saved': db_result.get('size_saved', 0)
        }
    else:
        # Process directory
        if not os.path.exists(args.directory):
            print(f"Error: Directory {args.directory} does not exist")
            return 1
        
        print(f"{'DRY RUN: ' if args.dry_run else ''}Cleaning duplicate rows in {args.directory}")
        
        results = cleaner.cleanup_directory(args.directory)
    
    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Databases processed: {len(results['databases'])}")
    print(f"Total duplicates removed: {results['total_duplicates_removed']}")
    print(f"Total space saved: {cleaner.format_size(results['total_size_saved'])}")
    
    if args.dry_run:
        print("\nThis was a dry run. Use without --dry-run to actually remove duplicates.")
    else:
        print("\nBackup files were created for each modified database.")
    
    return 0


if __name__ == "__main__":
    import time
    exit(main())