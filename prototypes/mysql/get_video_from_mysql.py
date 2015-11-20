import MySQLdb
import sys
import base64
import cStringIO
import shutil
import cv2

db = MySQLdb.connect(user='ethoscope', passwd='ethoscope',
                              host='localhost',
                              db='ethoscope_db')

cursor=db.cursor()

# write
# image = cv2.imread('test.jpg')
# blob_value = open('test.jpg', 'rb').read()
# sql = 'INSERT INTO img(t,images) VALUES(%s,%s)'
# args = (33, blob_value)
#
# cursor.execute(sql,args)
# db.commit()

## read
sql1='select id,t,img from IMG_SNAPSHOTS'
db.commit()
cursor.execute(sql1)
for i,c in enumerate(cursor):
    id, t, blob = c
    print i, blob[0:10]

    file_name = "/tmp/test/%05d_%i.jpg" % (id, t)

#     print type(data[0][0])
    file_like = cStringIO.StringIO(blob)
    out_file = open(file_name, "wb")
    file_like.seek(0)
    shutil.copyfileobj(file_like, out_file)
    # im = cv2.imread(out_file)
    # cv2.imshow(file_name, im)
    # cv2.waitKey(-1)

#
# #
#
# #img=PIL.Image.open(file_like)
# #img.show()

db.close()