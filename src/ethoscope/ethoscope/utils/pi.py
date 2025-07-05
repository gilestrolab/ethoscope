import random
import logging
import traceback
import datetime, time
import os
import re
from uuid import uuid4
import netifaces
import git

from ethoscope.utils.rpi_bad_power import powerChecker


PERSISTENT_STATE = "/var/cache/ethoscope/persistent_state.pkl"

def pi_version():
    """
    Detect the version of the Raspberry Pi.
    https://www.raspberrypi.org/documentation/hardware/raspberrypi/revision-codes/README.md
    
    We used to use cat /proc/cpuinfo but as of the 4.9 kernel, all Pis report BCM2835, even those with BCM2836, BCM2837 and BCM2711 processors. 
    You should not use this string to detect the processor. Decode the revision code using the information in the URL above, or simply cat /sys/firmware/devicetree/base/model

    PI 1 Raspberry Pi Model B Plus Rev 1.2
    PI 2 Raspberry Pi 2 Model B Rev 1.1
    PI 3 Raspberry Pi 3 Model B Rev 1.2
    PI 4 Raspberry Pi 4 Model B Rev 1.5

    """
    
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as file:
            model_info = file.read().strip()

        match = re.search(r'Raspberry Pi (\d+)([A-Za-z ]+)', model_info)
        if match:
            model_number = int(match.group(1))
            model_type = match.group(2).strip()
        else:
            model_number = None
            model_type = None

        # Return the information as a dictionary
        return {'model_number': model_number, 'model_type': model_type}
    
    except Exception as e:
        return {'model_number': 0, 'model_type': None}
        #return {'error': str(e)}

def isMachinePI(version=None):
    """
    Return True if we are running on a Pi - proper ethoscope
    """
    pi_ver = pi_version()['model_number']

    if not version:
        return pi_ver > 0
    else:
        return (pi_ver == int(version))


def get_machine_name(path="/etc/machine-name"):
    """
    Reads the machine name
    This file will be present only on a real ethoscope
    When running locally, it will generate a randome name
    """
    
    if os.path.exists(path):
        with open(path,'r') as f:
            info = f.readline().rstrip()
        return info

    else:
        return 'VIRTUA_' + get_machine_id()[:3]
        
def set_machine_name(id, path="/etc/machine-name"):
    '''
    Takes an id and updates the machine name accordingly in the format
    ETHOSCOPE_id; changes the hostname too.
    
    :param id: integer
    '''
    
    machine_name = "ETHOSCOPE_%03d" % id
    try:
        with open(path, 'w') as f:
            f.write(machine_name)
        logging.warning("Wrote new information in file: %s" % path)
        
        with open("/etc/hostname", 'w') as f:
            f.write(machine_name)
        logging.warning("Changed the machine hostname to: %s" % machine_name)
        

    except:
        raise

def set_machine_id(id, path="/etc/machine-id"):
    '''
    Takes an id and updates the machine id accordingly in the format
    0ID-UUID to make a 32 bytes string
    
    :param id: integer
    '''

    new_uuid = "%03d" % id + uuid4().hex[3:]
    
    try:
        with open(path, 'w') as f:
            f.write(new_uuid)
        logging.warning("Wrote new information in file: %s" % path)
            
    except:
        raise

def get_Network_Service():
    """
    Detects wether we are using systemd-networkd or netctl
    """
    daemon = {'netctl' : False, 'systemd' : False}

    with os.popen('systemctl is-active netctl@wlan.service') as df:
        status = df.read()
    if status.startswith('active'): daemon['netctl'] = True 
    
    with os.popen('systemctl is-active systemd-networkd.service') as df:
        status = df.read()
    if status.startswith('active'): daemon['systemd'] = True 

    return daemon


