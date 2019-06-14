
#/data/ethoscope_results/008aeeee10184bb39b0754e75cef7900/ETHOSCOPE_008/2015-11-09_18-05-18/2015-11-09_18-05-18_008aeeee10184bb39b0754e75cef7900.db



from glob import glob
import os
import time
import db2video


PATH = "/data/ethoscope_results"
files = [y for x in os.walk(PATH) for y in glob(os.path.join(x[0], '*.db'))]


def touch(fname, times=None):
    with open(fname, 'a'):
        os.utime(fname, times)

for f in sorted(files):
    ts_file = os.path.join(os.path.dirname(f), ".tstamp")
    if os.path.isfile(ts_file):
        last_tstamp = time.ctime(os.path.getmtime(ts_file))
        db_tstamp = time.ctime(os.path.getmtime(f))
        if last_tstamp > db_tstamp:
        #if  True:
            output = os.path.splitext(f)[0] + ".mp4"
            print(("generating " + output))
            try:
                db2video.make_video_file(f, output)

                touch(ts_file)
            except Exception as e:
                print("could not generate" + output)
                print(e)

    #print f, time.ctime(os.path.getmtime(f))

