import os
import glob
from datetime import datetime
from typing import Optional, List, Dict, Any
import csv


def find_videos_for_metadata_row(date: str, time_hhmmss: str, machine_name: str, 
                                roi: int, videos_base_path: str = "/mnt/ethoscope_data/videos") -> List[str]:
    """
    Find video files based on metadata row information.
    
    Args:
        date: Date in format 'DD/MM/YYYY' (e.g., '15/07/2025')
        time_hhmmss: Time in format 'HH:MM:SS' (e.g., '16:03:10')
        machine_name: Machine name as string (e.g., '076')
        roi: ROI number as integer (1-6 typically)
        videos_base_path: Base path to videos directory
        
    Returns:
        List of video file paths that match the criteria
    """
    # Convert date format from DD/MM/YYYY to YYYY-MM-DD
    day, month, year = date.split('/')
    iso_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    
    # Convert time format from HH:MM:SS to HH-MM-SS
    iso_time = time_hhmmss.replace(':', '-')
    
    # Create the expected datetime prefix for video files
    datetime_prefix = f"{iso_date}_{iso_time}"
    
    # Pattern to search for ethoscope directories
    # Each directory is named with a unique ID and contains ETHOSCOPE_XXX subdirectories
    ethoscope_pattern = f"*/ETHOSCOPE_{machine_name.zfill(3)}"
    
    matching_videos = []
    
    # Search through all ethoscope directories
    ethoscope_dirs = glob.glob(os.path.join(videos_base_path, ethoscope_pattern))
    
    for ethoscope_dir in ethoscope_dirs:
        # Look for datetime subdirectories that match our target time
        datetime_dirs = glob.glob(os.path.join(ethoscope_dir, f"{datetime_prefix}*"))
        
        for datetime_dir in datetime_dirs:
            # Look for video files in this datetime directory
            # Video files can be .mp4, .h264, or .avi
            video_extensions = ['*.mp4', '*.avi', '*.h264']
            
            for ext in video_extensions:
                video_files = glob.glob(os.path.join(datetime_dir, ext))
                
                # Filter video files that contain the datetime and machine info
                for video_file in video_files:
                    filename = os.path.basename(video_file)
                    # Video files typically contain the datetime, unique ID, and sometimes ROI info
                    if datetime_prefix in filename and not filename.endswith('.md5'):
                        matching_videos.append(video_file)
    
    return sorted(matching_videos)