def get_WIFI():
    """
    Will return a dictionary like the following:
    
    {'Description': 'ethoscope_wifi network', 
     'Interface': 'wlan0', 
     'Connection': 'wireless', 
     'Security': 'wpa', 
     'ESSID': 'ETHOSCOPE_WIFI', 
     'Key': 'ETHOSCOPE_1234', 
     'IP': 'static', 
     'Address': "('192.168.1.203/24')", 
     'Gateway': "'192.168.1.1'"}

    """
    network_service = get_Network_Service()
    data = {}
    
    if network_service['netctl']:
        netctl_file = "/etc/netctl/wlan"
        with open(netctl_file,'r') as f:
            wlan_settings = f.readlines()
        
        for line in wlan_settings:
            if "=" in line:
                data[ line.strip().split("=")[0] ] =  line.strip().split("=")[1]
        
        data['netctl'] = True

    if network_service['systemd']:
        wpasupplicant_file = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
        systemd_file = "/etc/systemd/network/25-wireless.network"       

        with open(wpasupplicant_file,'r') as f:
            wlan_settings = f.readlines()
        
        for line in wlan_settings:
            if "=" in line:
                data[ line.strip().split("=")[0] ] =  line.strip().split("=")[1].replace('"', '')

        data['systemd'] = True
        data['ESSID'] = data['ssid']
        data['Key'] = data['#psk']

        with os.popen("/sbin/ip -o -4 addr list eth0 | awk '{print $4}' | cut -d/ -f1") as cmd:
            data['IP'] = cmd.read().strip()

        with os.popen("ip route | grep default | head -n 1 | cut -d ' ' -f 3") as cmd:
            data['Gateway'] = cmd.read().strip()

        with open(systemd_file,'r') as f:
            net_settings = f.readlines()
        
        for line in net_settings:
            if "=" in line:
                data[ line.strip().split("=")[0] ] =  line.strip().split("=")[1]

    return data


def get_static_IPV4():
    """
    """

    with os.popen("ip route | grep default | head -n 1 | cut -d ' ' -f 3") as cmd:
        gateway = cmd.read().strip()

    a,b,c,_ = gateway.split('.')
    d = int(get_machine_name().split('_')[-1])
    
    if int(d) > 1 and int(d) < 255:
        ip_address = '.'.join([a,b,c,str(d)])
    else: #out of range
        ip_address = None

    return ip_address, gateway
    

def set_WIFI(ssid="ETHOSCOPE_WIFI", wpakey="ETHOSCOPE_1234", useSTATIC=False):
    """
    Receives the setting for wifi connection
    Uses dhcp by default but if USE_DHCP is set to False, it will adopt a static ip address instead
    """

    ip_address, gateway = get_static_IPV4()
    network_service = get_Network_Service()

    if network_service['netctl']:
        #### Write the settings for netctl (for images made before 2023/03/07)
        netctl_file = "/etc/netctl/wlan"

        wlan_settings = "Description=ethoscope_wifi network\nInterface=wlan0\nConnection=wireless\nSecurity=wpa\nESSID=%s\nKey=%s" % (ssid, wpakey)

        if useSTATIC:
            wlan_settings += "IP=static\nAddress=('%s/24')\nGateway='%s'" % (ip_address, gateway)
        else:
            wlan_settings += "IP=dhcp\nTimeoutDHCP=60"
            
        with open(netctl_file, 'w') as f:
            f.write(wlan_settings)
        logging.warning("Wrote new information to %s" % netctl_file)

    if network_service['systemd']:
        #### Write the settings for systemd-networkd (from images > 2023/03/07)
        wpasupplicant_file = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
        systemd_file = "/etc/systemd/network/25-wireless.network"

        wpa_cmd = "wpa_passphrase %s %s > %s" % (ssid, wpakey, wpasupplicant_file)
        with os.popen(wpa_cmd) as cmd:
            logging.info ( cmd.read() )

        wlan_settings_systemd = "[Match]\nName=wlan0\n\n[DHCPv4]\nRouteMetric=20\n"

        if useSTATIC:
            wlan_settings_systemd += "[Network]\nAddress=%s/24\nGateway=%s\nDHCP=no" % (ip_address, gateway)
        else:
            wlan_settings_systemd += "[Network]\nDHCP=yes"


        with open(systemd_file, 'w') as f:
            f.write(wlan_settings_systemd)
        logging.warning("Wrote new information to %s" % systemd_file)


