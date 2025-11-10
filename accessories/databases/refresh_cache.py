#!/usr/bin/env python3
"""
Database Cache Refresh Script for Ethoscope

This script refreshes all database cache JSON files by extracting metadata directly from
databases and creating properly timestamped cache files. It supports both SQLite and MySQL
databases and ensures cache filenames reflect actual database metadata timestamps.

Usage:
    python refresh_cache.py --all          # Refresh all database types
    python refresh_cache.py --sqlite       # Refresh only SQLite databases
    python refresh_cache.py --mysql --host ethoscope004.local # Refresh only MySQL databases
    python refresh_cache.py --dry-run      # Show what would be processed without changes
"""

import argparse
import logging
import os
import sys
import glob
import time
import json
from pathlib import Path

# Add the src directory to Python path to import ethoscope modules
ethoscope_src = os.path.join(os.path.dirname(__file__), '..', '..', 'src', 'ethoscope')
sys.path.insert(0, ethoscope_src)

from ethoscope.io.cache import (
    create_metadata_cache,
    MySQLDatabaseMetadataCache,
    SQLiteDatabaseMetadataCache
)
from ethoscope.utils import pi
import mysql.connector
import sqlite3

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
ETHOSCOPE_DATA_DIR = "/ethoscope_data"
RESULTS_DIR = os.path.join(ETHOSCOPE_DATA_DIR, "results")
CACHE_DIR = os.path.join(ETHOSCOPE_DATA_DIR, "cache")
MYSQL_CREDENTIALS = {
    "user": "ethoscope",
    "password": "ethoscope"
}



def discover_sqlite_databases():
    """
    Discover all SQLite databases in the results directory.

    Returns:
        list: List of dictionaries with database information
    """
    sqlite_databases = []

    if not os.path.exists(RESULTS_DIR):
        logger.warning(f"Results directory {RESULTS_DIR} does not exist")
        return sqlite_databases

    # Search pattern: /ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/*.db
    db_pattern = os.path.join(RESULTS_DIR, "*", "*", "*", "*.db")
    db_files = glob.glob(db_pattern)

    logger.info(f"Found {len(db_files)} SQLite database files")

    for db_path in db_files:
        try:
            # Parse path components
            path_parts = db_path.split(os.sep)
            if len(path_parts) < 4:
                continue

            machine_id = path_parts[-4]
            machine_name = path_parts[-3]
            date_time_dir = path_parts[-2]
            db_filename = path_parts[-1]

            # Verify database file exists and is accessible
            if not os.path.exists(db_path):
                logger.warning(f"Database file does not exist: {db_path}")
                continue

            # No need to manually extract timestamp - cache system will handle it
            sqlite_databases.append({
                'path': db_path,
                'machine_id': machine_id,
                'machine_name': machine_name,
                'backup_filename': db_filename
            })

        except Exception as e:
            logger.error(f"Error processing SQLite database {db_path}: {e}")
            continue

    return sqlite_databases


def refresh_sqlite_cache(sqlite_db_info, dry_run=False):
    """
    Refresh cache for a single SQLite database.

    Args:
        sqlite_db_info (dict): SQLite database information
        dry_run (bool): If True, only show what would be done
    """
    try:
        db_path = sqlite_db_info['path']
        machine_name = sqlite_db_info['machine_name']
        machine_id = sqlite_db_info['machine_id']

        logger.info(f"Processing SQLite database: {db_path}")

        if dry_run:
            logger.info(f"[DRY RUN] Would refresh cache for {db_path}")
            return

        # Create SQLite metadata cache
        cache = create_metadata_cache(
            db_credentials={"name": db_path},
            device_name=machine_name,
            cache_dir=CACHE_DIR,
            database_type="SQLite3"
        )

        # Get timestamp from DB to construct correct filename
        timestamp = cache.get_database_timestamp()
        if timestamp:
            ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(timestamp))
            correct_backup_filename = f"{ts_str}_{machine_id}.db"
            logger.info(f"Constructed correct backup filename: {correct_backup_filename}")
        else:
            # Fallback to original filename if timestamp not found
            correct_backup_filename = sqlite_db_info['backup_filename']
            logger.warning(f"Could not get timestamp from {db_path}, using original filename: {correct_backup_filename}")

        # Use cache system to refresh from database metadata (fully automated)
        cache_filepath = cache.refresh_cache_from_database(
            backup_filename=correct_backup_filename,
            sqlite_source_path=db_path
        )

        logger.info(f"Created cache file: {cache_filepath}")

    except Exception as e:
        logger.error(f"Failed to refresh SQLite cache for {sqlite_db_info['path']}: {e}")


