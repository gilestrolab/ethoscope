# Unified Backup Status API

## Overview

The Ethoscope node server now provides unified backup status information from both backup systems:
- **MySQL Backup Daemon** (port 8090) - handles MySQL/MariaDB database backups
- **Rsync Backup Daemon** (port 8093) - handles file-based backups (SQLite databases + videos)

## API Endpoint

**GET** `/backup/status`

Returns combined status information from both backup services.

## Response Format

```json
{
  "mysql_backup": {
    // Raw response from MySQL backup daemon (port 8090)
    "device_id": {
      "name": "ETHOSCOPE_XXX",
      "status": "stopped|running",
      "progress": {
        "status": "success|error|warning",
        "message": "Status message"
      },
      "synced": {},
      "processing": false,
      "count": 1,
      "started": 1752137404,
      "ended": 1752137404
    }
  },
  "rsync_backup": {
    "devices": {
      // Raw response from rsync backup daemon (port 8093)
      "device_id": {
        "name": "ETHOSCOPE_XXX", 
        "status": "stopped|running",
        "progress": {
          "status": "success|error",
          "message": "Backup status message"
        },
        "synced": {
          "results": {
            "local_files": 766,
            "directory": "/ethoscope_data/results",
            "disk_usage_bytes": 287646297933,
            "disk_usage_human": "267.9 GB"
          },
          "videos": {
            "local_files": 12529,
            "directory": "/ethoscope_data/videos", 
            "disk_usage_bytes": 544649438682,
            "disk_usage_human": "507.2 GB"
          }
        },
        "processing": false,
        "count": 818,
        "started": 1752137339,
        "ended": 1752137340,
        "metadata": {}
      }
    },
    "disk_usage_summary": {
      "results": {
        "total_files": 29119,
        "total_size_bytes": 11215763841541,
        "total_size_human": "10.2 TB"
      },
      "videos": {
        "total_files": 476102,
        "total_size_bytes": 20696678673241,
        "total_size_human": "18.8 TB"
      }
    }
  },
  "unified_devices": {
    // Merged view per device
    "device_id": {
      "name": "ETHOSCOPE_XXX",
      "status": "stopped|running", 
      "overall_status": "success|partial|error|unknown",
      "mysql_backup": {
        "available": true|false,
        "status": "stopped|running|not_available",
        "progress": {},
        "synced": {},
        "processing": false,
        "count": 0,
        "started": null,
        "ended": null
      },
      "rsync_backup": {
        "available": true|false,
        "status": "stopped|running|not_available",
        "progress": {},
        "synced": {},
        "processing": false,
        "count": 0,
        "started": null,
        "ended": null,
        "metadata": {}
      }
    }
  }
}
```

## Overall Status Logic

The `overall_status` field in `unified_devices` is determined as follows:

- **success**: Both MySQL and rsync backups report success
- **partial**: Only one backup type reports success  
- **error**: At least one backup type reports an error
- **unknown**: Neither backup type reports success or error

## Error Handling

If either backup service is unavailable, the response will include:

```json
{
  "mysql_backup": {
    "error": "MySQL backup service unavailable",
    "service": "mysql_backup"
  },
  "rsync_backup": {
    "error": "Rsync backup service unavailable", 
    "service": "rsync_backup"
  },
  "unified_devices": {}
}
```

## Testing

You can test the individual services directly:

- MySQL backup: `curl http://localhost:8090/status`
- Rsync backup: `curl http://localhost:8093/status`
- Unified status: `curl http://localhost/backup/status`

## Migration Notes

**Breaking Change**: The backup status endpoint now returns a different format. The previous format was a direct proxy to port 8090. Applications consuming this API will need to be updated to handle the new unified format.

To maintain compatibility with existing code that expects the old format, you can access:
- `response.mysql_backup` for the old MySQL-only format
- `response.unified_devices` for the new merged view

## Frontend Changes

The Ethoscope node frontend has been updated to work with the new unified backup status format:

### Updated JavaScript Functions:

1. **`get_backup_status()`**: Now extracts `unified_devices` and stores service availability flags
2. **`getBackupStatusClass()`**: Determines backup circle colors based on processing state and overall status:
   - **Orange (breathing)**: `processing` - any backup currently running
   - **Green**: `success` - both MySQL and rsync backups working
   - **Golden**: `partial` - only one backup service working  
   - **Red**: `error` - at least one backup service failed
   - **Grey**: `unknown` - status unclear
   - **Black**: Service offline

3. **`getBackupStatusTitle()`**: Provides comprehensive tooltip showing:
   - Overall backup status
   - MySQL backup status and message
   - Rsync backup status and message  
   - Data size information from rsync backups

### New Scope Variables:

- `$scope.backup_status`: Contains `unified_devices` for easy device lookup
- `$scope.mysql_backup_available`: Boolean indicating MySQL backup daemon availability
- `$scope.rsync_backup_available`: Boolean indicating rsync backup daemon availability
- `$scope.backup_service_available`: Boolean indicating if either service is available
- `$scope.backup_status_full`: Full API response for debugging

## Example Usage

```javascript
// Fetch unified backup status
fetch('/backup/status')
  .then(response => response.json())
  .then(data => {
    // Check if both services are available
    const mysqlAvailable = !data.mysql_backup.error;
    const rsyncAvailable = !data.rsync_backup.error;
    
    // Iterate through unified device view
    Object.entries(data.unified_devices).forEach(([deviceId, device]) => {
      console.log(`${device.name}: ${device.overall_status}`);
      
      if (device.mysql_backup.available) {
        console.log(`  MySQL: ${device.mysql_backup.progress.status}`);
      }
      
      if (device.rsync_backup.available) {
        console.log(`  Rsync: ${device.rsync_backup.progress.status}`);
        console.log(`  Data: ${device.rsync_backup.synced.results?.disk_usage_human}`);
      }
    });
  });
```