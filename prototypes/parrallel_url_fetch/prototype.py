__author__ = 'quentin'


import logging
import eventlet

import nmap
from psvnode.utils.helpers import scan_one_device


nm = nmap.PortScanner()

subnet = "129.31.135"
ip_range = (2,253)
to_scan = "%s.%i-%i" % (subnet, ip_range[0], ip_range[1])
scanned = nm.scan(to_scan, arguments="-sn")
url_candidates= ["http://%s" % str(s) for s in scanned["scan"].keys()]


pool = eventlet.GreenPool(200)
#
for id, ip in pool.imap(scan_one_device, url_candidates):
    if id is None:
        continue
    print id, ip

