__author__ = 'quentin'

import mysql.connector

db = mysql.connector.connect(host="localhost",
                     user="root",
                      passwd="",
                      db="psv_db")


cur = db.cursor()


cur.execute("DROP TABLE IF EXISTS song")
cur.execute("CREATE TABLE song ( id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT, title TEXT NOT NULL )")
