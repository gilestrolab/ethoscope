#!/bin/bash

# recover_mariadb_from_sdcard.sh - Recover MariaDB database from an ethoscope SD card
#
# This script mounts an ethoscope's MariaDB data directory from an SD card into a
# Docker container, exports the database, and converts it to SQLite format.
#
# Usage: ./recover_mariadb_from_sdcard.sh <sdcard_mount_point> [output_directory]
#
# Arguments:
#   sdcard_mount_point  - The mount point of the ethoscope SD card (e.g., /run/media/user/...)
#   output_directory    - Optional output directory (default: /ethoscope_data/results)
#
# Requirements:
#   - Docker (user must be in docker group or run with sudo)
#   - sqlite3
#   - awk
#
# Example:
#   ./recover_mariadb_from_sdcard.sh /run/media/gg/5a28ba63-c53d-4d1b-a4a4-3115b9dc250e
#
# Note: The script auto-detects the MariaDB version from the data directory.
#       Newer ethoscopes use MariaDB 10.11, older ones use 10.6.
#
# Author: Ethoscope Project
# Date: 2025-12-07

set -e

# Configuration
CONTAINER_NAME="ethoscope_recovery_db"
DEFAULT_MARIADB_IMAGE="mariadb:10.11"  # Default to 10.11 for newer ethoscopes
MARIADB_PORT=3307
WAIT_TIMEOUT=180  # 3 minutes for crash recovery

# Default output base directory
OUTPUT_BASE_DIR="${2:-/ethoscope_data/results}"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Cleanup function to ensure container is stopped
cleanup() {
    if docker ps -q --filter "name=${CONTAINER_NAME}" 2>/dev/null | grep -q .; then
        log_info "Stopping recovery container..."
        docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    fi
    if docker ps -aq --filter "name=${CONTAINER_NAME}" 2>/dev/null | grep -q .; then
        docker rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    fi
}

# Set trap to cleanup on exit
trap cleanup EXIT

# Check prerequisites
check_prerequisites() {
    log_step "Checking prerequisites..."

    # Check for Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi

    # Check Docker is running
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running or you don't have permission to access it"
        log_info "Try: sudo systemctl start docker"
        log_info "Or add your user to the docker group: sudo usermod -aG docker \$USER"
        exit 1
    fi

    # Check for sqlite3
    if ! command -v sqlite3 &> /dev/null; then
        log_error "sqlite3 is not installed"
        exit 1
    fi

    log_info "All prerequisites met"
}

# Validate SD card mount point
validate_sdcard() {
    local mount_point="$1"

    log_step "Validating SD card mount point..."

    if [ -z "$mount_point" ]; then
        log_error "Usage: $0 <sdcard_mount_point> [output_directory]"
        exit 1
    fi

    if [ ! -d "$mount_point" ]; then
        log_error "Mount point does not exist: $mount_point"
        exit 1
    fi

    local mysql_dir="${mount_point}/var/lib/mysql"
    if [ ! -d "$mysql_dir" ]; then
        log_error "MySQL data directory not found: $mysql_dir"
        log_info "Make sure this is an ethoscope SD card"
        exit 1
    fi

    log_info "Found MySQL data directory: $mysql_dir"
}

# Detect MariaDB version from ib_logfile
detect_mariadb_version() {
    local mount_point="$1"
    local mysql_dir="${mount_point}/var/lib/mysql"

    # Log to stderr so it doesn't get captured in the return value
    log_step "Detecting MariaDB version..." >&2

    # Try to read the ib_logfile header or check for version hints
    # The upgrade_info file contains version information
    if [ -f "${mysql_dir}/mysql_upgrade_info" ]; then
        local version
        version=$(sudo cat "${mysql_dir}/mysql_upgrade_info" 2>/dev/null | head -1)
        if [[ "$version" =~ ^10\.11 ]]; then
            log_info "Detected MariaDB 10.11 from upgrade_info" >&2
            echo "mariadb:10.11"
            return
        elif [[ "$version" =~ ^10\.6 ]]; then
            log_info "Detected MariaDB 10.6 from upgrade_info" >&2
            echo "mariadb:10.6"
            return
        elif [[ "$version" =~ ^10\. ]]; then
            log_info "Detected MariaDB 10.x, using 10.11" >&2
            echo "mariadb:10.11"
            return
        fi
    fi

    # Default to 10.11 for newer ethoscopes
    log_info "Using default MariaDB 10.11" >&2
    echo "mariadb:10.11"
}

