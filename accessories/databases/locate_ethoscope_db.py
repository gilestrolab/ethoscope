#!/usr/bin/env python
import os
import fnmatch
import optparse

def find_db_file(base_path, ethoscope_number, experiment_date):
    """
    Finds database files that match the given ethoscope number and experiment date pattern.

    Args:
        base_path (str): The base directory to search in.
        ethoscope_number (int): The ethoscope number.
        experiment_date (str): The experiment date, supports wildcards (e.g., 2024-06-21*, 2024-06*).

    Returns:
        list: A list of matching file paths.
    """
    matches = []
    pattern = f"{experiment_date}_*_*{ethoscope_number:03d}*.db"
    
    # Walk through the directory and find matching files
    for root, dirnames, filenames in os.walk(base_path):
        for filename in fnmatch.filter(filenames, pattern):
            matches.append(os.path.join(root, filename))
    
    return matches

def main():
    parser = optparse.OptionParser(usage="usage: %prog -e ETHOSCOPE_NUMBER -d DATE_PATTERN [--basepath BASE_PATH]\n\n"
                                          "Examples:\n"
                                          "  %prog -e 268 -d 2024-06-21\n"
                                          "  %prog -e 268 -d 2024-06*\n"
                                          "  %prog -e 268 -d 2024*\n"
                                          "  %prog -e 268 -d 2024-06-21 --basepath /path/to/data")
    
    parser.add_option('-e', '--ethoscope', dest='ethoscope_number', type='int', help='Ethoscope number', metavar='ETHOSCOPE_NUMBER')
    parser.add_option('-d', '--date', dest='experiment_date', help='Experiment date pattern (e.g., 2024-06-21, 2024-06*, 2024*)', metavar='DATE_PATTERN')
    parser.add_option('--basepath', dest='base_path', default='/mnt/data/results', help='Base path to search in (default: /mnt/data/results)', metavar='BASE_PATH')
    
    (options, args) = parser.parse_args()
    
    if not options.ethoscope_number:
        parser.error('Ethoscope number not given')
    if not options.experiment_date:
        parser.error('Experiment date not given')
    
    matching_files = find_db_file(options.base_path, options.ethoscope_number, options.experiment_date)
    
    if matching_files:
        for file_path in matching_files:
            print(file_path)
    else:
        print("No matching database file found.")

if __name__ == "__main__":
    main()
