import os
import time
import socket

def get_last_backup_time(device):
    try:
        backup_path = device["backup_path"]
        time_since_last_backup = time.time() - os.path.getmtime(backup_path)
        return time_since_last_backup
    except Exception:
        return "No backup"

def get_local_ip(local_subnet_ip ="192.169.123.0", max_node_subnet_address=5, localhost=False):
    subnet_ip_list = local_subnet_ip.split(".")
    local_router_ip = ".".join(subnet_ip_list[0:3] + ["254"])
    if localhost:
        return "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((local_router_ip, 80))
    except socket.gaierror:
        raise Exception("Cannot find local ip, check your connection")
    ip = s.getsockname()[0]
    s.close()

    ip_list = ip.split(".")
    if subnet_ip_list[0:3] != ip_list[0:3]:
        raise Exception("The local ip address does not match the expected router subnet: %s != %s" % (str(subnet_ip_list[0:3]), str(ip_list[0:3])))
    if  int(ip_list[3]) >  max_node_subnet_address:
        raise Exception("The the last field of the node ip should be lower or equal to %i. current ip = %s" % (max_node_subnet_address, ip))
    return ip

def get_internet_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("google.com", 80))
    except socket.gaierror:
        raise Exception("Cannot find internet (www) connection")

    ip = s.getsockname()[0]
    s.close()
    return ip