# Find ethoscope databases on the SD card
find_ethoscope_databases() {
    local mount_point="$1"
    local mysql_dir="${mount_point}/var/lib/mysql"

    # Log to stderr so it doesn't get captured in the return value
    log_step "Searching for ethoscope databases..." >&2

    # Find directories ending with _db (ethoscope naming convention)
    local db_list
    db_list=$(sudo ls "$mysql_dir" 2>/dev/null | grep '_db$' || true)

    if [ -z "$db_list" ]; then
        log_error "No ethoscope database found (expected pattern: *_db)" >&2
        log_info "Contents of $mysql_dir:" >&2
        sudo ls -la "$mysql_dir" 2>/dev/null >&2 || ls -la "$mysql_dir" 2>/dev/null >&2
        exit 1
    fi

    echo "$db_list"
}

# Start MariaDB container with the SD card's data directory
start_mariadb_container() {
    local mount_point="$1"
    local mariadb_image="$2"
    local mysql_dir="${mount_point}/var/lib/mysql"

    log_step "Starting MariaDB Docker container..."

    # Remove any existing container with the same name
    cleanup

    # Pull the image if not present
    if ! docker image inspect "${mariadb_image}" &> /dev/null; then
        log_info "Pulling MariaDB image: ${mariadb_image}"
        docker pull "${mariadb_image}"
    fi

    # Start the container
    # Using --skip-grant-tables to bypass authentication
    log_info "Starting container with data from: $mysql_dir"
    docker run -d \
        --name "${CONTAINER_NAME}" \
        -v "${mysql_dir}":/var/lib/mysql \
        -p "${MARIADB_PORT}:3306" \
        "${mariadb_image}" \
        --skip-grant-tables

    log_info "Container started, waiting for crash recovery..."
}

# Wait for MariaDB to be ready
wait_for_mariadb() {
    log_step "Waiting for MariaDB to be ready (this may take a few minutes for crash recovery)..."

    local counter=0
    local max_wait=$WAIT_TIMEOUT

    while [ $counter -lt $max_wait ]; do
        # Check if container is still running
        if ! docker ps -q --filter "name=${CONTAINER_NAME}" | grep -q .; then
            log_error "Container stopped unexpectedly"
            log_info "Container logs:"
            docker logs "${CONTAINER_NAME}" 2>&1 | tail -30
            return 1
        fi

        # Try to connect
        if docker exec "${CONTAINER_NAME}" mysqladmin ping -h localhost --silent 2>/dev/null; then
            log_info "MariaDB is ready!"
            return 0
        fi

        counter=$((counter + 1))
        if [ $((counter % 15)) -eq 0 ]; then
            log_info "Still waiting for MariaDB... ($counter seconds)"
            # Show last few log lines for progress
            docker logs "${CONTAINER_NAME}" 2>&1 | tail -3
        fi
        sleep 1
    done

    log_error "Timeout waiting for MariaDB to be ready (${max_wait}s)"
    log_info "Container logs:"
    docker logs "${CONTAINER_NAME}" 2>&1 | tail -30
    return 1
}

# Read metadata from the database using docker exec
read_metadata() {
    local db_name="$1"
    local field="$2"

    docker exec "${CONTAINER_NAME}" mysql -N -e \
        "SELECT value FROM METADATA WHERE field='$field'" "$db_name" 2>/dev/null | head -1
}

