"""
A tool to backup incrementally one source to one destination directory.
It copies files to the destination if and only if they are larger than in the destination
"""


from optparse import OptionParser
import os
import shutil
import glob
import  time


def copy_one_file(src, dst):
    src_size = os.stat(src).st_size
    if os.path.exists(dst):
        dst_size = os.stat(dst).st_size
    else:
        dst_size = 0
    if src_size > dst_size:
        target_dir = os.path.dirname(dst)
        if not os.path.exists(target_dir ):
            os.makedirs(target_dir)
        if (VERBOSE):
            print (src + " =======> " + dst)
        shutil.copy2(src, dst)
        return 1, src_size

    if (VERBOSE):
        print("Skipping", src)
    return 0, src_size

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-s", "--src-dir", dest="src_dir", help="The source directory to be mirrored")
    parser.add_option("-d", "--dst-dir", dest="dst_dir", help="The destination dir to save data to")
    parser.add_option("-v", "--verbose", dest="verbose", help="Print progress/info", default=False, action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)
    LOCAL_RESULTS_ROOT = option_dict["src_dir"]
    REMOTE_RESULTS_ROOT = option_dict["dst_dir"]
    VERBOSE= option_dict["verbose"]
    PATTERN = '*.db'
    start_t  = time.time()
    total = 0.0
    processed = 0.0
    total_size = 0.0
    processed_size = 0.0
    for x in sorted(os.walk(LOCAL_RESULTS_ROOT)):
        for abs_path in glob.glob(os.path.join(x[0], PATTERN)):
            rel_path = os.path.relpath(abs_path,  start=LOCAL_RESULTS_ROOT)
            target_abs_path = os.path.join(REMOTE_RESULTS_ROOT, rel_path)
            pr, size = copy_one_file(abs_path, target_abs_path)
            processed += pr
            if pr:
                processed_size += size
            total += 1
            total_size += size

    delta_t = time.time() - start_t
    print("Backup finished. In %i s" % delta_t)
    print("%i files processed. %i files in total" % (processed, total))
    print("%f GB transferred. %f GB in total" % (processed_size/ 2 **30 , total_size / 2 **30))



