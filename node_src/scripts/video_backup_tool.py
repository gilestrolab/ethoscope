import urllib2
from ethoscope_node.utils.helpers import generate_new_device_map
import logging
import optparse
import time
import  multiprocessing
import  traceback
import os
import subprocess
import re
import json

class WGetERROR(Exception):
    pass

def wget_mirror_wrapper(target, target_prefix, output_dir, cut_dirs=3):
    target = target_prefix + target
    command_arg_list=  ["wget",
                        target,
                        "-nv",
                         "--mirror",
                         "--cut-dirs=%i" % cut_dirs,
                         "-nH",
                         "--directory-prefix=%s" % output_dir
                        ]
    p = subprocess.Popen(command_arg_list,  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise WGetERROR("Error %i: %s" % ( p.returncode,stdout))

    if stdout == "":
        return False
    return True

#
# turl = "/ethoscope_data/results/0001eeee10184bb39b0754e75cef7900/ETHOSCOPE_BENCH/2016-03-04_18-18-53/2016-03-04_18-18-53_0001eeee10184bb39b0754e75cef7900_0359.h264"
# wget_mirror_wrapper(turl)


def get_video_list(ip, port=9000,static_dir = "static", index_file="ethoscope_data/results/index.html"):
    url = "/".join(["%s:%i"%(ip,port), static_dir, index_file])
    try:
        response = urllib2.urlopen(url)
        return [r.rstrip() for r in response]
    except urllib2.HTTPError as e:
        logging.warning("No index file could be found for device %s" % ip)
        return None



def remove_video_from_host(ip, id, target, port=9000):
    print "asking %s to remove %s" %  (ip, target)
    request_url = "{ip}:{port}/rm_static_file/{id}".format(ip=ip, id=id, port=port)

    data = {"file": target}
    data =json.dumps(data)

    req = urllib2.Request(url=request_url, data= data, headers={'Content-Type': 'application/json'})

    #try:
    f = urllib2.urlopen(req, timeout=5)

    #except Exception as e:
#        logging.warning(e)



def get_all_videos(device_info,out_dir, port=9000, static_dir="static"):
    ip = device_info["ip"]
    id = device_info["id"]

    video_list = get_video_list(ip, port=port, static_dir=static_dir)

    #backward compatible. if no index, we do not stop
    if video_list is None:
        return
    target_prefix = "/".join(["%s:%i"%(ip,port), static_dir])
    for v in video_list:
        try:
            current = wget_mirror_wrapper(v, target_prefix=target_prefix, output_dir=out_dir)
        except WGetERROR as e:
            logging.warning(e)
            continue

        if not current:
            # we only attempt to remove if the files is mirrored
            remove_video_from_host(ip, id, v)

def backup_job(device_info):
    logging.info("Initiating backup for device  %s" % device_info["id"])
    get_all_videos(device_info, VIDEO_RESULTS_DIR)
    logging.info("Backup done for for device  %s" % device_info["id"])


if __name__ == '__main__':
    # TODO where to save the files and the logs

    logging.getLogger().setLevel(logging.INFO)

    try:
        parser = optparse.OptionParser()
        parser.add_option("-d", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-s", "--safe", dest="safe", default=False,help="Set Safe mode ON", action="store_true")


        (options, args) = parser.parse_args()

        option_dict = vars(options)
        DEBUG = option_dict["debug"]
        safe= option_dict["safe"]
        VIDEO_RESULTS_DIR = "/ethoscope_videos"


        p1 = subprocess.Popen(["ip", "link", "show"], stdout=subprocess.PIPE)
        network_devices, err = p1.communicate()

        wireless = re.search(r'[0-9]: (wl.*):', network_devices)
        if wireless is not None:
            SUBNET_DEVICE = wireless.group(1)
        else:
            logging.error("Not Wireless adapter has been detected. It is necessary for connect to Devices.")

        TICK = 1.0 #s
        BACKUP_DT = 5*60 # 5min
        t0 = time.time()
        t1 = t0 + BACKUP_DT


        while True:
            if t1 - t0 < BACKUP_DT:
                t1 = time.time()
                time.sleep(TICK)
                continue

            logging.info("Starting backup")
            logging.info("Generating device map")
            dev_map = generate_new_device_map(device=SUBNET_DEVICE,result_main_dir=VIDEO_RESULTS_DIR)
            logging.info("Regenerated device map")

            if safe ==True:
                map(backup_job, dev_map.values())
            else:
                pool = multiprocessing.Pool(4)

                pool_res =  pool.map(backup_job, dev_map.values())
                logging.info("Pool mapped")
                pool.close()
                logging.info("Joining now")
                pool.join()

            t1 = time.time()
            logging.info("Backup finished at t=%i" % t1)
            t0 = t1

    except Exception as e:
        logging.error(traceback.format_exc(e))