# MySQL to SQLite conversion using awk
convert_mysql_to_sqlite() {
    awk '
    BEGIN {
        FS=",$"
        print "PRAGMA synchronous = OFF;"
        print "PRAGMA journal_mode = MEMORY;"
        print "BEGIN TRANSACTION;"
    }

    # CREATE TRIGGER statements have funny commenting
    /^\/\*.*CREATE.*TRIGGER/ {
        gsub( /^.*TRIGGER/, "CREATE TRIGGER" )
        print
        inTrigger = 1
        next
    }

    # The end of CREATE TRIGGER has a stray comment terminator
    /END \*\/;;/ { gsub( /\*\//, "" ); print; inTrigger = 0; next }

    # The rest of triggers just get passed through
    inTrigger != 0 { print; next }

    # Skip other comments
    /^\/\*/ { next }

    # Print all INSERT lines. Single quotes are protected by doubling.
    /INSERT/ {
        gsub( /\\\047/, "\047\047" )
        gsub(/\\n/, "\n")
        gsub(/\\r/, "\r")
        gsub(/\\"/, "\"")
        gsub(/\\\\/, "\\")
        gsub(/\\\032/, "\032")
        print
        next
    }

    # Print the CREATE line as is and capture the table name.
    /^CREATE/ {
        print
        if ( match( $0, /"[^"]+/ ) ) tableName = substr( $0, RSTART+1, RLENGTH-1 )
    }

    # Replace FULLTEXT KEY or any other XXXXX KEY except PRIMARY by KEY
    /^  [^"]+KEY/ && !/^  PRIMARY KEY/ { gsub( /.+KEY/, "  KEY" ) }

    # Get rid of field lengths in KEY lines
    / KEY/ { gsub(/\([0-9]+\)/, "") }

    # Print all fields definition lines except the KEY lines.
    /^  / && !/^(  KEY|\);)/ {
        gsub( /AUTO_INCREMENT|auto_increment/, "" )
        gsub( /(CHARACTER SET|character set) [^ ]+ /, "" )
        gsub( /DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP|default current_timestamp on update current_timestamp/, "" )
        gsub( /(COLLATE|collate) [^ ]+ /, "" )
        gsub(/(ENUM|enum)[^)]+\)/, "text ")
        gsub(/(SET|set)\([^)]+\)/, "text ")
        gsub(/UNSIGNED|unsigned/, "")
        if (prev) print prev ","
        prev = $1
    }

    # KEY lines are extracted from the CREATE block and stored in array for later print
    /^(  KEY|\);)/ {
        if (prev) print prev
        prev=""
        if ($0 == ");"){
            print
        } else {
            if ( match( $0, /"[^"]+/ ) ) indexName = substr( $0, RSTART+1, RLENGTH-1 )
            if ( match( $0, /\([^()]+/ ) ) indexKey = substr( $0, RSTART+1, RLENGTH-1 )
            key[tableName]=key[tableName] "CREATE INDEX \"" tableName "_" indexName "\" ON \"" tableName "\" (" indexKey ");\n"
        }
    }

    # Print all KEY creation lines.
    END {
        for (table in key) printf key[table]
        print "END TRANSACTION;"
    }
    '
}

# Export and convert a single database
export_database() {
    local db_name="$1"

    log_step "Exporting database: $db_name"

    # Get database size for progress indication
    local db_size
    db_size=$(docker exec "${CONTAINER_NAME}" mysql -N -e \
        "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) FROM information_schema.tables WHERE table_schema='$db_name'" 2>/dev/null || echo "unknown")
    log_info "Database size: ${db_size} MB"

    # Read metadata for output path construction
    local backup_filename
    backup_filename=$(read_metadata "$db_name" "backup_filename")

    if [ -z "$backup_filename" ]; then
        log_warn "No backup_filename found in metadata, using database name"
        backup_filename="${db_name}.db"
    fi

    log_info "Backup filename from metadata: $backup_filename"

    # Parse the backup filename to extract date/time and machine_id
    # Format: YYYY-MM-DD_HH-MM-SS_machine_id.db
    local output_dir
    local output_file

    if [[ "$backup_filename" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2})_([0-9]{2}-[0-9]{2}-[0-9]{2})_(.+)\.db$ ]]; then
        local date_part="${BASH_REMATCH[1]}"
        local time_part="${BASH_REMATCH[2]}"
        local machine_id="${BASH_REMATCH[3]}"

        log_info "Parsed: date=$date_part, time=$time_part, machine_id=$machine_id"

        # Get machine name from database name (remove _db suffix)
        local machine_name="${db_name%_db}"

        # Construct output path: /ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/
        output_dir="${OUTPUT_BASE_DIR}/${machine_id}/${machine_name}/${date_part}_${time_part}"
        output_file="${output_dir}/${backup_filename}"
    else
        log_warn "Could not parse backup_filename format, using simple path"
        local machine_name="${db_name%_db}"
        local timestamp=$(date +%Y-%m-%d_%H-%M-%S)
        output_dir="${OUTPUT_BASE_DIR}/${machine_name}/${timestamp}"
        output_file="${output_dir}/${db_name}.db"
    fi

    log_info "Output directory: $output_dir"
    log_info "Output file: $output_file"

    # Create output directory
    mkdir -p "$output_dir"

    # Check if output file already exists
    if [ -f "$output_file" ]; then
        log_warn "Output file already exists: $output_file"
        read -p "Overwrite? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Skipping database: $db_name"
            return 0
        fi
        rm -f "$output_file"
    fi

    # Perform the conversion
    log_info "Starting database export and conversion..."
    log_info "This may take several minutes for large databases..."

    # Run mysqldump inside container and convert to SQLite
    docker exec "${CONTAINER_NAME}" mysqldump \
        --compatible=ansi \
        --skip-extended-insert \
        --compact \
        "$db_name" 2>/dev/null | \
        convert_mysql_to_sqlite | \
        sqlite3 "$output_file"

    # Verify the conversion
    if [ -f "$output_file" ]; then
        local sqlite_size
        sqlite_size=$(du -h "$output_file" | cut -f1)

        # Quick sanity check - verify tables exist
        local table_count
        table_count=$(sqlite3 "$output_file" "SELECT COUNT(*) FROM sqlite_master WHERE type='table'" 2>/dev/null || echo "0")

        if [ "$table_count" -gt 0 ]; then
            log_info "Conversion successful!"
            log_info "Output file: $output_file"
            log_info "SQLite file size: $sqlite_size"
            log_info "Tables in SQLite database: $table_count"

            # Show ROI table counts
            local roi_tables
            roi_tables=$(sqlite3 "$output_file" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'ROI_%'" 2>/dev/null || echo "0")
            log_info "ROI tables found: $roi_tables"
        else
            log_error "Conversion may have failed - no tables found in output"
            return 1
        fi
    else
        log_error "Output file was not created"
        return 1
    fi

    return 0
}

