#!/bin/bash
# Script to check integrity of all ethoscope databases

# Load environment variables if available
if [ -f /etc/ethoscope/environment ]; then
    source /etc/ethoscope/environment
fi

# Default settings (can be overridden by environment variables)
DATA_DIR="${ETHOSCOPE_RESULTS_DIR:-/ethoscope_data/results}"
DEEP=false
FORCE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --deep)
            DEEP=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --path)
            DATA_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --deep           Perform thorough integrity_check (slower)"
            echo "  --force          Re-check databases even if log file exists"
            echo "  --path <dir>     Specify custom data directory (default: /ethoscope_data/results)"
            echo "  --help           Show this help message"
            echo ""
            echo "Default: quick_check (faster)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate data directory
if [ ! -d "$DATA_DIR" ]; then
    echo "Error: Directory not found: $DATA_DIR"
    exit 1
fi

# Set check type
if [ "$DEEP" = true ]; then
    CHECK_TYPE="deep"
    CHECK_CMD="PRAGMA integrity_check;"
else
    CHECK_TYPE="quick"
    CHECK_CMD="PRAGMA quick_check;"
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OK_LOG="${DATA_DIR}/databases_ok_${CHECK_TYPE}_${TIMESTAMP}.csv"
CORRUPTED_LOG="${DATA_DIR}/databases_corrupted_${CHECK_TYPE}_${TIMESTAMP}.csv"

# Create CSV headers
echo "filepath,filesize,check_result,log_file" > "$OK_LOG"
echo "filepath,filesize,error_message,log_file" > "$CORRUPTED_LOG"

# Counter for statistics
total=0
corrupted=0
ok=0
skipped=0

echo "Starting database integrity checks ($CHECK_TYPE)..."
echo "========================================"

# Find all .db files
while IFS= read -r db_file; do
    ((total++))

    # Get directory and basename
    db_dir=$(dirname "$db_file")
    db_name=$(basename "$db_file")
    log_file="${db_dir}/.${db_name}.${CHECK_TYPE}_check.log"

    # Check if log file exists and skip if not forced
    if [ -f "$log_file" ] && [ "$FORCE" = false ]; then
        echo "Skipping: $db_file (log exists)"
        ((skipped++))
        continue
    fi

    echo "Checking: $db_file"

    # Get file size
    filesize=$(stat -f%z "$db_file" 2>/dev/null || stat -c%s "$db_file" 2>/dev/null)

    # Run integrity check
    result=$(sqlite3 "$db_file" "$CHECK_CMD" 2>&1)

    # Create log file with results
    {
        echo "Database: $db_file"
        echo "Check Type: $CHECK_TYPE"
        echo "Check Date: $(date)"
        echo "File Size: $filesize bytes"
        echo "---"
        echo "Result: $result"
    } > "$log_file"

    if [ "$result" = "ok" ]; then
        echo "  ✓ OK"
        echo "\"$db_file\",$filesize,ok,\"$log_file\"" >> "$OK_LOG"
        ((ok++))
    else
        echo "  ✗ CORRUPTED"
        # Escape quotes in error message for CSV
        error_msg=$(echo "$result" | tr '\n' ' ' | sed 's/"/""/g')
        echo "\"$db_file\",$filesize,\"$error_msg\",\"$log_file\"" >> "$CORRUPTED_LOG"
        ((corrupted++))
    fi
done < <(find "$DATA_DIR" -name "*.db" -type f)

# Summary
echo ""
echo "========================================"
echo "Summary:"
echo "  Total databases found: $total"
echo "  Checked: $((ok + corrupted))"
echo "  Skipped: $skipped"
echo "  OK: $ok"
echo "  Corrupted: $corrupted"
echo ""
echo "Results saved to:"
echo "  OK databases: $OK_LOG"
echo "  Corrupted databases: $CORRUPTED_LOG"
echo ""
echo "Individual log files saved in each database directory"
