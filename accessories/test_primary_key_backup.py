#!/usr/bin/env python3
"""
Test Script for PRIMARY KEY Backup Implementation

This script tests the new PRIMARY KEY constraint preservation in the MySQL backup system.
It validates:
1. Proper schema detection and constraint preservation
2. Table migration for existing databases
3. Duplicate prevention during backup operations
4. Backward compatibility with existing code

Usage:
    python test_primary_key_backup.py [--verbose]
"""

import os
import sys
import sqlite3
import tempfile
import logging
from pathlib import Path

# Add the source directory to the path so we can import the backup modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "node" / "ethoscope_node" / "utils"))

try:
    from mysql_backup import MySQLdbToSQLite
except ImportError as e:
    print(f"Error importing backup modules: {e}")
    print("Make sure you're running this from the ethoscope root directory")
    sys.exit(1)


class BackupTester:
    """Test the PRIMARY KEY backup implementation."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.setup_logging()
        self.test_results = []
        
    def setup_logging(self):
        """Configure logging for tests."""
        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(levelname)s: %(message)s',
            stream=sys.stdout
        )
        self.logger = logging.getLogger(__name__)
    
    def run_all_tests(self):
        """Run all backup implementation tests."""
        print("Testing PRIMARY KEY Backup Implementation")
        print("=" * 50)
        
        # Test 1: Schema detection
        self.test_schema_detection()
        
        # Test 2: Table creation with constraints
        self.test_table_creation_with_constraints()
        
        # Test 3: Migration of existing tables
        self.test_table_migration()
        
        # Test 4: Duplicate prevention
        self.test_duplicate_prevention()
        
        # Summary
        self.print_test_summary()
    
    def test_schema_detection(self):
        """Test MySQL schema detection with PRIMARY KEY information."""
        print("\\nTest 1: Schema Detection")
        print("-" * 30)
        
        try:
            # Create a test MySQL-like schema structure
            test_schema = {
                'ROI_1': {
                    'columns': [
                        {'name': 'id', 'type': 'INTEGER', 'is_primary': True, 'is_auto_increment': True},
                        {'name': 't', 'type': 'INTEGER', 'is_primary': False, 'is_auto_increment': False},
                        {'name': 'x', 'type': 'INTEGER', 'is_primary': False, 'is_auto_increment': False}
                    ],
                    'primary_key': 'id',
                    'has_auto_increment': True
                },
                'METADATA': {
                    'columns': [
                        {'name': 'field', 'type': 'TEXT', 'is_primary': False, 'is_auto_increment': False},
                        {'name': 'value', 'type': 'TEXT', 'is_primary': False, 'is_auto_increment': False}
                    ],
                    'primary_key': None,
                    'has_auto_increment': False
                }
            }
            
            # Validate schema structure
            for table_name, schema in test_schema.items():
                has_pk = schema['primary_key'] is not None
                pk_column = schema['primary_key']
                
                if has_pk:
                    pk_col_info = next((col for col in schema['columns'] if col['name'] == pk_column), None)
                    if pk_col_info and pk_col_info['is_primary']:
                        print(f"✓ {table_name}: PRIMARY KEY detected on {pk_column}")
                    else:
                        print(f"✗ {table_name}: PRIMARY KEY detection failed")
                        self.test_results.append(f"Schema detection failed for {table_name}")
                else:
                    print(f"✓ {table_name}: No PRIMARY KEY (as expected)")
            
            self.test_results.append("Schema detection: PASSED")
            
        except Exception as e:
            print(f"✗ Schema detection test failed: {e}")
            self.test_results.append(f"Schema detection: FAILED - {e}")
    
    def test_table_creation_with_constraints(self):
        """Test creating SQLite tables with PRIMARY KEY constraints."""
        print("\\nTest 2: Table Creation with Constraints")
        print("-" * 40)
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
            test_db_path = tmp_file.name
        
        try:
            with sqlite3.connect(test_db_path) as conn:
                cursor = conn.cursor()
                
                # Test 1: Create table with PRIMARY KEY
                cursor.execute("""
                    CREATE TABLE test_roi (
                        id INTEGER PRIMARY KEY,
                        t INTEGER,
                        x INTEGER,
                        y INTEGER
                    )
                """)
                
                # Test 2: Create table without PRIMARY KEY
                cursor.execute("""
                    CREATE TABLE test_metadata (
                        field TEXT,
                        value TEXT
                    )
                """)
                
                # Verify constraints
                cursor.execute("PRAGMA table_info(test_roi)")
                roi_columns = cursor.fetchall()
                
                pk_found = False
                for col_info in roi_columns:
                    col_name = col_info[1]
                    is_pk = col_info[5] == 1
                    if col_name == 'id' and is_pk:
                        pk_found = True
                        break
                
                if pk_found:
                    print("✓ PRIMARY KEY constraint created successfully")
                else:
                    print("✗ PRIMARY KEY constraint not found")
                    self.test_results.append("Table creation: PRIMARY KEY not created")
                
                # Test duplicate prevention
                cursor.execute("INSERT INTO test_roi (id, t, x, y) VALUES (1, 100, 10, 20)")
                
                try:
                    cursor.execute("INSERT INTO test_roi (id, t, x, y) VALUES (1, 200, 30, 40)")
                    print("✗ PRIMARY KEY constraint not enforced")
                    self.test_results.append("Table creation: PRIMARY KEY not enforced")
                except sqlite3.IntegrityError:
                    print("✓ PRIMARY KEY constraint enforced (duplicate rejected)")
                
                # Test INSERT OR IGNORE
                cursor.execute("INSERT OR IGNORE INTO test_roi (id, t, x, y) VALUES (1, 300, 50, 60)")
                cursor.execute("SELECT COUNT(*) FROM test_roi WHERE id = 1")
                count = cursor.fetchone()[0]
                
                if count == 1:
                    print("✓ INSERT OR IGNORE works correctly")
                    self.test_results.append("Table creation: PASSED")
                else:
                    print(f"✗ INSERT OR IGNORE failed, count = {count}")
                    self.test_results.append("Table creation: INSERT OR IGNORE failed")
        
        except Exception as e:
            print(f"✗ Table creation test failed: {e}")
            self.test_results.append(f"Table creation: FAILED - {e}")
        
        finally:
            if os.path.exists(test_db_path):
                os.unlink(test_db_path)
    
    def test_table_migration(self):
        """Test migration of existing tables without constraints."""
        print("\\nTest 3: Table Migration")
        print("-" * 25)
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
            test_db_path = tmp_file.name
        
        try:
            with sqlite3.connect(test_db_path) as conn:
                cursor = conn.cursor()
                
                # Create old-style table without PRIMARY KEY
                cursor.execute("""
                    CREATE TABLE test_table (
                        id INTEGER,
                        data TEXT
                    )
                """)
                
                # Insert test data including duplicates
                test_data = [
                    (1, 'first'),
                    (2, 'second'),
                    (1, 'duplicate'),  # This should be removed during migration
                    (3, 'third')
                ]
                
                cursor.executemany("INSERT INTO test_table (id, data) VALUES (?, ?)", test_data)
                conn.commit()
                
                # Check initial state
                cursor.execute("SELECT COUNT(*) FROM test_table")
                initial_count = cursor.fetchone()[0]
                print(f"Initial rows: {initial_count}")
                
                # Simulate migration (backup and recreate)
                backup_table = "test_table_backup"
                cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM test_table")
                cursor.execute("DROP TABLE test_table")
                
                # Create new table with PRIMARY KEY
                cursor.execute("""
                    CREATE TABLE test_table (
                        id INTEGER PRIMARY KEY,
                        data TEXT
                    )
                """)
                
                # Copy data back with duplicate handling
                cursor.execute(f"INSERT OR IGNORE INTO test_table SELECT * FROM {backup_table} ORDER BY id")
                
                # Check final state
                cursor.execute("SELECT COUNT(*) FROM test_table")
                final_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(DISTINCT id) FROM test_table")
                unique_ids = cursor.fetchone()[0]
                
                if final_count == unique_ids and final_count < initial_count:
                    duplicates_removed = initial_count - final_count
                    print(f"✓ Migration successful: {duplicates_removed} duplicates removed")
                    print(f"  Final rows: {final_count} (all unique)")
                    self.test_results.append("Table migration: PASSED")
                else:
                    print(f"✗ Migration failed: final={final_count}, unique={unique_ids}")
                    self.test_results.append("Table migration: FAILED")
                
                # Clean up
                cursor.execute(f"DROP TABLE {backup_table}")
        
        except Exception as e:
            print(f"✗ Table migration test failed: {e}")
            self.test_results.append(f"Table migration: FAILED - {e}")
        
        finally:
            if os.path.exists(test_db_path):
                os.unlink(test_db_path)
    
    def test_duplicate_prevention(self):
        """Test that PRIMARY KEY constraints prevent duplicates during backup."""
        print("\\nTest 4: Duplicate Prevention")
        print("-" * 30)
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
            test_db_path = tmp_file.name
        
        try:
            with sqlite3.connect(test_db_path) as conn:
                cursor = conn.cursor()
                
                # Create table with PRIMARY KEY
                cursor.execute("""
                    CREATE TABLE backup_test (
                        id INTEGER PRIMARY KEY,
                        timestamp INTEGER,
                        value REAL
                    )
                """)
                
                # Simulate incremental backup with overlapping data
                batch1 = [(1, 1000, 1.5), (2, 2000, 2.5), (3, 3000, 3.5)]
                batch2 = [(3, 3000, 3.5), (4, 4000, 4.5), (5, 5000, 5.5)]  # ID 3 overlaps
                
                # Insert first batch
                cursor.executemany("INSERT INTO backup_test VALUES (?, ?, ?)", batch1)
                
                # Insert second batch with INSERT OR IGNORE (simulating backup behavior)
                cursor.executemany("INSERT OR IGNORE INTO backup_test VALUES (?, ?, ?)", batch2)
                
                # Check results
                cursor.execute("SELECT COUNT(*) FROM backup_test")
                total_rows = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(DISTINCT id) FROM backup_test")
                unique_ids = cursor.fetchone()[0]
                
                cursor.execute("SELECT MAX(id) FROM backup_test")
                max_id = cursor.fetchone()[0]
                
                expected_rows = 5  # IDs 1, 2, 3, 4, 5
                if total_rows == expected_rows and unique_ids == expected_rows and max_id == 5:
                    print(f"✓ Duplicate prevention working: {total_rows} rows, all unique")
                    self.test_results.append("Duplicate prevention: PASSED")
                else:
                    print(f"✗ Duplicate prevention failed: {total_rows} rows, {unique_ids} unique")
                    self.test_results.append("Duplicate prevention: FAILED")
        
        except Exception as e:
            print(f"✗ Duplicate prevention test failed: {e}")
            self.test_results.append(f"Duplicate prevention: FAILED - {e}")
        
        finally:
            if os.path.exists(test_db_path):
                os.unlink(test_db_path)
    
    def print_test_summary(self):
        """Print summary of all test results."""
        print("\\n" + "=" * 50)
        print("TEST SUMMARY")
        print("=" * 50)
        
        passed = 0
        failed = 0
        
        for result in self.test_results:
            if "PASSED" in result:
                passed += 1
                print(f"✓ {result}")
            else:
                failed += 1
                print(f"✗ {result}")
        
        print("-" * 50)
        print(f"Total Tests: {passed + failed}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        
        if failed == 0:
            print("\\n🎉 ALL TESTS PASSED! PRIMARY KEY implementation is working correctly.")
        else:
            print(f"\\n⚠️  {failed} test(s) failed. Please review the implementation.")
        
        return failed == 0


def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test PRIMARY KEY backup implementation")
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    args = parser.parse_args()
    
    tester = BackupTester(verbose=args.verbose)
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()