# Main execution
main() {
    local mount_point="$1"

    echo ""
    log_info "=============================================="
    log_info "Ethoscope SD Card Database Recovery Tool"
    log_info "=============================================="
    echo ""

    # Check prerequisites
    check_prerequisites

    # Validate SD card
    validate_sdcard "$mount_point"

    # Detect MariaDB version
    local mariadb_image
    mariadb_image=$(detect_mariadb_version "$mount_point")

    # Find databases
    local db_list
    db_list=$(find_ethoscope_databases "$mount_point")

    log_info "Found database(s):"
    echo "$db_list" | while read -r db; do
        echo "  - $db"
    done
    echo ""

    # Start MariaDB container
    start_mariadb_container "$mount_point" "$mariadb_image"

    # Wait for MariaDB to be ready
    if ! wait_for_mariadb; then
        log_error "Failed to start MariaDB. You may need to try a different MariaDB version."
        log_info "Try setting MARIADB_IMAGE environment variable:"
        log_info "  MARIADB_IMAGE=mariadb:10.6 $0 $mount_point"
        exit 1
    fi

    # Export each database
    local success_count=0
    local fail_count=0

    while read -r db_name; do
        if [ -n "$db_name" ]; then
            echo ""
            if export_database "$db_name"; then
                success_count=$((success_count + 1))
            else
                fail_count=$((fail_count + 1))
            fi
        fi
    done <<< "$db_list"

    echo ""
    log_info "=============================================="
    log_info "Recovery complete!"
    log_info "Successful: $success_count, Failed: $fail_count"
    log_info "=============================================="
}

# Show help
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Usage: $0 <sdcard_mount_point> [output_directory]"
    echo ""
    echo "Recover MariaDB database from an ethoscope SD card and convert to SQLite."
    echo ""
    echo "Arguments:"
    echo "  sdcard_mount_point  The mount point of the ethoscope SD card"
    echo "  output_directory    Output directory (default: /ethoscope_data/results)"
    echo ""
    echo "Environment Variables:"
    echo "  MARIADB_IMAGE       Override the MariaDB Docker image (default: auto-detect)"
    echo ""
    echo "Example:"
    echo "  $0 /run/media/gg/5a28ba63-c53d-4d1b-a4a4-3115b9dc250e"
    echo ""
    echo "  # Force specific MariaDB version"
    echo "  MARIADB_IMAGE=mariadb:10.6 $0 /run/media/gg/sdcard"
    echo ""
    echo "Requirements:"
    echo "  - Docker (user must be in docker group or run with sudo)"
    echo "  - sqlite3"
    echo ""
    echo "Notes:"
    echo "  - The script auto-detects MariaDB version from the data directory"
    echo "  - Crash recovery may take several minutes for large databases"
    echo "  - Output follows ethoscope convention:"
    echo "    /ethoscope_data/results/{machine_id}/{machine_name}/{datetime}/"
    exit 0
fi

# Allow override via environment variable
if [ -n "$MARIADB_IMAGE" ]; then
    DEFAULT_MARIADB_IMAGE="$MARIADB_IMAGE"
fi

# Run main function
main "$@"
