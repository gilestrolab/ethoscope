__author__ = 'quentin'

import urllib.request, urllib.error, urllib.parse
import logging
import optparse
import  traceback
import subprocess
import json
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
from ethoscope_node.utils.configuration import EthoscopeConfiguration

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
        response = urllib.request.urlopen(url)
        out = [r.decode('utf-8').rstrip() for r in response]
    except urllib.error.HTTPError as e:
        logging.warning("No index file could be found for device %s" % ip)
        out = None
    finally:
        make_index(ip, port)
        return out

def remove_video_from_host(ip, id, target, port=9000):
    request_url = "{ip}:{port}/rm_static_file/{id}".format(ip=ip, id=id, port=port)
    data = {"file": target}
    data =json.dumps(data)
    req = urllib.request.Request(url=request_url, data= data, headers={'Content-Type': 'application/json'})
    _ = urllib.request.urlopen(req, timeout=5)


def make_index(ip, port=9000, page="make_index"):
    url = "/".join(["%s:%i"%(ip,port), page])
    try:
        response = urllib.request.urlopen(url)
        return True
    except urllib.error.HTTPError as e:
        logging.warning("No index file could be found for device %s" % ip)
        return False


def get_all_videos(device_info, out_dir, port=9000, static_dir="static"):
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
    try:
        device_info, video_result_dir = args
        logging.info("Initiating backup for device  %s" % device_info["id"])
        
        get_all_videos(device_info, video_result_dir)
        logging.info("Backup done for for device  %s" % device_info["id"])
        return 1
        
    except Exception as e:
        logging.error("Unexpected error in backup. args are: %s" % str(args))
        logging.error(traceback.format_exc())
        return


if __name__ == '__main__':
    
    CFG = EthoscopeConfiguration()

    logging.getLogger().setLevel(logging.INFO)
    try:
        parser = optparse.OptionParser()
        parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-i", "--server", dest="server", default="localhost", help="The server on which the node is running will be interrogated first for the device list")        
        parser.add_option("-r", "--results-dir", dest="video_dir", help="Where video files are stored")
        parser.add_option("-s", "--safe", dest="safe", default=False,help="Set Safe mode ON", action="store_true")
        parser.add_option("-e", "--ethoscope", dest="ethoscope", help="Force backup of given ethoscope number (eg: 007)")


        (options, args) = parser.parse_args()
        option_dict = vars(options)
        VIDEO_DIR = option_dict["video_dir"] or CFG.content['folders']['video']['path']
        SAFE_MODE = option_dict["safe"]
        DEBUG = option_dict["debug"]

        ethoscope = option_dict["ethoscope"]
        server = option_dict["server"]

        if DEBUG:
            logging.basicConfig()
            logging.getLogger().setLevel(logging.DEBUG)
            logging.info("Logging using DEBUG SETTINGS")


        if ethoscope:
            ethoscope = int(ethoscope)
            print ("Forcing backup for ethoscope %03d" % ethoscope)
            all_devices = receive_devices(server)
            
            bj = None
            for devID in all_devices:
                if all_devices[devID]['name'] == ("ETHOSCOPE_%03d" % ethoscope) and all_devices[devID]['status'] != "offline":
                    bj = backup_job((all_devices[devID], VIDEO_DIR))
            if bj == None: exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)

        else:
            gbw = GenericBackupWrapper(     VIDEO_DIR,
                                            server, 
                                            video=True)
            gbw.run()
        
    except Exception as e:
        logging.error(traceback.format_exc())
