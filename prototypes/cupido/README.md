# Cupido Offline Tracking System (Enhanced)

A comprehensive offline tracking system for analyzing Drosophila behavior videos using the ethoscope package. The system integrates with ethoscope's target detection system and uses JSON templates for precise ROI definition.

## Overview

The enhanced Cupido system consists of five main components:

1. **Enhanced ROI Template Creator** (`mask_creator.py`) - Create JSON ROI templates with automatic target detection
2. **Template-Based ROI Manager** (`roi_manager.py`) - Load and validate JSON templates for tracking
3. **Tracking Configuration** (`tracking_config.py`) - Manage tracking parameters for different experimental conditions
4. **Main Tracker** (`cupido_tracker.py`) - Batch offline tracking orchestrator
5. **Results Manager** (`results_manager.py`) - Consolidate, analyze, and export tracking results

## Quick Start

### Prerequisites

```bash
# Activate ethoscope virtual environment
source /home/gg/Data/ethoscope_project/ethoscope/.venv/bin/activate

# Navigate to cupido directory
cd /home/gg/Data/ethoscope_project/ethoscope/prototypes/cupido
```

### 1. Create ROI Templates (First Time Setup)

Create JSON templates for each ethoscope machine with automatic target detection:

```bash
# Interactive template creation for all machines (uses default 6-ROI template)
python mask_creator.py

# Create template for specific machine (uses default 6-ROI template)
python mask_creator.py --machine 76

# Use built-in template as starting point
python mask_creator.py --machine 76 --template /path/to/builtin_template.json

# Use specific template
python mask_creator.py --machine 76 --template HD_Mating_Arena_6_ROIS.json

# Force manual target detection (skip automatic detection)
python mask_creator.py --machine 76 --manual
```

**The Enhanced Workflow:**
1. **Default Template Loading**: Automatically loads `HD_Mating_Arena_6_ROIS.json` (2×3 ROI grid)
2. **Target Detection Mode**: 
   - **Automatic** (default): System attempts to find 3 circular targets using ethoscope's detection algorithm
   - **Manual** (--manual flag): Skip automatic detection and go straight to manual clicking
3. **Manual Target Correction**: If automatic detection fails, or with --manual flag, click on target positions manually
4. **Automatic ROI Generation**: After 3 targets are placed manually, ROIs are automatically drawn using the template
5. **Template Application**: Apply default, built-in, or custom JSON template for ROI layout
6. **ROI Validation**: Test the template to ensure proper ROI generation
7. **Template Export**: Save as JSON file for use in tracking

**Interactive Controls:**
- 'm': Toggle manual target mode (disabled with --manual flag)
- 'r': Reset manual targets
- 'o': Toggle overlay display
- 't': Test current template
- 's': Save JSON template
- ESC: Exit

**Manual Mode Behavior:**
- **With --manual flag**: Starts in manual mode immediately, automatic detection disabled
- **Click targets**: Left-click on 3 target positions in order: top, bottom-left, bottom-right  
- **Auto-draw ROIs**: After 3rd target click, template automatically applies and draws ROIs
- **Ready to save**: Press 's' to save the template with target coordinates and ROI layout

### 2. Run Batch Tracking

```bash
# Track all experiments
python cupido_tracker.py

# Track specific machine only
python cupido_tracker.py --machine 76

# Resume interrupted processing
python cupido_tracker.py --resume

# Check current status
python cupido_tracker.py --status
```

### 3. Analyze Results

```bash
# View results summary
python results_manager.py

# Export summary to CSV
python results_manager.py --export-csv

# Generate comprehensive report
python results_manager.py --generate-report

# Export raw tracking data (warning: large files!)
python results_manager.py --export-raw
```

## System Architecture

### Data Flow

```
Metadata CSV → Target Detection → JSON Templates → Tracking Config → Batch Tracking → Results Analysis
     ↓              ↓                 ↓               ↓                ↓                ↓
Video Files → Auto/Manual Targets → ROI Layout → Genotype/Group → SQLite DBs → CSV/Reports
                                                Parameters      Per Experiment
```

### File Structure