def get_connection_status():
    ifs = {}
    for interface in netifaces.interfaces():
        addr = netifaces.ifaddresses(interface)
        ifs.update({interface : netifaces.AF_INET in addr})

    return ifs

    #return netifaces.AF_INET in addr    

def set_etc_hostname(ip_address, nodename = "node", path="/etc/hosts"):
    '''
    Updates the settings in /etc/hosts to match the given IP address
    '''
    
    try:
        with open(path, 'w') as f:
            f.write("127.0.0.1\tlocalhost\n")
            f.write("%s\t%s\n" % (ip_address, nodename))
        logging.warning("Wrote new information in file: %s" % path)
    except:
        raise 

def get_commit_version(commit):
    '''
    Returns a dictionary formatted like the following
    {'id': 'a82d746e370e15182d780d0f06fca03efddb07c9', 'date': '2024-03-21 08:44:11'}
    '''
    return {
            "id":str(commit),
            "date":datetime.datetime.utcfromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S')
                    }

def get_git_version():
    '''
    return the current git version
    '''

    wd = os.getcwd()

    while wd != "/":
        try:
            repo = git.Repo(wd)
            commit = repo.commit()
            return get_commit_version(commit)

        except git.InvalidGitRepositoryError:
            wd = os.path.dirname(wd)
    
    return {"id": "NOT_A_GIT", "date": "None", "dir": os.getcwd()}


def file_in_dir_r(file, dir):
    file_dir_path = os.path.dirname(file).rstrip("//")
    dir_path = dir.rstrip("//")
    if file_dir_path == dir_path:
        return True
    elif file_dir_path == "":
        return False
    else:
        return file_in_dir_r(file_dir_path, dir_path)

def cpu_serial():
    """
    on a rPI, return a unique identifier of the CPU
    """
    serial = ''
    
    if isMachinePI():
        with open('/proc/cpuinfo', 'r') as infile:
            cpuinfo = infile.read()
        # Match a line like 'Serial   : xxxxx'
        serial = re.search(r'^Serial\s+:\s+(\w+)$', cpuinfo,
                          flags=re.MULTILINE | re.IGNORECASE)
        
        serial = serial.group(1)
        
    return serial
        
        
def hasPiCamera():
    """
    return True if a piCamera is supported and detected

    In PI3 with libcamera support we can use vcgencmd which outputs something like this:
    'supported=1 detected=1, libcamera interfaces=1'
    'supported=1 detected=0, libcamera interfaces=1'

    With PI4, however, we need to use libcamera-hello which has the following output

    """
    if not isMachinePI():
        return False

    if isMachinePI(2) or isMachinePI(3):

        # older versions had vcgencmd coming from raspberrypi-firmware and located in /opt/vc/bin
        # in newer versions, the command comes from raspberrypi-utils and it's in /usr/bin
        # we try this for future compatibility even though we still have to use raspberrypi-firmware for now
        # we get it from https://alaa.ad24.cz/packages/r/raspberrypi-firmware/raspberrypi-firmware-20231019-1-armv7h.pkg.tar.xz
        vcgencmd_possible_locations = ['/opt/vc/bin/vcgencmd', '/usr/bin/vcgencmd']
        for loc in vcgencmd_possible_locations:
            if os.path.isfile(loc):
                vcgencmd = "%s get_camera" % loc
                break

        with os.popen(vcgencmd) as cmd:
            out_cmd = cmd.read().strip()
        out = dict(x.split('=') for x in out_cmd.split(',')[0].split(' '))
        
        # If libcamera interfaces are available but vcgencmd shows detected=0,
        # fall back to libcamera detection method
        if 'libcamera' in out_cmd and 'interfaces=1' in out_cmd and out["detected"] == "0":
            with os.popen("libcamera-hello --list-cameras") as cmd:
                libcam_out = cmd.read()
            match = re.search(r'\d+ : (\w+)', libcam_out)
            return bool(match)
        
        return out["detected"] == out["supported"] == "1"

    if isMachinePI(4):
        with os.popen("libcamera-hello --list-cameras") as cmd:
            out_cmd = cmd.read()
        match = re.search(r'\d+ : (\w+)', out_cmd)
        if match:
            return match.group(1)
        else:
            return False

        
