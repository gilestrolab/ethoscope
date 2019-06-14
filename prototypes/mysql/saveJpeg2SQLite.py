__author__ = 'quentin'

import sqlite3
import os
from os import listdir, getcwd



DB_FILE = "/tmp/pict_db.db"
ORIGINAL_IMG = "./test.jpg"
NEW_IMG = "./out.jpg"

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

conn = sqlite3.connect(DB_FILE)

sql = '''create table if not exists PICTURES(
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        PICTURE BLOB
        );'''
conn.execute(sql)
conn.commit()

with open(ORIGINAL_IMG, 'rb') as input_file:
    ablob = input_file.read()

    sql = '''INSERT INTO PICTURES
        (PICTURE)
        VALUES(?);'''
    conn.execute(sql,[sqlite3.Binary(ablob)])
    conn.commit()
    print("boom")

conn.close()

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()
sql = "SELECT PICTURE FROM PICTURES WHERE id = 1"

cur.execute(sql)
ablob = cur.fetchone()[0]

with open(NEW_IMG, 'wb') as output_file:
    output_file.write(ablob)



