#!/usr/bin/env python3
"""
Results Manager for Cupido Offline Tracking

This module provides utilities for consolidating, analyzing, and exporting
tracking results from the Cupido offline tracking pipeline.

Features:
- Consolidate multiple SQLite tracking databases
- Export data to CSV format
- Generate summary statistics
- Data quality validation
- Progress reporting

Usage:
    from results_manager import CupidoResultsManager
    
    manager = CupidoResultsManager('results/tracking')
    manager.consolidate_results()
    manager.export_to_csv('consolidated_results.csv')
"""

import os
import sys
import sqlite3
import csv
import json
import glob
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import traceback

# Add ethoscope to path for database compatibility
sys.path.insert(0, '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope')


class CupidoResultsManager:
    """
    Manager for consolidating and analyzing Cupido tracking results.
    
    Handles SQLite databases created by the tracking pipeline and provides
    tools for data export, analysis, and quality validation.
    """
    
    def __init__(self, results_dir: str = "results/tracking", 
                 output_dir: str = "results/analysis"):
        """
        Initialize the results manager.
        
        Args:
            results_dir: Directory containing tracking database files
            output_dir: Directory for analysis outputs
        """
        self.results_dir = results_dir
        self.output_dir = output_dir
        self.databases = self._discover_databases()
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
    def _discover_databases(self) -> List[Dict]:
        """Discover tracking database files."""
        databases = []
        
        if not os.path.exists(self.results_dir):
            return databases
            
        # Find all .db files
        db_files = glob.glob(os.path.join(self.results_dir, "*.db"))
        
        for db_file in db_files:
            try:
                db_info = self._analyze_database(db_file)
                if db_info:
                    databases.append(db_info)
            except Exception as e:
                print(f"Warning: Failed to analyze {db_file}: {e}")
                
        return sorted(databases, key=lambda x: x['filename'])
        
    def _analyze_database(self, db_path: str) -> Optional[Dict]:
        """
        Analyze a tracking database to extract metadata and statistics.
        
        Args:
            db_path: Path to SQLite database
            
        Returns:
            Dictionary with database information or None if invalid
        """
        if not os.path.exists(db_path):
            return None
            
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Check if this is a valid ethoscope database
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            if 'ETHOSCOPE_DATA' not in tables:
                conn.close()
                return None
                
            # Get metadata
            metadata = {}
            if 'METADATA' in tables:
                cursor.execute("SELECT key, value FROM METADATA")
                for key, value in cursor.fetchall():
                    try:
                        # Try to parse JSON values
                        metadata[key] = json.loads(value)
                    except:
                        metadata[key] = value
                        
            # Get data statistics
            cursor.execute("SELECT COUNT(*) FROM ETHOSCOPE_DATA")
            row_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT MIN(t), MAX(t) FROM ETHOSCOPE_DATA")
            time_range = cursor.fetchone()
            min_time, max_time = time_range if time_range[0] is not None else (0, 0)
            
            # Get ROI information
            cursor.execute("SELECT DISTINCT roi_idx FROM ETHOSCOPE_DATA")
            roi_indices = [row[0] for row in cursor.fetchall()]
            
            conn.close()
            
            # Parse filename for experiment info
            filename = os.path.basename(db_path)
            file_parts = self._parse_filename(filename)
            
            return {
                'filename': filename,
                'filepath': db_path,
                'metadata': metadata,
                'statistics': {
                    'row_count': row_count,
                    'duration_ms': max_time - min_time,
                    'duration_minutes': (max_time - min_time) / (1000 * 60) if max_time > min_time else 0,
                    'roi_count': len(roi_indices),
                    'roi_indices': roi_indices,
                    'start_time': min_time,
                    'end_time': max_time
                },
                'experiment': file_parts,
                'file_size_mb': os.path.getsize(db_path) / (1024 * 1024)
            }
            
        except Exception as e:
            print(f"Error analyzing database {db_path}: {e}")
            return None
            
    def _parse_filename(self, filename: str) -> Dict:
        """
        Parse tracking database filename to extract experiment information.
        
        Expected format: tracking_m{machine}_r{roi}_{date}_{time}_{genotype}_{group}.db
        """
        try:
            # Remove extension
            name = filename.replace('.db', '')
            parts = name.split('_')
            
            if len(parts) >= 6 and parts[0] == 'tracking':
                return {
                    'machine': parts[1][1:] if parts[1].startswith('m') else parts[1],
                    'roi': parts[2][1:] if parts[2].startswith('r') else parts[2],
                    'date': parts[3],
                    'time': parts[4], 
                    'genotype': parts[5],
                    'group': parts[6] if len(parts) > 6 else 'unknown'
                }
        except:
            pass
            
        return {
            'machine': 'unknown',
            'roi': 'unknown', 
            'date': 'unknown',
            'time': 'unknown',
            'genotype': 'unknown',
            'group': 'unknown'
        }
        
    def get_databases_summary(self) -> Dict:
        """Get summary statistics for all discovered databases."""
        if not self.databases:
            return {
                'total_databases': 0,
                'total_experiments': 0,
                'machines': [],
                'genotypes': [],
                'groups': [],
                'total_data_points': 0,
                'total_duration_hours': 0,
                'total_size_mb': 0
            }
            
        machines = set()
        genotypes = set()
        groups = set()
        total_points = 0
        total_duration = 0
        total_size = 0
        
        for db in self.databases:
            exp = db['experiment']
            stats = db['statistics']
            
            machines.add(exp['machine'])
            genotypes.add(exp['genotype']) 
            groups.add(exp['group'])
            
            total_points += stats['row_count']
            total_duration += stats['duration_minutes']
            total_size += db['file_size_mb']
            
        return {
            'total_databases': len(self.databases),
            'total_experiments': len(self.databases),
            'machines': sorted(machines),
            'genotypes': sorted(genotypes),
            'groups': sorted(groups),
            'total_data_points': total_points,
            'total_duration_hours': total_duration / 60,
            'total_size_mb': total_size
        }
        
    def export_to_csv(self, output_file: str = None, 
                     include_raw_data: bool = False) -> str:
        """
        Export tracking results to CSV format.
        
        Args:
            output_file: Output CSV filename
            include_raw_data: Whether to include all tracking data points
            
        Returns:
            Path to created CSV file
        """
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"cupido_results_{timestamp}.csv"
            
        output_path = os.path.join(self.output_dir, output_file)
        
        if include_raw_data:
            return self._export_raw_data_csv(output_path)
        else:
            return self._export_summary_csv(output_path)
            
    def _export_summary_csv(self, output_path: str) -> str:
        """Export experiment summary to CSV."""
        with open(output_path, 'w', newline='') as csvfile:
            fieldnames = [
                'filename', 'machine', 'roi', 'genotype', 'group',
                'date', 'time', 'duration_minutes', 'data_points',
                'roi_count', 'file_size_mb', 'tracker_class'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for db in self.databases:
                exp = db['experiment']
                stats = db['statistics']
                metadata = db['metadata']
                
                row = {
                    'filename': db['filename'],
                    'machine': exp['machine'],
                    'roi': exp['roi'],
                    'genotype': exp['genotype'],
                    'group': exp['group'],
                    'date': exp['date'],
                    'time': exp['time'],
                    'duration_minutes': round(stats['duration_minutes'], 2),
                    'data_points': stats['row_count'],
                    'roi_count': stats['roi_count'],
                    'file_size_mb': round(db['file_size_mb'], 2),
                    'tracker_class': metadata.get('tracker_class', 'unknown')
                }
                
                writer.writerow(row)
                
        print(f"Summary CSV exported to: {output_path}")
        return output_path
        
    def _export_raw_data_csv(self, output_path: str) -> str:
        """Export all raw tracking data to CSV."""
        with open(output_path, 'w', newline='') as csvfile:
            fieldnames = [
                'experiment', 'machine', 'roi', 'genotype', 'group',
                't', 'roi_idx', 'x', 'y', 'w', 'h', 'phi',
                'tracking_frame_idx', 'has_moved'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for i, db in enumerate(self.databases):
                print(f"Exporting raw data from {db['filename']} ({i+1}/{len(self.databases)})")
                
                exp = db['experiment']
                
                try:
                    conn = sqlite3.connect(db['filepath'])
                    cursor = conn.cursor()
                    
                    # Get all tracking data
                    cursor.execute("""
                        SELECT t, roi_idx, x, y, w, h, phi, 
                               tracking_frame_idx, has_moved
                        FROM ETHOSCOPE_DATA 
                        ORDER BY t, roi_idx
                    """)
                    
                    for row in cursor.fetchall():
                        data_row = {
                            'experiment': db['filename'].replace('.db', ''),
                            'machine': exp['machine'],
                            'roi': exp['roi'],
                            'genotype': exp['genotype'],
                            'group': exp['group'],
                            't': row[0],
                            'roi_idx': row[1],
                            'x': row[2],
                            'y': row[3],
                            'w': row[4],
                            'h': row[5],
                            'phi': row[6],
                            'tracking_frame_idx': row[7],
                            'has_moved': row[8]
                        }
                        
                        writer.writerow(data_row)
                        
                    conn.close()
                    
                except Exception as e:
                    print(f"Error exporting data from {db['filename']}: {e}")
                    
        print(f"Raw data CSV exported to: {output_path}")
        return output_path
        
    def generate_report(self, output_file: str = None) -> str:
        """
        Generate a comprehensive analysis report.
        
        Args:
            output_file: Output report filename
            
        Returns:
            Path to created report file
        """
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"cupido_report_{timestamp}.md"
            
        output_path = os.path.join(self.output_dir, output_file)
        
        summary = self.get_databases_summary()
        
        with open(output_path, 'w') as f:
            f.write("# Cupido Offline Tracking Results Report\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Summary statistics
            f.write("## Summary Statistics\n\n")
            f.write(f"- **Total Experiments**: {summary['total_experiments']}\n")
            f.write(f"- **Total Data Points**: {summary['total_data_points']:,}\n")
            f.write(f"- **Total Duration**: {summary['total_duration_hours']:.1f} hours\n")
            f.write(f"- **Total Data Size**: {summary['total_size_mb']:.1f} MB\n\n")
            
            # Experiment breakdown
            f.write("## Experiment Breakdown\n\n")
            f.write(f"- **Machines**: {', '.join(summary['machines'])}\n")
            f.write(f"- **Genotypes**: {', '.join(summary['genotypes'])}\n") 
            f.write(f"- **Groups**: {', '.join(summary['groups'])}\n\n")
            
            # Detailed experiment list
            f.write("## Detailed Experiment List\n\n")
            f.write("| Experiment | Machine | ROI | Genotype | Group | Duration (min) | Data Points |\n")
            f.write("|------------|---------|-----|----------|-------|----------------|-------------|\n")
            
            for db in self.databases:
                exp = db['experiment']
                stats = db['statistics']
                f.write(f"| {db['filename'].replace('.db', '')} | "
                       f"{exp['machine']} | {exp['roi']} | {exp['genotype']} | "
                       f"{exp['group']} | {stats['duration_minutes']:.1f} | "
                       f"{stats['row_count']:,} |\n")
                       
            # Data quality assessment
            f.write("\n## Data Quality Assessment\n\n")
            
            # Check for experiments with no data
            empty_experiments = [db for db in self.databases if db['statistics']['row_count'] == 0]
            if empty_experiments:
                f.write("### ⚠️ Experiments with No Data\n\n")
                for db in empty_experiments:
                    f.write(f"- {db['filename']}\n")
                f.write("\n")
                
            # Check for very short experiments (< 1 minute)
            short_experiments = [db for db in self.databases if db['statistics']['duration_minutes'] < 1]
            if short_experiments:
                f.write("### ⚠️ Very Short Experiments (<1 minute)\n\n")
                for db in short_experiments:
                    f.write(f"- {db['filename']}: {db['statistics']['duration_minutes']:.1f} min\n")
                f.write("\n")
                
            # Activity summary by group
            f.write("## Activity Summary by Group\n\n")
            
            group_stats = {}
            for db in self.databases:
                group = db['experiment']['group']
                if group not in group_stats:
                    group_stats[group] = {
                        'experiments': 0,
                        'total_points': 0,
                        'total_duration': 0
                    }
                    
                group_stats[group]['experiments'] += 1
                group_stats[group]['total_points'] += db['statistics']['row_count']
                group_stats[group]['total_duration'] += db['statistics']['duration_minutes']
                
            for group, stats in group_stats.items():
                avg_duration = stats['total_duration'] / stats['experiments'] if stats['experiments'] > 0 else 0
                avg_points = stats['total_points'] / stats['experiments'] if stats['experiments'] > 0 else 0
                
                f.write(f"### {group.title()} Group\n")
                f.write(f"- Experiments: {stats['experiments']}\n")
                f.write(f"- Average Duration: {avg_duration:.1f} minutes\n")
                f.write(f"- Average Data Points: {avg_points:.0f}\n\n")
                
        print(f"Analysis report generated: {output_path}")
        return output_path
        
    def validate_results(self) -> Dict:
        """
        Validate tracking results and identify potential issues.
        
        Returns:
            Dictionary with validation results
        """
        issues = []
        warnings = []
        
        for db in self.databases:
            filename = db['filename']
            stats = db['statistics']
            
            # Check for empty databases
            if stats['row_count'] == 0:
                issues.append(f"{filename}: No tracking data")
                
            # Check for very short tracking
            elif stats['duration_minutes'] < 1:
                warnings.append(f"{filename}: Very short duration ({stats['duration_minutes']:.1f} min)")
                
            # Check for missing ROI data
            elif stats['roi_count'] == 0:
                issues.append(f"{filename}: No ROI data found")
                
        return {
            'total_databases': len(self.databases),
            'valid_databases': len(self.databases) - len(issues),
            'issues': issues,
            'warnings': warnings,
            'validation_passed': len(issues) == 0
        }
        
    def print_summary(self):
        """Print summary of results."""
        summary = self.get_databases_summary()
        validation = self.validate_results()
        
        print(f"\n📊 Cupido Results Summary")
        print(f"Results directory: {self.results_dir}")
        print(f"Output directory: {self.output_dir}")
        
        print(f"\n📈 Statistics:")
        print(f"   Total experiments: {summary['total_experiments']}")
        print(f"   Total data points: {summary['total_data_points']:,}")
        print(f"   Total duration: {summary['total_duration_hours']:.1f} hours")
        print(f"   Total size: {summary['total_size_mb']:.1f} MB")
        
        print(f"\n🧬 Experiment Coverage:")
        print(f"   Machines: {', '.join(summary['machines'])}")
        print(f"   Genotypes: {', '.join(summary['genotypes'])}")
        print(f"   Groups: {', '.join(summary['groups'])}")
        
        print(f"\n✅ Data Validation:")
        print(f"   Valid databases: {validation['valid_databases']}/{validation['total_databases']}")
        
        if validation['issues']:
            print(f"   ❌ Issues found: {len(validation['issues'])}")
            for issue in validation['issues'][:3]:  # Show first 3 issues
                print(f"      {issue}")
            if len(validation['issues']) > 3:
                print(f"      ... and {len(validation['issues']) - 3} more")
                
        if validation['warnings']:
            print(f"   ⚠️ Warnings: {len(validation['warnings'])}")
            for warning in validation['warnings'][:3]:  # Show first 3 warnings
                print(f"      {warning}")
            if len(validation['warnings']) > 3:
                print(f"      ... and {len(validation['warnings']) - 3} more")


def main():
    """Test the results manager functionality."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Cupido Results Manager')
    parser.add_argument('--results-dir', '-r',
                       default='results/tracking',
                       help='Directory containing tracking databases')
    parser.add_argument('--output', '-o',
                       default='results/analysis',
                       help='Output directory for analysis')
    parser.add_argument('--export-csv', '-c', action='store_true',
                       help='Export summary to CSV')
    parser.add_argument('--export-raw', action='store_true',
                       help='Export raw data to CSV (warning: large files!)')
    parser.add_argument('--generate-report', '-g', action='store_true',
                       help='Generate analysis report')
    parser.add_argument('--validate', '-v', action='store_true',
                       help='Validate results only')
    
    args = parser.parse_args()
    
    # Create results manager
    manager = CupidoResultsManager(args.results_dir, args.output)
    
    # Print summary
    manager.print_summary()
    
    if args.validate:
        validation = manager.validate_results()
        print(f"\n🔍 Validation Results:")
        print(f"   Passed: {validation['validation_passed']}")
        if not validation['validation_passed']:
            print("   Issues found - see summary above")
            
    if args.export_csv:
        csv_file = manager.export_to_csv(include_raw_data=args.export_raw)
        print(f"\n📁 CSV exported to: {csv_file}")
        
    if args.generate_report:
        report_file = manager.generate_report()
        print(f"\n📋 Report generated: {report_file}")


if __name__ == "__main__":
    main()