```
prototypes/cupido/
├── 2025_07_15_metadata.csv          # Input metadata
├── mask_creator.py                   # Interactive ROI mask creator
├── roi_manager.py                    # ROI mask management
├── tracking_config.py                # Tracking parameter configuration
├── cupido_tracker.py                 # Main tracking orchestrator  
├── results_manager.py                # Results analysis and export
├── video_finder.py                   # Video file utilities (existing)
├── results/
│   ├── masks/                        # JSON ROI templates 
│   ├── tracking/                     # Tracking databases (.db)
│   ├── analysis/                     # Analysis outputs (.csv, .md)
│   └── progress.json                 # Processing progress
└── README.md                         # This file
```

## Components Details

### 1. Enhanced ROI Template Creator

**Purpose:** Create JSON ROI templates using ethoscope's target detection system.

**Key Features:**
- Automatic target detection using TargetGridROIBuilder
- Manual target correction when automatic detection fails
- Built-in template support (sleep_monitor_20tube, hd_12tubes, etc.)
- Real-time ROI validation and preview
- JSON template export compatible with ethoscope ecosystem

**Output:** JSON template files with target coordinates and ROI configuration

### 2. Template-Based ROI Manager

**Purpose:** Load, validate, and provide ROI builders using JSON templates.

**Key Features:**
- Automatic JSON template discovery
- Integration with TargetGridROIBuilder
- Stored target coordinate support
- Built-in template loading capability
- Fallback to full-frame ROI if no template available

### 3. Tracking Configuration

**Purpose:** Manage tracking parameters for different experimental conditions.

**Supported Configurations:**
- **Genotypes:** CS (Canton-S) with extensible config
- **Groups:** trained/untrained with specific parameters
- **Trackers:** AdaptiveBGModel (primary), MultiFlyTracker (optional)
- **Machines:** Machine-specific adjustments (76, 145, 139, 268)

**Default Parameters:**
```json
{
  "adaptive_alpha": 0.05,
  "minimal_movement": 0.05,
  "fg_data": {
    "sample_size": 400,
    "normal_limits": [50, 200],
    "tolerance": 0.8
  }
}
```

### 4. Main Tracking Orchestrator

**Purpose:** Batch processing of video experiments with error handling and progress tracking.

**Key Features:**
- Processes all experiments from metadata CSV
- Machine-specific ROI mask loading
- Configurable tracking parameters per genotype/group
- Progress tracking with resume capability
- Error handling and recovery
- SQLite database output per experiment

**Database Schema:** Compatible with ethoscope ecosystem (ETHOSCOPE_DATA table)

## Target Detection System

The enhanced Cupido system integrates with ethoscope's robust target detection algorithms:

### Automatic Detection
- **Algorithm**: Uses ethoscope's `TargetGridROIBuilder` with adaptive background subtraction
- **Targets**: Detects 3 circular black targets in triangular arrangement
- **Robustness**: Multi-attempt detection with progressive tolerance relaxation
- **Quality Control**: Validates target circularity and size consistency

### Manual Correction
- **Fallback**: Manual target clicking when automatic detection fails
- **Target Order**: Top target, bottom-left target, bottom-right target
- **Visual Feedback**: Real-time target visualization and validation
- **Integration**: Manual targets seamlessly integrate with ROI generation

### JSON Template Format
Templates are compatible with ethoscope's standard format:
```json
{
  "template_info": {
    "name": "Cupido Machine 76",
    "version": "1.0",
    "description": "Custom template for machine 76"
  },
  "roi_definition": {
    "type": "grid_with_targets",
    "grid": { "n_rows": 1, "n_cols": 6 },
    "positioning": {
      "margins": { "top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0 },
      "fill_ratios": { "horizontal": 0.9, "vertical": 0.9 }
    }
  },
  "targets": {
    "coordinates": [[x1, y1], [x2, y2], [x3, y3]],
    "detection_method": "automatic",
    "timestamp": "2025-01-15T12:00:00"
  }
}
```

### 5. Results Manager

**Purpose:** Consolidate, analyze, and export tracking results.

**Analysis Features:**
- Experiment summary statistics
- Data quality validation
- Group-based analysis
- Duration and activity metrics
- CSV export (summary and raw data)
- Markdown reports

## Configuration Files