def getPiCameraVersion():
    """
    If a PiCamera is connected, returns the model

    #PINoIR v1
    #{'IFD0.Model': 'RP_ov5647', 'IFD0.Make': 'RaspberryPi'}
    #PINoIR v2
    #{'IFD0.Model': 'RP_imx219', 'IFD0.Make': 'RaspberryPi'}
    
    """
    
    known_versions = {'RP_ov5647': 'PINoIR 1', 'RP_imx219': 'PINoIR 2'}
    
    picamera_info_file = '/etc/picamera-version'
    
    if hasPiCamera():

        try:
            with open(picamera_info_file, 'r') as infile:
                camera_info = eval(infile.read())
            
            camera_info['version'] = known_versions[ camera_info['IFD0.Model'] ]
            
        except:
            camera_info = "This is a new ethoscope. Run tracking once to detect the camera module"
            
        return camera_info
    else:
        
        return False

def isSuperscope():
    """
    The following lsusb device
    Bus 001 Device 003: ID 05a3:9230 ARC International Camera
    is the one we currently use for the SuperScope
    https://www.amazon.co.uk/gp/product/B07R7JXV35/ref=ppx_yo_dt_b_asin_title_o06_s00?ie=UTF8&psc=1
    
    Eventually we will include the new rPI camera too
    https://uk.farnell.com/raspberry-pi/rpi-hq-camera/rpi-high-quality-camera-12-3-mp/dp/3381605
    
    """
    
    pass
    
    
def isExperimental(new_value=None):
    """
    return true if the machine is to be used as experimental
    this mymics a non-PI or a PI without plugged in camera
    to activate, create an empty file called /etc/isexperimental
    """
    
    # If the ethoscope is running on something that is not a pi, it will be always flagged as experimental
    if new_value == None and not isMachinePI():
        return True
    
    filename = '/etc/isexperimental'
    current_value = os.path.exists(filename)
    
    if new_value == None:
        return current_value
        
    if new_value == True and current_value == False:
        #create file
        with open(filename, mode='w'):
            logging.warning("Created a new empty file in %s. The machine is now experimental." % filename)
    
    elif new_value == False and current_value == True:
        #delete file
        os.remove(filename)
        logging.warning("Removed file %s. The machine is not experimental." % filename)

def was_interrupted():
    return os.path.exists(PERSISTENT_STATE)

def get_container_id(short=True):
    """
    From https://stackoverflow.com/a/71823877
    """
    with open('/proc/self/mountinfo') as file:
        for line in file:
            line = line.strip()
            if '/docker/containers/' in line:
                container_id = line.split('/docker/containers/')[-1].split('/')[0]
                if not short:
                    return container_id
                else:
                    return container_id[:12]
    return None

def get_machine_id(path="/etc/machine-id"):
    """
    Reads the machine ID
    This file should be present on any linux installation because, when missing, it is automatically generated by the OS.
    However, it won't be present in a docker container so if the file is missing we fall back to assuming it's because
    we are running this as a virtuascope inside a container
    """
    try:
        if os.path.exists(path):
            with open(path,'r') as f:
                info = f.readline().rstrip()
            return info

        else:
            return "VIR%s" % get_container_id()
    except: 
        return "NO_ID_AVAILABLE"

