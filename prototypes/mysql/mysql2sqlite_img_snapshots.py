
__author__ = 'quentin'


from ethoscope_node.utils.helpers import generate_new_device_map
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError
import logging
import optparse
import time
import  multiprocessing
import  traceback
import os
import subprocess
import re


db_credentials = {
    "name":"ethoscope_db",
    "user":"ethoscope",
    "password":"ethoscope"
}


database_ip = "localhost"


mirror= MySQLdbToSQlite("/tmp/test.db", db_credentials["name"],
                            remote_host=database_ip,
                            remote_pass=db_credentials["password"],
                            remote_user=db_credentials["user"])

mirror.update_roi_tables()


