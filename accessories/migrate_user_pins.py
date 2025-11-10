#!/usr/bin/env python3
"""
PIN Migration Utility for Ethoscope Node

Migrates existing plaintext PINs to secure hashed format using bcrypt.
This utility should be run before enabling the new authentication system.

Usage:
    python migrate_user_pins.py --help
    python migrate_user_pins.py --dry-run
    python migrate_user_pins.py --config-dir /etc/ethoscope
"""

import sys
import logging
import argparse
from pathlib import Path

# Add the src directory to Python path to import ethoscope modules
sys.path.insert(0, str(Path(__file__).parent.parent / 'src' / 'node'))

try:
    from ethoscope_node.utils.configuration import EthoscopeConfiguration
except ImportError as e:
    print(f"Error importing ethoscope modules: {e}")
    print("Make sure you're running this from the ethoscope project root directory")
    sys.exit(1)


def setup_logging(verbose=False):
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def check_bcrypt_availability():
    """Check if bcrypt library is available."""
    try:
        import bcrypt
        return True
    except ImportError:
        return False


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description='Migrate plaintext PINs to secure hashed format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Check what would be migrated (dry run)
    python migrate_user_pins.py --dry-run

    # Perform actual migration
    python migrate_user_pins.py

    # Use custom config directory
    python migrate_user_pins.py --config-dir /custom/path
        """
    )
    parser.add_argument(
        '--config-dir',
        default='/etc/ethoscope',
        help='Configuration directory path (default: /etc/ethoscope)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force migration even if bcrypt is not available'
    )

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        # Check bcrypt availability
        if not check_bcrypt_availability():
            if not args.force:
                logger.error("bcrypt library not available. Install with: pip install bcrypt")
                logger.error("Or use --force to migrate with fallback hashing (less secure)")
                return 1
            else:
                logger.warning("bcrypt not available, using fallback hashing (less secure)")
        else:
            logger.info("bcrypt library available - using secure hashing")

        # Initialize configuration with custom config directory
        config_file = f"{args.config_dir}/ethoscope.conf"
        logger.info(f"Using configuration file: {config_file}")

        config = EthoscopeConfiguration(config_file=config_file)

        # Perform migration
        if args.dry_run:
            logger.info("=== DRY RUN MODE ===")
            migrated_count = config.migrate_user_pins(dry_run=True)
            if migrated_count > 0:
                logger.info(f"Would migrate {migrated_count} plaintext PINs")
                logger.info("Run without --dry-run to perform actual migration")
            else:
                logger.info("No plaintext PINs found to migrate")
        else:
            logger.info("=== PERFORMING PIN MIGRATION ===")
            migrated_count = config.migrate_user_pins(dry_run=False)
            if migrated_count > 0:
                logger.info(f"Successfully migrated {migrated_count} plaintext PINs")
                logger.info("PIN migration completed successfully!")
                logger.info("You can now safely enable the new authentication system")
            else:
                logger.info("No plaintext PINs were found to migrate")

        return 0

    except KeyboardInterrupt:
        logger.info("Migration cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        if args.verbose:
            import traceback
            logger.debug(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())