def process_metadata_csv(csv_path: str, videos_base_path: str = "/mnt/ethoscope_data/videos") -> Dict[int, Dict[str, Any]]:
    """
    Process a metadata CSV file and find corresponding videos for each row.
    
    Args:
        csv_path: Path to the CSV file containing metadata
        videos_base_path: Base path to videos directory
        
    Returns:
        Dictionary mapping row numbers to metadata and found videos
    """
    results = {}
    
    with open(csv_path, 'r', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row_num, row in enumerate(reader, start=1):
            date = row['date']
            time_hhmmss = row['HHMMSS']
            machine_name = row['machine_name']
            roi = int(row['ROI'])
            genotype = row['genotype']
            group = row['group']
            
            # Find videos for this metadata row
            videos = find_videos_for_metadata_row(
                date=date,
                time_hhmmss=time_hhmmss,
                machine_name=machine_name,
                roi=roi,
                videos_base_path=videos_base_path
            )
            
            results[row_num] = {
                'metadata': {
                    'date': date,
                    'time': time_hhmmss,
                    'machine_name': machine_name,
                    'roi': roi,
                    'genotype': genotype,
                    'group': group
                },
                'videos': videos,
                'video_count': len(videos)
            }
    
    return results


def find_video_by_criteria(date: str, time_hhmmss: str, machine_name: str, roi: int, 
                          videos_base_path: str = "/mnt/ethoscope_data/videos") -> Optional[str]:
    """
    Find a single video file based on specific criteria.
    
    Args:
        date: Date in format 'DD/MM/YYYY'
        time_hhmmss: Time in format 'HH:MM:SS'
        machine_name: Machine name as string
        roi: ROI number as integer
        videos_base_path: Base path to videos directory
        
    Returns:
        Path to the first matching video file, or None if not found
    """
    videos = find_videos_for_metadata_row(date, time_hhmmss, machine_name, roi, videos_base_path)
    return videos[0] if videos else None


def get_file_size_mb(file_path: str) -> float:
    """
    Get file size in megabytes.
    
    Args:
        file_path: Path to the file
        
    Returns:
        File size in MB, or 0 if file doesn't exist
    """
    try:
        if file_path and os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            size_mb = size_bytes / (1024 * 1024)
            return round(size_mb, 2)
        return 0.0
    except Exception:
        return 0.0


def add_video_paths_to_csv(csv_path: str, output_path: str = None, 
                          videos_base_path: str = "/mnt/ethoscope_data/videos") -> str:
    """
    Add video paths and file sizes to an existing CSV file by creating new 'path' and 'filesize_mb' columns.
    
    Args:
        csv_path: Path to the input CSV file
        output_path: Path for the output CSV file (if None, overwrites input)
        videos_base_path: Base path to videos directory
        
    Returns:
        Path to the updated CSV file
    """
    import pandas as pd
    
    # Read the CSV file
    df = pd.read_csv(csv_path, encoding='utf-8-sig')
    
    # Add new columns
    video_paths = []
    file_sizes = []
    
    for index, row in df.iterrows():
        date = row['date']
        time_hhmmss = row['HHMMSS']
        machine_name = str(row['machine_name'])
        roi = int(row['ROI'])
        
        # Find the video for this row
        video = find_video_by_criteria(
            date=date,
            time_hhmmss=time_hhmmss,
            machine_name=machine_name,
            roi=roi,
            videos_base_path=videos_base_path
        )
        
        video_paths.append(video if video else "")
        
        # Get file size
        file_size = get_file_size_mb(video) if video else 0.0
        file_sizes.append(file_size)
    
    # Add the columns
    df['path'] = video_paths
    df['filesize_mb'] = file_sizes
    
    # Determine output path
    if output_path is None:
        output_path = csv_path
    
    # Save the updated CSV
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    
    return output_path


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Find video files for metadata entries")
    parser.add_argument("csv_path", help="Path to the metadata CSV file")
    parser.add_argument("--videos-base-path", "-v", 
                        default="/mnt/ethoscope_data/videos",
                        help="Base path to videos directory (default: /mnt/ethoscope_data/videos)")
    parser.add_argument("--output-path", "-o",
                        help="Path for output CSV file (if not provided, will overwrite input file)")
    
    args = parser.parse_args()
    
    # Add video paths and file sizes to CSV
    print(f"Adding video paths and file sizes to CSV...")
    print(f"Metadata CSV: {args.csv_path}")
    print(f"Videos base path: {args.videos_base_path}")
    updated_csv = add_video_paths_to_csv(args.csv_path, args.output_path, args.videos_base_path)
    print(f"Updated CSV saved to: {updated_csv}")
    
    # Display a few results to verify
    print("\nVerifying results...")
    import pandas as pd
    df = pd.read_csv(updated_csv, encoding='utf-8-sig')
    
    print(f"CSV now has {len(df.columns)} columns: {list(df.columns)}")
    print(f"Total rows: {len(df)}")
    
    # Show first 5 rows
    print("\nFirst 5 rows:")
    for i in range(min(5, len(df))):
        row = df.iloc[i]
        print(f"Row {i+1}: Machine {row['machine_name']}, {row['date']} {row['HHMMSS']}")
        if row['path']:
            print(f"  Video: {row['path']}")
            print(f"  Size: {row['filesize_mb']} MB")
        else:
            print("  Video: Not found")
            print("  Size: 0 MB")
    
    # Check how many videos were found and calculate total size
    found_videos = df['path'].notna() & (df['path'] != "")
    total_size_mb = df['filesize_mb'].sum()
    total_size_gb = total_size_mb / 1024
    
    print(f"\nSummary:")
    print(f"  Videos found: {found_videos.sum()} out of {len(df)} rows")
    print(f"  Total size: {total_size_mb:.2f} MB ({total_size_gb:.2f} GB)")
    if found_videos.sum() > 0:
        print(f"  Average size per video: {total_size_mb/float(found_videos.sum()):.2f} MB")