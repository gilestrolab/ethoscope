__author__ = 'quentin'


import MySQLdb
import sqlite3

def copy_table(table_name, src, dst):
    src_cur = src.cursor()
    dst_cur = dst.cursor()
    src_command = "SHOW COLUMNS FROM %s " % table_name

    src_cur.execute(src_command )
    col_list = []
    for c in src_cur:
         col_list.append(" ".join(c[0:2]))

    formated_cols_names = ", ".join(col_list)

    dst_command = "DROP TABLE IF EXISTS %s" % table_name
    dst_cur.execute(dst_command)
    dst_command = "CREATE TABLE %s (%s) " % (table_name ,formated_cols_names)
    dst_cur.execute(dst_command)

    src_command = "SELECT * FROM %s " % table_name

    src_cur.execute(src_command)
    for c in src_cur:
        tp = tuple([str(v) for v in c ])

        dst_command = "INSERT INTO %s VALUES %s" % (table_name, tp)
        dst_cur.execute(dst_command)
    dst.commit()



def update_one_roi_table(table_name, src, dst):
    #FIXME copy table if not exist
    src_cur = src.cursor()
    dst_cur = dst.cursor()


    dst_command= "SELECT t FROM %s ORDER BY t DESC LIMIT 1" % table_name

    dst_cur.execute(dst_command)
    last_t_in_dst = 0
    for c in dst_cur:
        last_t_in_dst = c[0]


    src_command = "SELECT * FROM %s WHERE t > %d" % (table_name, last_t_in_dst)

    src_cur.execute(src_command)

    for sc in src_cur:
        tp = tuple([str(v) for v in sc ])
        dst_command = "INSERT INTO %s VALUES %s" % (table_name, tp)
        dst_cur.execute(dst_command)

    dst.commit()


def update_roi_tables(src, dst):

    src_cur = src.cursor()

    command = "SELECT roi_idx FROM ROI_MAP"

    src_cur.execute(command)

    rois_in_src = set([c[0] for c in src_cur])

    for i in rois_in_src :
        print i
        update_one_roi_table("ROI_%i" % i, mysql_db, conn)





mysql_db = MySQLdb.connect(host="localhost",
                     user="root",
                      passwd="",
                      db="psv_db")
conn = sqlite3.connect("/tmp/sqlite_test.db", check_same_thread=False)


copy_table("VAR_MAP", mysql_db, conn)
copy_table("METADATA", mysql_db, conn)

src_cur = mysql_db.cursor()
command = "SELECT roi_idx FROM ROI_MAP"
src_cur.execute(command)
rois_in_src = set([c[0] for c in src_cur])

for i in rois_in_src:
    copy_table("ROI_%i" % i, mysql_db, conn)



import time
try:
    while True:
        mysql_db = MySQLdb.connect(host="localhost",user="root",passwd="",db="psv_db")

        update_roi_tables(mysql_db, conn)
        print "bouya"
        # update_one_roi_table("ROI_3",mysql_db, conn)
        time.sleep(5)
except Exception as e:
    print e

# cur = db.cursor()

