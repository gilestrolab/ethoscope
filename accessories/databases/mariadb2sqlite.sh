#!/bin/bash

# mariadb2sqlite.sh - Convert ethoscope MariaDB database to SQLite format
#
# This script automatically detects the MariaDB database on an ethoscope device,
# reads the metadata to determine the proper output path and filename, and
# converts the database to SQLite format.
#
# Usage: ./mariadb2sqlite.sh [output_directory]
#
# If output_directory is not specified, uses /ethoscope_data/results
#
# Requirements:
#   - mariadb/mysqldump
#   - sqlite3
#   - awk
#
# Author: Ethoscope Project
# Date: 2025-11-27

set -e

# Default output base directory
OUTPUT_BASE_DIR="${1:-/ethoscope_data/results}"

# MariaDB credentials (standard ethoscope configuration)
# Can be overridden via environment variables (use empty string for no password)
DB_USER="${DB_USER-ethoscope}"
DB_PASS="${DB_PASS-ethoscope}"
DB_HOST="${DB_HOST-localhost}"
DB_PORT="${DB_PORT-3306}"

# Build password argument (empty password = no -p flag)
if [ -n "$DB_PASS" ]; then
    DB_PASS_ARG="-p${DB_PASS}"
else
    DB_PASS_ARG=""
fi

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

# Function to find the ethoscope database
find_ethoscope_db() {
    log_info "Searching for ethoscope database..."

    # List all databases and find the one ending with _db (ethoscope naming convention)
    local db_list
    db_list=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" $DB_PASS_ARG -N -e "SHOW DATABASES" 2>/dev/null | grep '_db$' | grep -v 'information_schema\|mysql\|performance_schema' || true)

    if [ -z "$db_list" ]; then
        log_error "No ethoscope database found (expected pattern: *_db)"
        exit 1
    fi

    # Count databases found
    local db_count
    db_count=$(echo "$db_list" | wc -l)

    if [ "$db_count" -gt 1 ]; then
        log_warn "Multiple databases found:"
        echo "$db_list"
        log_info "Using the first one. Specify DB_NAME environment variable to override."
        db_list=$(echo "$db_list" | head -1)
    fi

    echo "$db_list"
}

# Function to read metadata from the database
read_metadata() {
    local db_name="$1"
    local field="$2"

    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" $DB_PASS_ARG -N -e \
        "SELECT value FROM METADATA WHERE field='$field'" "$db_name" 2>/dev/null | head -1
}

# Function to check if database has data
check_database_has_data() {
    local db_name="$1"

    # Check if ROI tables exist and have data
    local table_count
    table_count=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" $DB_PASS_ARG -N -e \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$db_name' AND table_name LIKE 'ROI_%'" 2>/dev/null || echo "0")

    if [ "$table_count" -eq 0 ]; then
        log_error "Database has no ROI tables - appears to be empty or invalid"
        return 1
    fi

    log_info "Found $table_count ROI tables in database"
    return 0
}

# MySQL to SQLite conversion using awk (adapted from sql2sqlite.sh)
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
        if ( match( $0, /\"[^\"]+/ ) ) tableName = substr( $0, RSTART+1, RLENGTH-1 )
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
            if ( match( $0, /\"[^"]+/ ) ) indexName = substr( $0, RSTART+1, RLENGTH-1 )
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

# Main execution
main() {
    log_info "MariaDB to SQLite converter for Ethoscope"
    log_info "=========================================="

    # Check for required tools
    for cmd in mysql mysqldump sqlite3 awk; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "Required command '$cmd' not found"
            exit 1
        fi
    done

    # Allow override via environment variable
    local db_name="${DB_NAME:-}"

    if [ -z "$db_name" ]; then
        db_name=$(find_ethoscope_db)
    fi

    log_info "Using database: $db_name"

    # Verify database has data
    if ! check_database_has_data "$db_name"; then
        exit 1
    fi

    # Read metadata for output path construction
    local backup_filename
    backup_filename=$(read_metadata "$db_name" "backup_filename")

    if [ -z "$backup_filename" ]; then
        log_warn "No backup_filename found in metadata, using database name"
        backup_filename="${db_name%.db}.db"
        if [[ ! "$backup_filename" == *.db ]]; then
            backup_filename="${backup_filename}.db"
        fi
    fi

    log_info "Backup filename from metadata: $backup_filename"

    # Parse the backup filename to extract date/time and machine_id
    # Format: YYYY-MM-DD_HH-MM-SS_machine_id.db
    if [[ "$backup_filename" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2})_([0-9]{2}-[0-9]{2}-[0-9]{2})_(.+)\.db$ ]]; then
        local date_part="${BASH_REMATCH[1]}"
        local time_part="${BASH_REMATCH[2]}"
        local machine_id="${BASH_REMATCH[3]}"

        log_info "Parsed: date=$date_part, time=$time_part, machine_id=$machine_id"

        # Get machine name from database name (remove _db suffix)
        local machine_name="${db_name%_db}"

        # Construct output path: /ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/
        local output_dir="${OUTPUT_BASE_DIR}/${machine_id}/${machine_name}/${date_part}_${time_part}"
        local output_file="${output_dir}/${backup_filename}"
    else
        log_warn "Could not parse backup_filename format, using simple path"
        local machine_name="${db_name%_db}"
        local output_dir="${OUTPUT_BASE_DIR}/${machine_name}"
        local output_file="${output_dir}/${backup_filename}"
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
            log_info "Aborted"
            exit 0
        fi
        rm -f "$output_file"
    fi

    # Perform the conversion
    log_info "Starting database conversion..."
    log_info "This may take several minutes depending on database size..."

    # Get database size for progress indication
    local db_size
    db_size=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" $DB_PASS_ARG -N -e \
        "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) FROM information_schema.tables WHERE table_schema='$db_name'" 2>/dev/null || echo "unknown")
    log_info "Database size: ${db_size} MB"

    # Perform mysqldump and convert to SQLite
    mysqldump --compatible=ansi --skip-extended-insert --compact \
        -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" $DB_PASS_ARG "$db_name" 2>/dev/null | \
        convert_mysql_to_sqlite | \
        sqlite3 "$output_file"

    # Verify the conversion
    if [ -f "$output_file" ]; then
        local sqlite_size
        sqlite_size=$(du -h "$output_file" | cut -f1)

        # Quick sanity check - verify METADATA table exists
        local metadata_check
        metadata_check=$(sqlite3 "$output_file" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='METADATA'" 2>/dev/null || echo "0")

        if [ "$metadata_check" -eq 1 ]; then
            log_info "Conversion successful!"
            log_info "Output file: $output_file"
            log_info "SQLite file size: $sqlite_size"

            # Show table counts
            local table_count
            table_count=$(sqlite3 "$output_file" "SELECT COUNT(*) FROM sqlite_master WHERE type='table'" 2>/dev/null || echo "unknown")
            log_info "Tables in SQLite database: $table_count"
        else
            log_error "Conversion may have failed - METADATA table not found"
            exit 1
        fi
    else
        log_error "Output file was not created"
        exit 1
    fi

    log_info "Done!"
}

# Run main function
main "$@"