def get_etc_hostnames():
    """
    Parses /etc/hosts file and returns all the hostnames in a dictionary.
    """
    with open('/etc/hosts', 'r') as f:
        hostlines = f.readlines()
        
    hostlines = [line.strip() for line in hostlines
                 if not line.startswith('#') and line.strip() != '']
    hosts = {}
    for line in hostlines:
        entries = line.split("#")[0].split()
        hosts [ entries[1] ] = entries[0]

    return hosts
    
def get_core_temperature():
    """
    Returns the internal core temperature in degrees celsius
    """
    # older versions had vcgencmd coming from raspberrypi-firmware and located in /opt/vc/bin
    # in newer versions, the command comes from raspberrypi-utils and it's in /usr/bin
    # we try this for future compatibility even though we still have to use raspberrypi-firmware for now
    # we get it from https://alaa.ad24.cz/packages/r/raspberrypi-firmware/raspberrypi-firmware-20231019-1-armv7h.pkg.tar.xz

    vcgencmd_possible_locations = ['/opt/vc/bin/vcgencmd', '/usr/bin/vcgencmd']
    for loc in vcgencmd_possible_locations:
        if os.path.isfile(loc):
            vcgencmd = "%s measure_temp" % loc
            break

    if isMachinePI():
        try:
            with os.popen(vcgencmd) as df:
                temp = float("".join(filter(lambda d: str.isdigit(d) or d == '.', df.read())))
            return temp
        except:
            return 0
    else: 
        return 0

def underPowered():
    '''
    Return true if the PI is underpowered, false otherwise
    Code from rpi-bad-power https://github.com/shenxn/rpi-bad-power
    '''
    under_voltage = powerChecker()
    if under_voltage is None:
        return None
    else:
        return under_voltage.get()

    

def get_SD_CARD_AGE():
    """
    Given the machine_id file is created at the first boot, it assumes the SD card is as old as the file itself
    :return: timestamp of the card
    """
    try:
        return time.time() - os.path.getmtime("/etc/machine-id")
        
    except:
        return

def get_SD_CARD_NAME():
    """
    On recent (07/2020 on) versions of the SD images we save a file called
    /etc/sdimagename
    that contains the name of the img file we burnt to create the ethoscope
    """
    fn = "/etc/sdimagename"
    try:
        with open(fn) as f:
            name = f.read()
        return name.rstrip()

    except:
        return "N/A"
        

def get_partition_info(folder=''):
    """
    Returns information about the mounted partitions. If a folder is specified,
    returns information about the mounted partition containing that folder
    and its free available space.
    """
    try:
        command = f'df -Th {folder}'.strip()
        with os.popen(command) as df:
            df_info = df.read().strip().split('\n')
        
        if len(df_info) < 2:
            raise ValueError(f"No partition information found for folder: {folder}")

        keys = df_info[0].split()
        values = df_info[1:]
        
        # For a specified folder, return a dictionary; otherwise, return a list of dictionaries
        if folder:
            return dict(zip(keys, values[0].split()))
        else:
            return [dict(zip(keys, line.split())) for line in values]
        
    except Exception as e:
        print(f"Error: {e}")
        return

def set_datetime(time_on_node):
    """
    Set date and time on the PI
    time_on_node is the time to be set in the datetime format
    """
    
    cmd = 'date -s "%s"' % time_on_node.strftime("%d %b %Y %H:%M:%S") # 26 Jun 2020 15:04:25
    
    try:
        with os.popen(cmd, 'r') as c:
            c.read()
        
        return True
        
    except:
        return False
        
        
def SQL_dump( database_name = None, credentials = {'username' : 'ethoscope', 'password' : 'ethoscope'}, output_dir = "/ethoscope_data/backup", outputfile=None ):
    """
    Creates a SQL dump of the specified database
    """
    
    if database_name == None:
        database_name = get_machine_name() + "_db"
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    if outputfile is None:
        formatted_time = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        outputfile = "%s_%s.sql" % (database_name, formatted_time)
    
    fullpath = os.path.join(output_dir, outputfile)
   
    cmd = "mysqldump -alv --compatible=ansi --skip-extended-insert --compact --user=%s --password=%s %s > %s" % (credentials['username'], credentials['password'], database_name, fullpath)

    try:
        # Exporting the database can take some time 
        # I am not really sure if there is a way to get a real time feedback of the process
        with os.popen(cmd, 'r') as c:
            verbose = c.read()

        return True

    except:
        return False

