__author__ = 'diana'
import sqlite3
import mysql.connector

src = mysql.connector.connect(user='root', passwd='mysql',
                              host='localhost',
                              db='testdb')
table_name = 'img'

with sqlite3.connect('output_sqlite.db', check_same_thread=False) as dst:
    src_cur = src.cursor()
    dst_cur = dst.cursor()
    src_command = "SHOW COLUMNS FROM %s " % table_name

    src_cur.execute(src_command )
    col_list = []
    for c in src_cur:
         col_list.append(" ".join(c[0:2]))

    formated_cols_names = ", ".join(col_list)
    print(formated_cols_names)

    dst_command = "DROP TABLE IF EXISTS %s" % table_name
    dst_cur.execute(dst_command)
    dst_command = "CREATE TABLE %s (%s) " % (table_name, formated_cols_names)
    dst_cur.execute(dst_command)

    src_command = "SELECT * FROM %s " % table_name

    src_cur.execute(src_command)
    for c in src_cur:
        tp = tuple([sqlite3.Binary(v) for v in c])
        command = '''INSERT INTO img
                    (images)
                    VALUES(?);'''
        dst_cur.execute(command, [sqlite3.Binary(tp[0])])

        # dst_command = "INSERT INTO %s VALUES %s" % (table_name, tp)
        # dst_cur.execute(dst_command)
    dst.commit()

with sqlite3.connect('output_sqlite.db', check_same_thread=False) as get_jpeg:

    cursor = get_jpeg.cursor()
    command = "SELECT images FROM %s " % table_name
    cursor.execute(command)
    img_blob = cursor.fetchone()[0]
    print("SAVING!!!!!!!!!!!!!")
    with open("img_from_sqlite.jpg", 'wb') as output_file:
        output_file.write(img_blob)