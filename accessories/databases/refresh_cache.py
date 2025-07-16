#!/usr/bin/env python3
"""
Database Cache Refresh Script for Ethoscope

This script refreshes all database cache JSON files by extracting metadata directly from
databases and creating properly timestamped cache files. It supports both SQLite and MySQL
databases and ensures cache filenames reflect actual database metadata timestamps.

Usage:
    python refresh_cache.py --all          # Refresh all database types
    python refresh_cache.py --sqlite       # Refresh only SQLite databases
    python refresh_cache.py --mysql        # Refresh only MySQL databases
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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from ethoscope.utils.cache import (
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


def get_mysql_experiment_start_time(db_name):
    """
    Get the actual experiment start time from MySQL START_EVENTS table.
    
    Args:
        db_name (str): MySQL database name
        
    Returns:
        int: Experiment start timestamp, or None if not found
    """
    try:
        with mysql.connector.connect(
            host='localhost',
            user=MYSQL_CREDENTIALS["user"],
            password=MYSQL_CREDENTIALS["password"],
            database=db_name,
            charset='latin1',
            use_unicode=True,
            connect_timeout=10
        ) as conn:
            cursor = conn.cursor()
            
            # Query START_EVENTS table for graceful_start events
            cursor.execute("""
                SELECT t FROM START_EVENTS 
                WHERE event = 'graceful_start' 
                ORDER BY t ASC 
                LIMIT 1
            """)
            result = cursor.fetchone()
            
            if result:
                return result[0]
            else:
                logger.warning(f"No graceful_start event found in {db_name}")
                return None
                
    except mysql.connector.Error as e:
        logger.error(f"Failed to get experiment start time from {db_name}: {e}")
        return None


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
            
            # Extract timestamp from directory name (YYYY-MM-DD_HH-MM-SS format)
            try:
                timestamp = time.mktime(time.strptime(date_time_dir, '%Y-%m-%d_%H-%M-%S'))
            except ValueError:
                logger.warning(f"Could not parse timestamp from directory {date_time_dir}")
                continue
            
            # Verify database file exists and is accessible
            if not os.path.exists(db_path):
                logger.warning(f"Database file does not exist: {db_path}")
                continue
                
            sqlite_databases.append({
                'path': db_path,
                'machine_id': machine_id,
                'machine_name': machine_name,
                'timestamp': timestamp,
                'backup_filename': db_filename
            })
            
        except Exception as e:
            logger.error(f"Error processing SQLite database {db_path}: {e}")
            continue
    
    return sqlite_databases


def discover_mysql_databases():
    """
    Discover MySQL databases using machine name pattern.
    
    Returns:
        list: List of dictionaries with database information
    """
    mysql_databases = []
    
    try:
        machine_name = pi.get_machine_name()
        db_name = f"{machine_name}_db"
        
        # Test connection to the database
        with mysql.connector.connect(
            host='localhost',
            user=MYSQL_CREDENTIALS["user"],
            password=MYSQL_CREDENTIALS["password"],
            database=db_name,
            charset='latin1',
            use_unicode=True,
            connect_timeout=10
        ) as conn:
            logger.info(f"Found MySQL database: {db_name}")
            
            # Get actual experiment start time
            experiment_start_time = get_mysql_experiment_start_time(db_name)
            
            if experiment_start_time:
                mysql_databases.append({
                    'name': db_name,
                    'machine_name': machine_name,
                    'timestamp': experiment_start_time
                })
            else:
                logger.warning(f"Could not determine experiment start time for {db_name}")
                
    except mysql.connector.Error as e:
        logger.error(f"Failed to connect to MySQL database: {e}")
    
    return mysql_databases


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
        timestamp = sqlite_db_info['timestamp']
        
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
        
        # Get database metadata
        db_metadata = cache.get_metadata(tracking_start_time=timestamp)
        
        # Extract experimental metadata from database
        experimental_metadata = cache.get_experimental_metadata()
        
        # Prepare experiment info
        experiment_info = {
            "date_time": timestamp,
            "backup_filename": sqlite_db_info['backup_filename'],
            "user": experimental_metadata.get("user", "unknown"),
            "location": experimental_metadata.get("location", "unknown"),
            "result_writer_type": "SQLiteResultWriter",
            "sqlite_source_path": db_path
        }
        
        # Store experiment info in cache
        cache.store_experiment_info(timestamp, experiment_info)
        
        # Generate cache filename
        ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(timestamp))
        cache_filename = f"db_metadata_{ts_str}_{machine_name}_db.json"
        cache_filepath = os.path.join(CACHE_DIR, cache_filename)
        
        logger.info(f"Created cache file: {cache_filepath}")
        
    except Exception as e:
        logger.error(f"Failed to refresh SQLite cache for {sqlite_db_info['path']}: {e}")


def refresh_mysql_cache(mysql_db_info, dry_run=False):
    """
    Refresh cache for a single MySQL database.
    
    Args:
        mysql_db_info (dict): MySQL database information
        dry_run (bool): If True, only show what would be done
    """
    try:
        db_name = mysql_db_info['name']
        machine_name = mysql_db_info['machine_name']
        timestamp = mysql_db_info['timestamp']
        
        logger.info(f"Processing MySQL database: {db_name}")
        
        if dry_run:
            logger.info(f"[DRY RUN] Would refresh cache for {db_name}")
            return
        
        # Create MySQL metadata cache
        mysql_credentials = MYSQL_CREDENTIALS.copy()
        mysql_credentials["name"] = db_name
        
        cache = create_metadata_cache(
            db_credentials=mysql_credentials,
            device_name=machine_name,
            cache_dir=CACHE_DIR,
            database_type="MySQL"
        )
        
        # Get database metadata
        db_metadata = cache.get_metadata(tracking_start_time=timestamp)
        
        # Extract experimental metadata from database
        experimental_metadata = cache.get_experimental_metadata()
        
        # Generate backup filename from timestamp
        ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(timestamp))
        backup_filename = f"{ts_str}_{pi.get_machine_id()}.db"
        
        # Prepare experiment info
        experiment_info = {
            "date_time": timestamp,
            "backup_filename": backup_filename,
            "user": experimental_metadata.get("user", "unknown"),
            "location": experimental_metadata.get("location", "unknown"),
            "result_writer_type": "MySQLResultWriter"
        }
        
        # Store experiment info in cache
        cache.store_experiment_info(timestamp, experiment_info)
        
        # Generate cache filename
        cache_filename = f"db_metadata_{ts_str}_{machine_name}_db.json"
        cache_filepath = os.path.join(CACHE_DIR, cache_filename)
        
        logger.info(f"Created cache file: {cache_filepath}")
        
    except Exception as e:
        logger.error(f"Failed to refresh MySQL cache for {mysql_db_info['name']}: {e}")


def main():
    """Main function to handle command-line arguments and orchestrate cache refresh."""
    parser = argparse.ArgumentParser(
        description="Refresh database cache JSON files for Ethoscope",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python refresh_cache.py --all          # Refresh all database types
    python refresh_cache.py --sqlite       # Refresh only SQLite databases
    python refresh_cache.py --mysql        # Refresh only MySQL databases
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
        logger.info("Discovering MySQL databases...")
        mysql_databases = discover_mysql_databases()
        logger.info(f"Found {len(mysql_databases)} MySQL databases")
        
        for mysql_db in mysql_databases:
            refresh_mysql_cache(mysql_db, dry_run=args.dry_run)
    
    logger.info("Database cache refresh completed")


if __name__ == "__main__":
    main()