def refresh_mysql_cache(dry_run=False, host=None, db_name=None, user=None, password=None):
    """
    Refresh cache for a single MySQL database.

    Args:
        dry_run (bool): If True, only show what would be done
        host (str): MySQL host (default: localhost)
        db_name (str): Database name (default: auto-detect from machine)
        user (str): MySQL username (default: ethoscope)
        password (str): MySQL password (default: ethoscope)
    """
    try:
        # Use provided credentials or defaults
        db_credentials = {
            "name": db_name or f"{pi.get_machine_name()}_db",
            "host": host or "localhost",
            "user": user or "ethoscope",
            "password": password or "ethoscope"
        }

        if dry_run:
            logger.info(f"[DRY RUN] Would refresh cache for {db_credentials['name']} on {db_credentials['host']}")
            return

        logger.info(f"Connecting to MySQL database: {db_credentials['name']} on {db_credentials['host']}")

        # Initiating the cache
        cache = create_metadata_cache(db_credentials, database_type="MySQL")

        # Get backup filename from metadata to ensure consistency
        backup_filename = cache.get_backup_filename()
        logger.info(f"Found backup filename in metadata: {backup_filename}")

        # Use cache system to refresh from database metadata (fully automated)
        cache_filepath = cache.refresh_cache_from_database(backup_filename=backup_filename)

        # Test the get_database_info method we just fixed
        db_info = cache.get_database_info()
        logger.info(f"Database info - Size: {db_info.get('db_size_bytes', 0)} bytes, Tables: {len(db_info.get('table_counts', {}))}")

        logger.info(f"Created cache file: {cache_filepath}")

    except Exception as e:
        logger.error(f"Failed to refresh MySQL cache: {e}")
        import traceback
        logger.debug(traceback.format_exc())


def main():
    """Main function to handle command-line arguments and orchestrate cache refresh."""
    parser = argparse.ArgumentParser(
        description="Refresh database cache JSON files for Ethoscope",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python refresh_cache.py --all          # Refresh all database types
    python refresh_cache.py --sqlite       # Refresh only SQLite databases
    python refresh_cache.py --mysql --host ethoscope004.local # Refresh only MySQL databases
    python refresh_cache.py --dry-run      # Show what would be processed
        """
    )

    # Add mutually exclusive group for database type selection
    db_group = parser.add_mutually_exclusive_group(required=True)
    db_group.add_argument('--sqlite', action='store_true', help='Refresh SQLite database caches')
    db_group.add_argument('--mysql', action='store_true', help='Refresh MySQL database caches')
    db_group.add_argument('--all', action='store_true', help='Refresh all database types')

    parser.add_argument('--dry-run', action='store_true', help='Show what would be processed without making changes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')

    # MySQL connection arguments
    parser.add_argument('--host', help='MySQL host (default: localhost)')
    parser.add_argument('--db-name', help='Database name (default: auto-detect from machine)')
    parser.add_argument('--user', help='MySQL username (default: ethoscope)')
    parser.add_argument('--password', help='MySQL password (default: ethoscope)')

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Ensure cache directory exists
    os.makedirs(CACHE_DIR, exist_ok=True)

    logger.info("Starting database cache refresh")

    # Discover and process databases based on arguments
    if args.sqlite or args.all:
        logger.info("Discovering SQLite databases...")
        sqlite_databases = discover_sqlite_databases()
        logger.info(f"Found {len(sqlite_databases)} SQLite databases")

        for sqlite_db in sqlite_databases:
            refresh_sqlite_cache(sqlite_db, dry_run=args.dry_run)

    if args.mysql or args.all:
        refresh_mysql_cache(
            dry_run=args.dry_run,
            host=args.host,
            db_name=args.db_name,
            user=args.user,
            password=args.password
        )

    logger.info("Database cache refresh completed")


if __name__ == "__main__":
    main()
