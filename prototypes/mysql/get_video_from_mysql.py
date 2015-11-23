import sqlite3
import sys
import base64
import cStringIO
import shutil
import cv2


file = "/ethoscope_results/0001eeee10184bb39b0754e75cef7900/ETHOSCOPE_BENCH/2015-11-23_18-15-23/2015-11-23_18-15-23_0001eeee10184bb39b0754e75cef7900.db"
with sqlite3.connect(file, check_same_thread=False) as conn:
    cursor = conn.cursor()



    sql1 = 'select id,t,img from IMG_SNAPSHOTS'
    conn.commit()
    cursor.execute(sql1)
    for i,c in enumerate(cursor):
        id, t, blob = c


        file_name = "/tmp/test/%05d_%i.jpg" % (id, t)
        print file_name
        file_like = cStringIO.StringIO(blob)
        out_file = open(file_name, "wb")
        file_like.seek(0)
        shutil.copyfileobj(file_like, out_file)
