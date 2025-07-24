"""
Database Writers for Ethoscope Experiment Data Storage

This module provides various classes for storing experimental tracking data from the Ethoscope
behavioral monitoring system. The classes support multiple database backends (MySQL/MariaDB, SQLite)
and different output formats (database tables, numpy arrays).

Class Hierarchy and Relationships:
==================================

1. Database Writers (Main Interface):
   MySQLResultWriter (base class for MySQL database storage)
   ├── SQLiteResultWriter (extends BaseResultWriter for SQLite-specific behavior)
   └── RawDataWriter (independent class for numpy array storage)

2. Async Database Processes (Multiprocessing):
   multiprocessing.Process
   ├── AsyncMySQLWriter (handles MySQL/MariaDB writes in separate process)
   └── AsyncSQLiteWriter (handles SQLite writes in separate process)

3. Helper Classes (Data Formatting):
   SensorDataHelper (formats sensor data for database storage)
   ImgSnapshotHelper (handles image snapshot storage as BLOBs)
   DAMFileHelper (creates DAM-compatible activity summaries)

4. Utility Classes:
   Null (special NULL representation for SQLite)
   NpyAppendableFile (custom numpy array file format for incremental writes)

Interaction Flow:
================
1. MySQLResultWriter/SQLiteResultWriter creates an async writer process (AsyncMySQLWriter/AsyncSQLiteWriter)
2. MySQLResultWriter sends SQL commands through a multiprocessing queue to the async writer
3. MySQLResultWriter uses helper classes to format different data types:
   - DAMFileHelper for activity summaries
   - ImgSnapshotHelper for periodic screenshots
   - SensorDataHelper for environmental sensor data
4. RawDataWriter operates independently, saving raw data directly to numpy array files

Key Design Patterns:
===================
- Multiprocessing: Async writers run in separate processes to prevent I/O blocking
- Producer-Consumer: Main thread produces SQL commands, async writer consumes them
- Template Method: BaseResultWriter provides base implementation, MySQLResultWriter and SQLiteResultWriter override specific methods
- Helper Pattern: Separate classes handle formatting for different data types
- Context Manager: BaseResultWriter implements __enter__/__exit__ for proper cleanup
"""

# Import all base classes and utilities from their respective modules
from .base import (
    BaseAsyncSQLWriter, 
    BaseResultWriter, 
    dbAppender
)

from .helpers import (
    SensorDataHelper,
    ImgSnapshotHelper, 
    DAMFileHelper,
    Null,
    NpyAppendableFile,
    RawDataWriter
)

from .mysql import (
    AsyncMySQLWriter,
    MySQLResultWriter
)

from .sqlite import (
    AsyncSQLiteWriter,
    SQLiteResultWriter
)


from .cache import (
    BaseDatabaseMetadataCache,
    MySQLDatabaseMetadataCache,
    SQLiteDatabaseMetadataCache,
    DatabasesInfo,
    create_metadata_cache
)

# Export all classes for proper module interface
__all__ = [
    # Base classes
    'BaseAsyncSQLWriter',
    'BaseResultWriter',
    'dbAppender',
    
    # Helper classes
    'SensorDataHelper',
    'ImgSnapshotHelper', 
    'DAMFileHelper',
    'Null',
    'NpyAppendableFile',
    'RawDataWriter',
    
    # MySQL classes
    'AsyncMySQLWriter',
    'MySQLResultWriter',
    
    # SQLite classes
    'AsyncSQLiteWriter',
    'SQLiteResultWriter',
    
    
    # Cache classes
    'BaseDatabaseMetadataCache',
    'MySQLDatabaseMetadataCache', 
    'SQLiteDatabaseMetadataCache',
    'create_metadata_cache',
    'get_all_databases_info'
]