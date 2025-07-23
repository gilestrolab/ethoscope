#!/bin/bash

# Test runner for append functionality tests
# This script runs all tests related to the database append feature

echo "==================================="
echo "Running Ethoscope Append Tests"
echo "==================================="

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/../../.."

# Activate virtual environment if it exists
if [ -f "$HOME/Data/virtual_envs/python/ethoscope/bin/activate" ]; then
    echo "Activating virtual environment..."
    source "$HOME/Data/virtual_envs/python/ethoscope/bin/activate"
fi

# Change to project root directory
cd "$PROJECT_ROOT"

# Add project to Python path
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "Python path: $PYTHONPATH"
echo "Current directory: $(pwd)"
echo ""

# Run append functionality tests
echo "1. Running append functionality unit tests..."
python -m pytest ethoscope/tests/unit/test_append_functionality.py -v --tb=short

echo ""
echo "2. Running database cache tests..."
python -m pytest ethoscope/tests/unit/test_database_cache.py -v --tb=short

echo ""
echo "3. Running related monitor tests..."
python -m pytest ethoscope/tests/unit/test_monitor.py -v --tb=short -k "time"

echo ""
echo "==================================="
echo "Running append functionality integration test..."
echo "==================================="

# Create a simple integration test script
cat > /tmp/test_append_integration.py << 'EOF'
"""
Simple integration test for append functionality.
"""
import sys
import os
import tempfile
import sqlite3
import time

# Add project to path
sys.path.insert(0, os.getcwd())

try:
    from ethoscope.utils.io import SQLiteResultWriter
    from ethoscope.core.monitor import Monitor
    from ethoscope.core.roi import ROI
    from unittest.mock import Mock
    
    print("✓ Successfully imported required modules")
    
    # Test 1: SQLite append functionality
    print("\nTesting SQLite append functionality...")
    
    # Create test database
    fd, temp_db = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    try:
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        # Create ROI table with test data
        cursor.execute("""
            CREATE TABLE ROI_1 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                t INTEGER,
                x REAL,
                y REAL
            )
        """)
        
        cursor.execute("INSERT INTO ROI_1 (t, x, y) VALUES (?, ?, ?)", (5000, 10.5, 20.5))
        cursor.execute("INSERT INTO ROI_1 (t, x, y) VALUES (?, ?, ?)", (10000, 15.5, 25.5))
        
        conn.commit()
        conn.close()
        
        # Create mock ROI
        roi = Mock()
        roi.idx = 1
        roi.get_feature_dict = Mock(return_value={
            "idx": 1, "value": 255, "x": 10, "y": 10, "w": 100, "h": 100
        })
        
        # Test SQLite writer append
        db_credentials = {"name": temp_db}
        writer = SQLiteResultWriter(
            db_credentials=db_credentials,
            rois=[roi],
            erase_old_db=False
        )
        
        last_timestamp = writer.append()
        print(f"✓ SQLite append returned timestamp: {last_timestamp}")
        
        assert last_timestamp == 10000, f"Expected 10000, got {last_timestamp}"
        print("✓ SQLite append test passed")
        
    finally:
        if os.path.exists(temp_db):
            os.unlink(temp_db)
    
    # Test 2: Monitor with time offset
    print("\nTesting Monitor with time offset...")
    
    mock_camera = Mock()
    mock_camera.__iter__ = Mock(return_value=iter([
        (0, Mock()),
        (1000, Mock()),
        (2000, Mock()),
    ]))
    
    mock_tracker_class = Mock()
    
    time_offset = 10000
    monitor = Monitor(
        camera=mock_camera,
        tracker_class=mock_tracker_class,
        rois=[roi],
        time_offset=time_offset
    )
    
    assert monitor._time_offset == time_offset, f"Expected {time_offset}, got {monitor._time_offset}"
    assert monitor._last_time_stamp == time_offset, f"Expected {time_offset}, got {monitor._last_time_stamp}"
    
    print(f"✓ Monitor initialized with time_offset: {time_offset}")
    print("✓ Monitor time offset test passed")
    
    print("\n=== All integration tests passed! ===")
    
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOF

# Run the integration test
echo "Running integration test..."
python /tmp/test_append_integration.py

# Clean up
rm -f /tmp/test_append_integration.py

echo ""
echo "==================================="
echo "Append tests completed!"
echo "==================================="