def loggingStatus( status = None ):
    """
    Set or read the current logging status
    """
    if status == None:
        try:
            with os.popen('systemctl is-active systemd-journal-upload.service') as df:
                status = df.read().split("\n")[2] 
            if status.startswith('active'): return True
            else: return False
        except: 
            return -1

    elif status == True and not loggingStatus():
        try:
            logging.info('User requested to start remote Logging.')
            
            with open('/etc/systemd/journal-upload.conf', mode='w') as cf:
                cf.write ("[Upload]\nURL=http://node:19532\n")
            logging.info('Modified journal-upload.conf to point to the node')

            with os.popen("sleep 1 && systemctl enable --now systemd-journal-upload.service && sleep 2") as po:
                r = po.read()
            
            return loggingStatus()
        except:
            return -1

    elif status == False and loggingStatus():
        try:
            with os.popen("sleep 1 && systemctl disable --now systemd-journal-upload.service && sleep 2") as po:
                r = po.read()
            return loggingStatus()
        except:
            return -1


def check_disk_space(ethoscope_dir, threshold_percent=85):
    """
    Check disk space usage for the partition containing ethoscope_dir.
    
    Args:
        ethoscope_dir (str): Path to ethoscope data directory
        threshold_percent (int): Threshold percentage for cleanup trigger
        
    Returns:
        dict: {'usage_percent': float, 'available_gb': float, 'needs_cleanup': bool}
    """
    try:
        partition_info = get_partition_info(ethoscope_dir)
        if not partition_info:
            return {'usage_percent': 0, 'available_gb': 0, 'needs_cleanup': False, 'error': 'Cannot get partition info'}
        
        # Extract usage percentage (format: "85%" -> 85)
        usage_str = partition_info.get('Use%', '0%')
        usage_percent = float(usage_str.rstrip('%'))
        
        # Extract available space (format: "1.2G" -> 1.2)
        available_str = partition_info.get('Avail', '0')
        available_gb = 0
        if available_str.endswith('G'):
            available_gb = float(available_str[:-1])
        elif available_str.endswith('M'):
            available_gb = float(available_str[:-1]) / 1024
        elif available_str.endswith('K'):
            available_gb = float(available_str[:-1]) / (1024 * 1024)
        
        needs_cleanup = usage_percent >= threshold_percent
        
        return {
            'usage_percent': usage_percent,
            'available_gb': available_gb,
            'needs_cleanup': needs_cleanup
        }
        
    except Exception as e:
        logging.error(f"Error checking disk space: {e}")
        return {'usage_percent': 0, 'available_gb': 0, 'needs_cleanup': False, 'error': str(e)}


