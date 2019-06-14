"""
A script to exctract frames from a .db file and create a video.
There are to external deps: ffmpeg and imagemagick.
"""
import sqlite3
import io
import tempfile
import shutil
import os
from optparse import OptionParser
import datetime
import glob
from multiprocessing import Pool



def annotate_image(args):
    input, time, t0 = args
    label = datetime.datetime.fromtimestamp(time/1000 + t0).strftime('%Y-%m-%d %H:%M:%S')
    out = input+"_tmp.jpg"

    command = "convert %s -pointsize 50  -font FreeMono -background Khaki  label:'%s' +swap -gravity Center -append %s" % (input, label, out)
    os.system(command)
    shutil.move(out,input)

def make_video_file(file, output, fps=1, annotate=True):

    dir = tempfile.mkdtemp(prefix="etho_video")
    try:
        with sqlite3.connect(file, check_same_thread=False) as conn:
            cursor = conn.cursor()
            sql_metadata = 'select * from METADATA'
            conn.commit()
            cursor.execute(sql_metadata)
            t0 = 0
            for field, value in cursor:
                if field == "date_time":
                    t0 = float(value)

            sql1 = 'select id,t,img from IMG_SNAPSHOTS'
            conn.commit()
            cursor.execute(sql1)



            for i,c in enumerate(cursor):
                id, t, blob = c
                file_name = os.path.join(dir,"%05d_%i.jpg" % (id, t))

                file_like = io.StringIO(blob)
                out_file = open(file_name, "wb")
                file_like.seek(0)
                shutil.copyfileobj(file_like, out_file)


            pool = Pool(4)
            pool_args = []
            for f in glob.glob(os.path.join(dir , "*.jpg")):
                t = int(os.path.basename(f).split("_")[1].split(".")[0])
                pool_args.append((f,t,t0))


            pool.map(annotate_image,pool_args)


            # if option_dict["annot"]:


        command = "ffmpeg -loglevel panic -y -framerate %i -pattern_type glob -i '%s/*.jpg' -c:v libx264 %s" % (fps, dir, output)
        os.system(command)

    finally:
        shutil.rmtree(dir)





if __name__ == '__main__':

    ETHOGRAM_DIR = "/ethoscope_data/results"
    MACHINE_ID_FILE = '/etc/machine-id'
    MACHINE_NAME_FILE = '/etc/machine-name'

    parser = OptionParser()
    parser.add_option("-i", "--input", dest="input", help="The input .db file")
    parser.add_option("-o", "--output", dest="output", help="The output mp4")
    parser.add_option("-f", "--fps", dest="fps", default=1, help="The output fps")
    parser.add_option("-a", "--annotate", dest="annot", default=False, help="Whether date and time should be written on the bottom of the frames", action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)



    make_video_file(option_dict["input"],
                    option_dict["output"],
                    option_dict["fps"],
                    option_dict["annot"]
                    )
