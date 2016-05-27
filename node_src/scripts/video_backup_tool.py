__author__ = 'quentin'

import urllib2
import logging
import optparse
import  traceback
import subprocess
import json
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
from ethoscope_node.utils.helpers import  get_local_ip

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


def get_video_list(ip, port=9000,static_dir = "static", index_file="ethoscope_data/results/index.html"):
    url = "/".join(["%s:%i"%(ip,port), static_dir, index_file])
    try:
        response = urllib2.urlopen(url)
        return [r.rstrip() for r in response]
    except urllib2.HTTPError as e:
        logging.warning("No index file could be found for device %s" % ip)
        return None

def remove_video_from_host(ip, id, target, port=9000):
    request_url = "{ip}:{port}/rm_static_file/{id}".format(ip=ip, id=id, port=port)
    data = {"file": target}
    data =json.dumps(data)
    req = urllib2.Request(url=request_url, data= data, headers={'Content-Type': 'application/json'})
    _ = urllib2.urlopen(req, timeout=5)



def get_all_videos(device_info,out_dir, port=9000, static_dir="static"):
    url = "http://" + device_info["ip"]
    id = device_info["id"]
    video_list = get_video_list(url, port=port, static_dir=static_dir)
    #backward compatible. if no index, we do not stop
    if video_list is None:
        return
    target_prefix = "/".join(["%s:%i"%(url,port), static_dir])
    for v in video_list:
        try:
            current = wget_mirror_wrapper(v, target_prefix=target_prefix, output_dir=out_dir)
        except WGetERROR as e:
            logging.warning(e)
            continue

        if not current:
            # we only attempt to remove if the files is mirrored
            remove_video_from_host(url, id, v)

def backup_job(args):
    device_info, video_result_dir = args
    logging.info("Initiating backup for device  %s" % device_info["id"])
    get_all_videos(device_info, video_result_dir)
    logging.info("Backup done for for device  %s" % device_info["id"])


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    try:
        parser = optparse.OptionParser()
        parser = optparse.OptionParser()
        parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-e", "--results-dir", dest="results_dir", default="/ethoscope_videos",
                          help="Where temporary result files are stored")

        parser.add_option("-r", "--subnet-ip", dest="subnet_ip", default="192.169.123.0",
                          help="the ip of the router in your setup")
        parser.add_option("-s", "--safe", dest="safe", default=False,help="Set Safe mode ON", action="store_true")
        parser.add_option("-l", "--local", dest="local", default=False,
                          help="Run on localhost (run a node and device on the same machine, for development)",
                          action="store_true")
        (options, args) = parser.parse_args()
        option_dict = vars(options)

        local_ip= get_local_ip(option_dict["subnet_ip"],localhost = option_dict["local"])

        (options, args) = parser.parse_args()
        option_dict = vars(options)

        gbw = GenericBackupWrapper( backup_job,
                                    option_dict["results_dir"],
                                    option_dict["safe"], local_ip
                                    )
        gbw.run()
    except Exception as e:
        logging.error(traceback.format_exc(e))
