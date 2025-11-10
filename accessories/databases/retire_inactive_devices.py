#!/usr/bin/env python3
"""
Cron script to retire inactive devices from the Ethoscope database.

This script retires devices that haven't been seen for more than the specified
number of days (default: 90 days). It's designed to be run periodically via cron.

Usage:
    python retire_inactive_devices.py [--threshold-days DAYS] [--config-dir DIR] [--dry-run]

Example crontab entry (run daily at 3 AM):
    0 3 * * * /usr/bin/python3 /path/to/retire_inactive_devices.py

Author: Giorgio Gilestro
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta

# Add the node package to the Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(script_dir, '..', '..', 'src', 'node')
sys.path.insert(0, project_root)

try:
    from ethoscope_node.utils.etho_db import ExperimentalDB
except ImportError as e:
    print(f"Error importing ExperimentalDB: {e}")
    print("Make sure you're running this script from the correct directory")
    sys.exit(1)


def setup_logging(debug: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    logging.basicConfig(level=level, format=format_string)

    if debug:
        logging.info("Debug logging enabled")


def main():
    """Main entry point for the retire inactive devices script."""
    parser = argparse.ArgumentParser(
        description='Retire inactive Ethoscope devices from the database'
    )
    parser.add_argument(
        '--threshold-days',
        type=int,
        default=90,
        help='Number of days after which to retire inactive devices (default: 90)'
    )
    parser.add_argument(
        '--config-dir',
        type=str,
        default='/etc/ethoscope',
        help='Path to configuration directory (default: /etc/ethoscope)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be retired without actually retiring devices'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.debug)
    logger = logging.getLogger('RetireInactiveDevices')

    try:
        # Initialize database connection
        logger.info(f"Connecting to database in {args.config_dir}")
        database = ExperimentalDB(args.config_dir)

        if args.dry_run:
            logger.info(f"DRY RUN: Would retire devices inactive for >{args.threshold_days} days")

            # Get devices that would be retired
            cutoff_date = datetime.now() - timedelta(days=args.threshold_days)

            # Get all active devices
            sql_get_active = "SELECT ethoscope_id, ethoscope_name, last_seen FROM ethoscopes WHERE active = 1"
            active_devices = database.executeSQL(sql_get_active)

            if isinstance(active_devices, list):
                devices_to_retire = []
                for device in active_devices:
                    ethoscope_id = device[0]
                    ethoscope_name = device[1]
                    last_seen = device[2]

                    try:
                        # Parse timestamp (simplified)
                        if isinstance(last_seen, str):
                            last_seen_dt = datetime.strptime(last_seen.split('.')[0], '%Y-%m-%d %H:%M:%S')
                        else:
                            last_seen_dt = datetime.fromtimestamp(float(last_seen))

                        if last_seen_dt < cutoff_date:
                            devices_to_retire.append((ethoscope_id, ethoscope_name, last_seen))
                    except:
                        devices_to_retire.append((ethoscope_id, ethoscope_name, last_seen))

                if devices_to_retire:
                    logger.info(f"Would retire {len(devices_to_retire)} devices:")
                    for device_id, device_name, last_seen in devices_to_retire:
                        logger.info(f"  - {device_name} ({device_id}) - last seen: {last_seen}")
                else:
                    logger.info("No devices would be retired")
            else:
                logger.info("No active devices found")

        else:
            # Actually retire devices
            logger.info(f"Retiring devices inactive for >{args.threshold_days} days")
            retired_count = database.retire_inactive_devices(args.threshold_days)
            logger.info(f"Successfully retired {retired_count} inactive devices")

            if retired_count > 0:
                # Also run cleanup operations
                logger.info("Running additional database cleanup operations...")

                # Clean up stale busy devices
                cleaned_busy = database.cleanup_stale_busy_devices()
                logger.info(f"Cleaned up {cleaned_busy} stale busy devices")

                # Clean up offline busy devices
                cleaned_offline_busy = database.cleanup_offline_busy_devices()
                logger.info(f"Cleaned up {cleaned_offline_busy} offline busy devices")

                # Purge unnamed devices
                purged_unnamed = database.purge_unnamed_devices()
                logger.info(f"Purged {purged_unnamed} unnamed/invalid devices")

        logger.info("Script completed successfully")

    except Exception as e:
        logger.error(f"Error running retire inactive devices script: {e}")
        if args.debug:
            import traceback
            logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()