### Metadata CSV Format

Required columns in `2025_07_15_metadata.csv`:
```csv
date,HHMMSS,machine_name,ROI,genotype,group,path,filesize_mb
15/07/2025,16:03:10,76,1,CS,trained,/path/to/video.mp4,59.4
```

### Progress Tracking

The system maintains progress in `results/progress.json`:
```json
{
  "completed": [1, 2, 3],
  "failed": [4],
  "in_progress": null,
  "statistics": {
    "total_videos": 36,
    "completed_count": 3,
    "failed_count": 1,
    "start_time": "2025-01-15T10:00:00",
    "last_update": "2025-01-15T12:30:00"
  }
}
```

## Usage Examples

### Complete Workflow Example

```bash
# 1. Create masks for all machines
python mask_creator.py
# Follow interactive prompts for each machine

# 2. Verify ROI manager can load masks
python roi_manager.py --validate

# 3. Test tracking configuration
python tracking_config.py --genotype CS --group trained --machine 76

# 4. Check tracking status
python cupido_tracker.py --status

# 5. Run batch tracking
python cupido_tracker.py

# 6. Analyze results
python results_manager.py --export-csv --generate-report
```

### Processing Specific Subsets

```bash
# Process only machine 76
python cupido_tracker.py --machine 76

# Process only experiment row 5
python cupido_tracker.py --experiment 5

# Resume interrupted batch processing
python cupido_tracker.py --resume
```

### Custom Configuration

```bash
# Save current tracking config
python tracking_config.py --save custom_config.json

# Use custom config file  
python cupido_tracker.py --config custom_config.json
```

## Troubleshooting

### Common Issues

**No ROI masks found:**
```bash
# Create masks first
python mask_creator.py --machine YOUR_MACHINE
```

**Video files not found:**
- Check that video paths in metadata CSV are accessible
- Verify the `/mnt/ethoscope_data/videos` mount if using network storage

**Tracking fails with ROI errors:**
```bash
# Validate specific mask
python roi_manager.py --machine YOUR_MACHINE --validate

# Test mask in mask creator
python mask_creator.py --machine YOUR_MACHINE
# Press 't' to test mask
```

**Database validation fails:**
- Check SQLite database integrity
- Verify ETHOSCOPE_DATA table exists with data
- Use results manager to validate: `python results_manager.py --validate`

### Performance Notes

- **Memory usage:** ~500MB per video during processing
- **Processing time:** ~2-5x video duration (depends on video quality and tracking parameters)
- **Storage:** ~1-10MB SQLite database per video experiment
- **Parallelization:** Currently single-threaded (can be extended for parallel processing)

## Extension Points

### Adding New Genotypes

Edit tracking configuration in `tracking_config.py`:
```python
"genotype_configs": {
    "NEW_GENOTYPE": {
        "description": "New genotype description",
        "default_tracker": "adaptive_bg",
        "movement_threshold": 0.05,
        # ... additional parameters
    }
}
```

### Adding New Trackers

1. Import tracker in `tracking_config.py`
2. Add to `tracker_configs` section
3. Update `get_tracker_class_by_name()` method

### Adding New Analysis Features

Extend `results_manager.py` with new analysis methods:
- Activity pattern analysis
- Sleep/wake cycle detection
- Movement velocity calculations
- Spatial preference analysis

## Dependencies

The system uses the ethoscope package with these key dependencies:
- `opencv-python` (computer vision)
- `numpy` (numerical operations)
- `sqlite3` (database storage)
- Standard library: `csv`, `json`, `argparse`, `datetime`, `os`, `sys`

## Integration with Ethoscope Ecosystem

The Cupido system is fully compatible with:
- **Ethoscope ROI builders** (ImgMaskROIBuilder)
- **Ethoscope trackers** (AdaptiveBGModel, MultiFlyTracker)
- **Ethoscope database format** (SQLite with ETHOSCOPE_DATA table)
- **Ethoscope monitoring framework** (Monitor class)

Results can be analyzed using standard ethoscope analysis tools or imported into R/Python analysis pipelines.

---

**Created:** 2025-01-15  
**System Version:** 1.0  
**Ethoscope Compatibility:** Latest development version