def cleanup_old_data(ethoscope_dir, max_age_days=60, dry_run=False):
    """
    Clean up old data files from videos and tracking directories.
    
    Args:
        ethoscope_dir (str): Path to ethoscope data directory
        max_age_days (int): Delete files older than this many days
        dry_run (bool): If True, only simulate cleanup without deleting
        
    Returns:
        dict: Summary of cleanup actions
    """
    import glob
    
    cleanup_summary = {
        'files_deleted': 0,
        'space_freed_mb': 0,
        'errors': [],
        'deleted_files': []
    }
    
    try:
        # Define data directories to clean
        data_dirs = [
            os.path.join(ethoscope_dir, 'videos'),
            os.path.join(ethoscope_dir, 'tracking')
        ]
        
        # Calculate cutoff time (files older than this will be deleted)
        cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
        
        # Collect all files with their modification times
        files_to_check = []
        for data_dir in data_dirs:
            if os.path.exists(data_dir):
                # Look for common ethoscope file patterns
                patterns = ['*.db', '*.h264', '*.mp4', '*.avi', '*.sql', '*.log']
                for pattern in patterns:
                    for file_path in glob.glob(os.path.join(data_dir, '**', pattern), recursive=True):
                        try:
                            mtime = os.path.getmtime(file_path)
                            file_size = os.path.getsize(file_path)
                            files_to_check.append((file_path, mtime, file_size))
                        except OSError as e:
                            cleanup_summary['errors'].append(f"Cannot access {file_path}: {e}")
        
        # Sort files by modification time (oldest first)
        files_to_check.sort(key=lambda x: x[1])
        
        # Delete old files
        for file_path, mtime, file_size in files_to_check:
            if mtime < cutoff_time:
                try:
                    if not dry_run:
                        os.remove(file_path)
                        logging.info(f"Deleted old file: {file_path}")
                    else:
                        logging.info(f"Would delete: {file_path}")
                    
                    cleanup_summary['files_deleted'] += 1
                    cleanup_summary['space_freed_mb'] += file_size / (1024 * 1024)
                    cleanup_summary['deleted_files'].append(file_path)
                    
                except OSError as e:
                    cleanup_summary['errors'].append(f"Cannot delete {file_path}: {e}")
                    logging.error(f"Failed to delete {file_path}: {e}")
        
        action = "Would delete" if dry_run else "Deleted"
        logging.info(f"{action} {cleanup_summary['files_deleted']} old files, "
                    f"freed {cleanup_summary['space_freed_mb']:.2f} MB")
        
    except Exception as e:
        error_msg = f"Error during cleanup: {e}"
        cleanup_summary['errors'].append(error_msg)
        logging.error(error_msg)
    
    return cleanup_summary


def manage_disk_space(ethoscope_dir, threshold_percent=85, max_age_days=60):
    """
    Manage disk space by checking usage and cleaning up old files if needed.
    
    Args:
        ethoscope_dir (str): Path to ethoscope data directory  
        threshold_percent (int): Disk usage percentage that triggers cleanup
        max_age_days (int): Delete files older than this many days
        
    Returns:
        dict: Summary of space management actions
    """
    try:
        # Check current disk space
        space_info = check_disk_space(ethoscope_dir, threshold_percent)
        
        if 'error' in space_info:
            logging.warning(f"Disk space check failed: {space_info['error']}")
            return {'status': 'error', 'details': space_info}
        
        result = {
            'status': 'checked',
            'usage_percent': space_info['usage_percent'],
            'available_gb': space_info['available_gb'],
            'cleanup_performed': False
        }
        
        if space_info['needs_cleanup']:
            logging.warning(f"Disk usage at {space_info['usage_percent']:.1f}%, "
                          f"triggering cleanup of files older than {max_age_days} days")
            
            # Perform cleanup
            cleanup_result = cleanup_old_data(ethoscope_dir, max_age_days, dry_run=False)
            result['cleanup_performed'] = True
            result['cleanup_summary'] = cleanup_result
            
            # Check space again after cleanup
            new_space_info = check_disk_space(ethoscope_dir, threshold_percent)
            if 'error' not in new_space_info:
                result['usage_after_cleanup'] = new_space_info['usage_percent']
                result['available_after_cleanup'] = new_space_info['available_gb']
                
                if cleanup_result['files_deleted'] > 0:
                    logging.info(f"Cleanup completed: freed {cleanup_result['space_freed_mb']:.2f} MB, "
                               f"disk usage now {new_space_info['usage_percent']:.1f}%")
                else:
                    logging.warning("No files were eligible for cleanup")
        else:
            logging.debug(f"Disk usage at {space_info['usage_percent']:.1f}%, no cleanup needed")
        
        return result
        
    except Exception as e:
        error_msg = f"Error in disk space management: {e}"
        logging.error(error_msg)
        return {'status': 'error', 'details': error_msg}