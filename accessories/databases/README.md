# Database Recovery Tools

This directory contains tools for recovering and converting ethoscope databases.

## Recovering MariaDB Data from an Ethoscope SD Card

If an ethoscope device fails or you need to recover tracking data from an SD card, you can extract the MariaDB database and convert it to SQLite format using the tools provided here.

### When Would You Need This?

- The ethoscope device is no longer functional
- The network backup failed and you need to recover data directly from the SD card
- You want to archive data from an SD card before reimaging it
- The ethoscope was running but the data was never synced to the node

### Prerequisites

Before you begin, make sure you have:

1. **A Linux computer** (the node server or any Linux machine)
2. **Docker installed and running**
   ```bash
   # Check if Docker is running
   docker info

   # If not running, start it
   sudo systemctl start docker
   ```
3. **An SD card reader** to connect the ethoscope's microSD card
4. **SQLite3** installed (usually pre-installed on most Linux systems)
   ```bash
   # Check if installed
   sqlite3 --version
   ```

### Step-by-Step Instructions

#### Step 1: Remove the SD Card from the Ethoscope

1. **Power off** the ethoscope device completely
2. Carefully remove the microSD card from the Raspberry Pi
3. Insert the SD card into a card reader connected to your Linux computer

#### Step 2: Locate the SD Card Mount Point

When you insert the SD card, it should automatically mount. Find where it mounted:

```bash
# List mounted devices
lsblk

# Or check the /run/media directory (common on most Linux systems)
ls /run/media/$USER/
```

You should see two partitions:
- A small **boot partition** (usually ~128MB, FAT32)
- A larger **root partition** (the main filesystem with your data)

The root partition is what you need. It will have a path like:
```
/run/media/yourusername/5a28ba63-c53d-4d1b-a4a4-3115b9dc250e
```

You can verify it's the right partition by checking for the MySQL data directory:
```bash
ls /run/media/$USER/<partition-id>/var/lib/mysql/
```

You should see directories like `ETHOSCOPE_XXX_db`.

#### Step 3: Run the Recovery Script

Run the recovery script with sudo (required for Docker and reading the MySQL directory):

```bash
sudo /path/to/ethoscope/accessories/databases/recover_mariadb_from_sdcard.sh /run/media/$USER/<partition-id>
```

**Example:**
```bash
sudo ./recover_mariadb_from_sdcard.sh /run/media/gg/5a28ba63-c53d-4d1b-a4a4-3115b9dc250e
```

#### Step 4: Wait for the Recovery Process

The script will:

1. **Detect the MariaDB version** from the SD card
2. **Start a Docker container** with the database files
3. **Perform crash recovery** (this may take 1-3 minutes)
4. **Export the database** using mysqldump
5. **Convert to SQLite** format
6. **Save the file** to the standard ethoscope results directory

You'll see output like this:
```
[INFO] ==============================================
[INFO] Ethoscope SD Card Database Recovery Tool
[INFO] ==============================================

[STEP] Checking prerequisites...
[INFO] All prerequisites met
[STEP] Validating SD card mount point...
[INFO] Found MySQL data directory: /run/media/gg/.../var/lib/mysql
[STEP] Detecting MariaDB version...
[INFO] Detected MariaDB 10.11 from upgrade_info
[STEP] Searching for ethoscope databases...
[INFO] Found database(s):
  - ETHOSCOPE_019_db

[STEP] Starting MariaDB Docker container...
[INFO] Container started, waiting for crash recovery...
[STEP] Waiting for MariaDB to be ready...
[INFO] Still waiting for MariaDB... (15 seconds)
[INFO] MariaDB is ready!

[STEP] Exporting database: ETHOSCOPE_019_db
[INFO] Database size: 2762.19 MB
[INFO] Starting database export and conversion...
[INFO] This may take several minutes for large databases...
```

**Be patient!** Large databases (2-3GB) can take 5-10 minutes to convert.

#### Step 5: Verify the Recovery

Once complete, you'll see:
```
[INFO] Conversion successful!
[INFO] Output file: /ethoscope_data/results/.../2025-11-05_15-18-53_xxx.db
[INFO] SQLite file size: 2.8G
[INFO] Tables in SQLite database: 26
[INFO] ROI tables found: 21
```

You can verify the database is valid:
```bash
# Check tables
sqlite3 /ethoscope_data/results/.../your_database.db "SELECT name FROM sqlite_master WHERE type='table';"

# Check metadata
sqlite3 /ethoscope_data/results/.../your_database.db "SELECT * FROM METADATA;"
```

### Output Location

The recovered database is saved following the standard ethoscope convention:
```
/ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/{backup_filename}.db
```

For example:
```
/ethoscope_data/results/019f8214123546dd811e530ec4827b55/ETHOSCOPE_019/2025-11-05_15-18-53/2025-11-05_15-18-53_019f8214123546dd811e530ec4827b55.db
```

### Custom Output Directory

To save to a different location, specify it as the second argument:
```bash
sudo ./recover_mariadb_from_sdcard.sh /run/media/$USER/<partition-id> /custom/output/path
```

### Troubleshooting

#### "No ethoscope database found"

Make sure you're pointing to the **root partition**, not the boot partition. The root partition contains `/var/lib/mysql/`.

#### "Container stopped unexpectedly" or Version Mismatch

The script auto-detects the MariaDB version, but if it fails, you can force a specific version:

```bash
# For older ethoscopes (pre-2024)
MARIADB_IMAGE=mariadb:10.6 sudo ./recover_mariadb_from_sdcard.sh /run/media/$USER/<partition-id>

# For newer ethoscopes
MARIADB_IMAGE=mariadb:10.11 sudo ./recover_mariadb_from_sdcard.sh /run/media/$USER/<partition-id>
```

#### "Docker permission denied"

Either run with sudo, or add your user to the docker group:
```bash
sudo usermod -aG docker $USER
# Then log out and log back in
```

#### Timeout during crash recovery

Large databases may need more time for crash recovery. The default timeout is 3 minutes. If you see timeout errors, try running the script again - sometimes the recovery completes faster on the second attempt.

#### Multiple SD cards with same UUID

Ethoscope SD cards cloned from the same image may have identical filesystem UUIDs. They'll mount at the same path. Simply swap cards and run the script again for each card.

### Other Tools in This Directory

| Script | Description |
|--------|-------------|
| `mariadb2sqlite.sh` | Convert MariaDB to SQLite on a running ethoscope device |
| `sql2sqlite.sh` | Convert mysqldump output to SQLite (used internally) |
| `recover_mariadb_from_sdcard.sh` | Recover database from SD card using Docker |

### Technical Details

The recovery process:
1. Mounts the SD card's MySQL data directory into a Docker container
2. Uses the matching MariaDB version to ensure compatibility
3. MariaDB performs crash recovery on the InnoDB files
4. mysqldump exports the data in ANSI-compatible format
5. An AWK script converts MySQL syntax to SQLite syntax
6. SQLite imports the converted data

The Docker container is automatically cleaned up after the script completes.

### Getting Help

If you encounter issues:
1. Check the container logs: `docker logs ethoscope_recovery_db`
2. Ensure the SD card is properly mounted and readable
3. Verify you have enough disk space for the output file
4. Report issues at: https://github.com/gilestrolab/ethoscope/issues
