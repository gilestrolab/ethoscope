import datetime
import glob
import logging
import os
import re
import shutil
import subprocess
import time
from uuid import uuid4

import git
import netifaces

from ethoscope.utils.rpi_bad_power import powerChecker

PERSISTENT_STATE = "/var/cache/ethoscope/persistent_state.pkl"

# Where the detected camera model is cached. Defined here, and imported by the
# camera code that writes it, because the two used to disagree: the writer used
# /etc/picamera-version while the reader looked in /etc/ethoscope/, so the cache
# was never read and detection always fell through to probing the filesystem.
PICAMERA_VERSION_FILE = "/etc/ethoscope/picamera-version"

# Analogue gain applied when no gain file is present.
#
# Measured on a Pi 3 / imx219 bench (issue #222): image noise is linear in gain,
# frame_noise = 0.523 + 0.0824 x gain (R^2 = 0.965, n = 22), and is independent
# of frame rate and of illumination - so gain is the only lever for image noise
# and every step costs about 0.08 grey levels.
#
# The floor is set by detection rather than by noise: at gain 1 the image is dim
# enough that ROI target detection failed outright in one run, and it gave the
# only unstable noise readings in the matrix. Gains 2-3 detected in every
# condition tested, so 3 takes the lowest noise that still leaves margin - about
# 18 % below the 5.0 most cards were shipped with.
DEFAULT_CAMERA_GAIN = 3.0

# Tracking frame-rate cap applied when no maxfps file is present.
#
# It is a CPU throttle, not an exposure control - since the exposure ceiling was
# decoupled from it, image noise is independent of frame rate (#222). What it
# does still determine is `dt`, and the movement statistic used for sleep scoring
# is a per-frame displacement divided by `dt`, so runs at different caps are not
# directly comparable. 5 matches what deployed cards were shipped with and is at
# the limit of what a Pi 3 achieves in practice.
DEFAULT_MAXFPS = 5


def ensure_dir_exists(file_path):
    """
    Ensures that the directory for the given file path exists.

    Args:
        file_path (str): Full path to a file whose directory should be created
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)


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
        with open("/sys/firmware/devicetree/base/model") as file:
            model_info = file.read().strip()

        match = re.search(r"Raspberry Pi (\d+)([A-Za-z ]+)", model_info)
        if match:
            model_number = int(match.group(1))
            model_type = match.group(2).strip()
        else:
            model_number = None
            model_type = None

        # Return the information as a dictionary
        return {"model_number": model_number, "model_type": model_type}

    except Exception:
        return {"model_number": 0, "model_type": None}
        # return {'error': str(e)}


def isMachinePI(version=None):
    """
    Return True if we are running on a Pi - proper ethoscope
    """
    pi_ver = pi_version()["model_number"]

    if not version:
        return pi_ver > 0
    else:
        return pi_ver == int(version)


def get_machine_name(path="/etc/machine-name"):
    """
    Reads the machine name
    This file will be present only on a real ethoscope
    When running locally, it will generate a randome name
    """

    if os.path.exists(path):
        with open(path) as f:
            info = f.readline().rstrip()
        return info

    else:
        return "VIRTUA_" + get_machine_id()[:3]


def set_machine_name(id, path="/etc/machine-name"):
    """
    Takes an id and updates the machine name accordingly in the format
    ETHOSCOPE_id; changes the hostname too.

    The hostname omits the underscore (e.g. ETHOSCOPE010).
    On Raspberry Pi OS with cloud-init, we must also disable cloud-init's
    hostname management and update /boot/firmware/user-data to prevent
    reversion on reboot.

    :param id: integer
    """

    machine_name = f"ETHOSCOPE_{id:03d}"
    hostname = f"ETHOSCOPE{id:03d}"
    try:
        # Write internal machine name (with underscore)
        ensure_dir_exists(path)
        with open(path, "w") as f:
            f.write(machine_name)
        logging.warning(f"Wrote new information in file: {path}")

        # Use raspi-config to set hostname (updates /etc/hostname, /etc/hosts, and running hostname)
        subprocess.run(
            ["raspi-config", "nonint", "do_hostname", hostname],
            check=True,
            capture_output=True,
        )
        logging.warning(f"Changed the machine hostname to: {hostname}")

        # Prevent cloud-init from reverting hostname on reboot
        _disable_cloud_init_hostname()

        # Update cloud-init user-data so it stays consistent
        _update_cloud_init_hostname(hostname)

    except Exception:
        raise


def _disable_cloud_init_hostname(cloud_cfg="/etc/cloud/cloud.cfg"):
    """
    Sets preserve_hostname to true and manage_etc_hosts to false in cloud.cfg
    so cloud-init stops overriding the hostname and /etc/hosts on every boot.
    """
    try:
        with open(cloud_cfg) as f:
            content = f.read()

        modified = False

        if "preserve_hostname: false" in content:
            content = content.replace(
                "preserve_hostname: false", "preserve_hostname: true"
            )
            modified = True

        if "manage_etc_hosts: true" in content:
            content = content.replace(
                "manage_etc_hosts: true", "manage_etc_hosts: false"
            )
            modified = True

        if modified:
            with open(cloud_cfg, "w") as f:
                f.write(content)
            logging.warning(
                "Updated cloud.cfg: preserve_hostname=true, manage_etc_hosts=false"
            )
    except FileNotFoundError:
        pass  # Not a cloud-init system
    except Exception as e:
        logging.error(f"Failed to update cloud.cfg: {e}")


def _update_cloud_init_hostname(hostname, user_data="/boot/firmware/user-data"):
    """
    Updates the hostname line in cloud-init's user-data file
    so it stays consistent with the actual hostname.
    """
    try:
        with open(user_data) as f:
            content = f.read()
        new_content = re.sub(
            r"^hostname:.*$", f"hostname: {hostname}", content, flags=re.MULTILINE
        )
        if new_content != content:
            with open(user_data, "w") as f:
                f.write(new_content)
            logging.warning(f"Updated hostname in {user_data}")
    except FileNotFoundError:
        pass  # No user-data file
    except Exception as e:
        logging.error(f"Failed to update {user_data}: {e}")


def _update_cloud_init_hosts_template(
    ip_address, nodename, template="/etc/cloud/templates/hosts.debian.tmpl"
):
    """
    Adds the node entry to the cloud-init hosts template so it persists
    even if cloud-init regenerates /etc/hosts.
    """
    try:
        with open(template) as f:
            content = f.read()

        # Check if nodename already has an entry and update it
        new_content = re.sub(
            rf"^.*\t{re.escape(nodename)}\s*$",
            f"{ip_address}\t{nodename}",
            content,
            flags=re.MULTILINE,
        )

        if new_content == content:
            # No existing entry found, append it
            if not content.endswith("\n"):
                content += "\n"
            new_content = content + f"{ip_address}\t{nodename}\n"

        if new_content != content:
            with open(template, "w") as f:
                f.write(new_content)
            logging.warning(
                f"Updated cloud-init hosts template with {nodename} -> {ip_address}"
            )
    except FileNotFoundError:
        pass  # Not a cloud-init system
    except Exception as e:
        logging.error(f"Failed to update cloud-init hosts template: {e}")


def set_machine_id(id, path="/etc/machine-id"):
    """
    Takes an id and updates the machine id accordingly in the format
    0ID-UUID to make a 32 bytes string

    :param id: integer
    """

    new_uuid = f"{id:03d}" + uuid4().hex[3:]

    try:
        with open(path, "w") as f:
            f.write(new_uuid)
        logging.warning(f"Wrote new information in file: {path}")

    except Exception:
        raise


def get_Network_Service():
    """
    Detects wether we are using systemd-networkd or netctl
    """
    daemon = {"netctl": False, "systemd": False}

    with os.popen("systemctl is-active netctl@wlan.service") as df:
        status = df.read()
    if status.startswith("active"):
        daemon["netctl"] = True

    with os.popen("systemctl is-active systemd-networkd.service") as df:
        status = df.read()
    if status.startswith("active"):
        daemon["systemd"] = True

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

    if network_service["netctl"]:
        netctl_file = "/etc/netctl/wlan"
        with open(netctl_file) as f:
            wlan_settings = f.readlines()

        for line in wlan_settings:
            if "=" in line:
                data[line.strip().split("=")[0]] = line.strip().split("=")[1]

        data["netctl"] = True

    if network_service["systemd"]:
        wpasupplicant_file = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
        systemd_file = "/etc/systemd/network/25-wireless.network"

        with open(wpasupplicant_file) as f:
            wlan_settings = f.readlines()

        for line in wlan_settings:
            if "=" in line:
                data[line.strip().split("=")[0]] = (
                    line.strip().split("=")[1].replace('"', "")
                )

        data["systemd"] = True
        data["ESSID"] = data["ssid"]
        data["Key"] = data["#psk"]

        with os.popen(
            "/sbin/ip -o -4 addr list eth0 | awk '{print $4}' | cut -d/ -f1"
        ) as cmd:
            data["IP"] = cmd.read().strip()

        with os.popen("ip route | grep default | head -n 1 | cut -d ' ' -f 3") as cmd:
            data["Gateway"] = cmd.read().strip()

        with open(systemd_file) as f:
            net_settings = f.readlines()

        for line in net_settings:
            if "=" in line:
                data[line.strip().split("=")[0]] = line.strip().split("=")[1]

    return data


def get_static_IPV4():
    """ """

    with os.popen("ip route | grep default | head -n 1 | cut -d ' ' -f 3") as cmd:
        gateway = cmd.read().strip()

    a, b, c, _ = gateway.split(".")
    d = int(get_machine_name().split("_")[-1])

    if int(d) > 1 and int(d) < 255:
        ip_address = ".".join([a, b, c, str(d)])
    else:  # out of range
        ip_address = None

    return ip_address, gateway


def set_WIFI(ssid="ETHOSCOPE_WIFI", wpakey="ETHOSCOPE_1234", useSTATIC=False):
    """
    Receives the setting for wifi connection
    Uses dhcp by default but if USE_DHCP is set to False, it will adopt a static ip address instead
    """

    ip_address, gateway = get_static_IPV4()
    network_service = get_Network_Service()

    if network_service["netctl"]:
        # Write the settings for netctl (for images made before 2023/03/07)
        netctl_file = "/etc/netctl/wlan"

        wlan_settings = f"Description=ethoscope_wifi network\nInterface=wlan0\nConnection=wireless\nSecurity=wpa\nESSID={ssid}\nKey={wpakey}"

        if useSTATIC:
            wlan_settings += (
                f"IP=static\nAddress=('{ip_address}/24')\nGateway='{gateway}'"
            )
        else:
            wlan_settings += "IP=dhcp\nTimeoutDHCP=60"

        with open(netctl_file, "w") as f:
            f.write(wlan_settings)
        logging.warning(f"Wrote new information to {netctl_file}")

    if network_service["systemd"]:
        # Write the settings for systemd-networkd (from images > 2023/03/07)
        wpasupplicant_file = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
        systemd_file = "/etc/systemd/network/25-wireless.network"

        wpa_cmd = f"wpa_passphrase {ssid} {wpakey} > {wpasupplicant_file}"
        with os.popen(wpa_cmd) as cmd:
            logging.info(cmd.read())

        wlan_settings_systemd = "[Match]\nName=wlan0\n\n[DHCPv4]\nRouteMetric=20\n"

        if useSTATIC:
            wlan_settings_systemd += (
                f"[Network]\nAddress={ip_address}/24\nGateway={gateway}\nDHCP=no"
            )
        else:
            wlan_settings_systemd += "[Network]\nDHCP=yes"

        with open(systemd_file, "w") as f:
            f.write(wlan_settings_systemd)
        logging.warning(f"Wrote new information to {systemd_file}")


def get_connection_status():
    ifs = {}
    for interface in netifaces.interfaces():
        addr = netifaces.ifaddresses(interface)
        ifs.update({interface: netifaces.AF_INET in addr})

    return ifs

    # return netifaces.AF_INET in addr


def set_etc_hostname(ip_address, nodename="node", path="/etc/hosts"):
    """
    Updates or adds the node entry in /etc/hosts to match the given IP address.
    Preserves all other existing entries (localhost, ethoscope hostname, IPv6, etc.)
    Also disables cloud-init's manage_etc_hosts to prevent it from overwriting
    /etc/hosts on reboot.
    """

    try:
        # Prevent cloud-init from regenerating /etc/hosts on reboot
        _disable_cloud_init_hostname()

        # Read existing content
        try:
            with open(path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = ["127.0.0.1\tlocalhost\n"]

        # Update or add the node entry
        new_lines = []
        node_found = False
        for line in lines:
            stripped = line.strip()
            # Skip empty lines and comments
            if stripped == "" or stripped.startswith("#"):
                new_lines.append(line)
                continue
            # Check if this line maps to our nodename
            parts = stripped.split()
            if len(parts) >= 2 and nodename in parts[1:]:
                new_lines.append(f"{ip_address}\t{nodename}\n")
                node_found = True
            else:
                new_lines.append(line)

        if not node_found:
            new_lines.append(f"{ip_address}\t{nodename}\n")

        with open(path, "w") as f:
            f.writelines(new_lines)
        logging.warning(f"Updated {nodename} -> {ip_address} in {path}")

        # Also update cloud-init template so the entry survives if cloud-init
        # regenerates /etc/hosts despite our manage_etc_hosts=false setting
        _update_cloud_init_hosts_template(ip_address, nodename)

    except Exception:
        raise


def get_commit_version(commit):
    """
    Returns a dictionary formatted like the following
    {'id': 'a82d746e370e15182d780d0f06fca03efddb07c9', 'date': '2024-03-21 08:44:11'}
    """
    return {
        "id": str(commit),
        "date": datetime.datetime.utcfromtimestamp(commit.committed_date).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


def get_git_version():
    """
    return the current git version
    """

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
    file_dir_path = os.path.dirname(file).rstrip("/")
    dir_path = dir.rstrip("/")
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
    serial = ""

    if isMachinePI():
        with open("/proc/cpuinfo") as infile:
            cpuinfo = infile.read()
        # Match a line like 'Serial   : xxxxx'
        serial = re.search(
            r"^Serial\s+:\s+(\w+)$", cpuinfo, flags=re.MULTILINE | re.IGNORECASE
        )

        serial = serial.group(1)

    return serial


def _camera_cli():
    """
    Name of the libcamera "list the cameras" tool, or None when absent.

    Raspberry Pi OS renamed the ``libcamera-*`` tools to ``rpicam-*`` in
    Bookworm and dropped the old names entirely in Trixie, where only
    ``rpicam-hello`` exists. The name used to be hardcoded to
    ``libcamera-hello``, and because it was shelled out through ``os.popen()``
    the breakage was invisible: the shell wrote "command not found" to stderr,
    ``read()`` returned an empty string, the regex matched nothing, and the
    caller concluded there was no camera. Look the binary up instead.

    Returns:
        str: The executable name to call, or None if neither is installed.
    """
    for name in ("rpicam-hello", "libcamera-hello"):
        if shutil.which(name):
            return name

    logging.debug("Neither rpicam-hello nor libcamera-hello is installed")
    return None


def _detect_camera_via_libcamera_cli(timeout_s=2):
    """
    Ask the libcamera CLI which sensor is attached.

    The slowest probe of the set - it starts the camera stack - so it is used
    only as a fallback, after the filesystem checks.

    Args:
        timeout_s (int): Seconds to allow the tool before giving up.

    Returns:
        str: The sensor name (e.g. "imx219"), or None if it could not be read.
    """
    cli = _camera_cli()
    if cli is None:
        return None

    try:
        with os.popen(
            f"timeout {timeout_s} {cli} --list-cameras --timeout 1000"
        ) as cmd:
            out_cmd = cmd.read()
    except Exception as e:
        logging.debug(f"Could not run {cli}: {e}")
        return None

    match = re.search(r"\d+ : (\w+)", out_cmd)
    return match.group(1) if match else None


def _detect_camera_via_i2c():
    """
    Detect the camera from the sensor driver's I2C binding.

    This is the primary method on any image where libcamera drives the camera:
    ``camera_auto_detect=1`` loads the sensor overlay, which binds the driver
    and publishes the sensor name under /sys/bus/i2c. That is now every Pi
    model, not just Pi 4 - see hasPiCamera().

    Returns:
        str: The sensor name if found, None otherwise.
    """
    known_sensors = ["imx219", "ov5647", "imx477", "imx708"]

    try:
        i2c_devices = glob.glob("/sys/bus/i2c/devices/*/name")
        for device_path in i2c_devices:
            with open(device_path) as f:
                sensor_name = f.read().strip()
                if sensor_name in known_sensors:
                    return sensor_name
    except Exception:
        pass
    return None


def _detect_camera_via_v4l2_subdev():
    """
    Detect camera via V4L2 subdevices (Pi 4+ method).
    Returns True if camera subdevice found, False otherwise.
    """
    v4l2_subdevs = glob.glob("/dev/v4l-subdev*")
    return len(v4l2_subdevs) > 0


def _detect_camera_via_bcm2835_platform():
    """
    Detect camera via bcm2835-camera platform device (Pi 2/3 method).
    Returns True if bcm2835-camera device found, False otherwise.
    """
    # Primary path for Pi 3
    bcm2835_paths = [
        "/sys/devices/platform/soc/3f00b840.mailbox/bcm2835-camera",
        "/sys/devices/platform/soc/*/mailbox/bcm2835-camera",  # Alternative patterns
    ]

    for path_pattern in bcm2835_paths:
        if "*" in path_pattern:
            matches = glob.glob(path_pattern)
            if matches:
                return True
        else:
            if os.path.exists(path_pattern):
                return True
    return False


def _legacy_camera_detection():
    """
    Ask the GPU firmware whether it can see a camera.

    Only ever answers on a legacy (MMAL) image: under KMS ``vcgencmd
    get_camera`` reports detected=0 even when the camera works perfectly, so a
    negative here means nothing on its own.

    The model gate this used to carry has gone with the one in hasPiCamera():
    it sent Pi 4 down a libcamera branch that now lives in
    _detect_camera_via_libcamera_cli(), and it is the caller's job to decide
    which probes to run.

    Returns:
        bool: True only if the firmware reports a supported, detected camera.
    """
    try:
        vcgencmd_possible_locations = ["/opt/vc/bin/vcgencmd", "/usr/bin/vcgencmd"]

        for loc in vcgencmd_possible_locations:
            if os.path.isfile(loc):
                with os.popen(f"{loc} get_camera") as cmd:
                    out_cmd = cmd.read().strip()
                return "detected=1" in out_cmd and "supported=1" in out_cmd

    except Exception as e:
        logging.debug(f"vcgencmd camera probe failed: {e}")

    return False


def hasPiCamera():
    """
    Detect Pi camera using filesystem checks to avoid conflicts with active camera usage.

    This function uses non-intrusive methods to detect camera hardware without trying
    to access the camera directly, preventing false negatives when the camera is
    actively being used for tracking, recording, or streaming.

    Returns:
        bool: True if camera hardware is detected, False otherwise
    """
    if not isMachinePI():
        return False

    # Reason: the probes used to be chosen by Pi model, on the assumption that
    # Pi 2/3 ran the legacy MMAL firmware camera and Pi 4 ran libcamera. That
    # stopped being true when one image began booting every model on KMS +
    # camera_auto_detect: a Pi 3 on that image has no bcm2835-camera device and
    # vcgencmd reports detected=0, so a model-keyed check calls a perfectly good
    # camera missing - and the whole fleet is Pi 3. Any model outside 2/3/4 (a
    # Pi 5) fell off the end and returned False unconditionally.
    #
    # Which probe answers depends on the camera *stack*, not on the board, so
    # run them all and let the first positive win. Ordered cheapest and most
    # specific first; the CLI one starts the camera stack, so it goes last.
    # A false negative here is far worse than a false positive: it reports
    # "No camera hardware detected - video capabilities disabled" for a device
    # that is tracking happily, and stamps that into every run's METADATA.
    probes = (
        ("I2C sensor binding", lambda: bool(_detect_camera_via_i2c())),
        ("V4L2 subdevice", _detect_camera_via_v4l2_subdev),
        ("bcm2835 platform device", _detect_camera_via_bcm2835_platform),
        ("GPU firmware (vcgencmd)", _legacy_camera_detection),
        ("libcamera CLI", lambda: bool(_detect_camera_via_libcamera_cli(timeout_s=3))),
    )

    for name, probe in probes:
        try:
            if probe():
                logging.debug(f"Camera detected via {name}")
                return True
        except Exception as e:
            # A probe that cannot run is not evidence of absence.
            logging.debug(f"Camera probe '{name}' could not run: {e}")

    logging.warning(
        "No camera detected by any probe (I2C, V4L2, bcm2835, vcgencmd, "
        "libcamera CLI). Video capabilities will be reported as unavailable."
    )
    return False


def _get_camera_sensor_info():
    """
    Name the attached camera sensor.

    Returns:
        str: The sensor name (e.g. "imx219"), or None when it cannot be
            determined - which callers must treat as a degraded state, since
            the NoIR tuning file is chosen from this name and a run without it
            is not comparable with a correctly tuned one (issue #222).
    """
    sensor_name = _detect_camera_via_i2c()
    if sensor_name:
        return sensor_name

    # Reason: the fallback was gated on isMachinePI(4), which is an equality
    # test, so it never ran on a Pi 3 or a Pi 5. That was harmless while Pi 3
    # was on the legacy camera stack; now that one image puts every model on
    # libcamera, it left the fleet with a single detection method and no
    # backup at all. Nothing about reading the sensor name is Pi 4 specific.
    sensor_name = _detect_camera_via_libcamera_cli()
    if sensor_name:
        return sensor_name

    logging.warning(
        "Could not determine the camera sensor from either the I2C binding or "
        "the libcamera CLI; the NoIR tuning file cannot be resolved without it."
    )
    return None


def getPiCameraVersion():
    """
    Returns camera information if a PiCamera is connected.

    Returns:
        dict or str: Camera information dictionary with version details,
                    or descriptive string about camera status.

    Examples:
        Pi with camera: {'IFD0.Model': 'RP_imx219', 'IFD0.Make': 'RaspberryPi', 'version': 'PINoIR 2', 'sensor': 'imx219'}
        New ethoscope: "This is a new ethoscope. Run tracking once to detect the camera module"
        No camera: "No camera hardware detected - video capabilities disabled"
    """

    known_versions = {
        "RP_ov5647": "PINoIR 1",
        "RP_imx219": "PINoIR 2",
        "RP_imx477": "HQ Camera",
        "RP_imx708": "Camera Module 3",
    }

    # Map sensor names to known Pi camera versions
    sensor_to_version = {
        "ov5647": "PINoIR 1",
        "imx219": "PINoIR 2",
        "imx477": "HQ Camera",
        "imx708": "Camera Module 3",
    }

    picamera_info_file = PICAMERA_VERSION_FILE

    if hasPiCamera():
        try:
            # Try to read cached camera info file
            with open(picamera_info_file) as infile:
                camera_info = eval(infile.read())

            if (
                "IFD0.Model" in camera_info
                and camera_info["IFD0.Model"] in known_versions
            ):
                camera_info["version"] = known_versions[camera_info["IFD0.Model"]]

            # Add detected sensor information if available
            sensor_name = _get_camera_sensor_info()
            if sensor_name:
                camera_info["sensor"] = sensor_name
                if "version" not in camera_info and sensor_name in sensor_to_version:
                    camera_info["version"] = sensor_to_version[sensor_name]

            return camera_info

        except Exception:
            # Fallback: try to provide sensor info even without cache file
            sensor_name = _get_camera_sensor_info()
            if sensor_name and sensor_name in sensor_to_version:
                return {
                    "sensor": sensor_name,
                    "version": sensor_to_version[sensor_name],
                    "detected_via": "filesystem",
                }

            return (
                "This is a new ethoscope. Run tracking once to detect the camera module"
            )

    else:
        return "No camera hardware detected - video capabilities disabled"


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
    to activate, create an empty file called /etc/ethoscope/isexperimental
    """

    # If the ethoscope is running on something that is not a pi, it will be always flagged as experimental
    if new_value is None and not isMachinePI():
        return True

    filename = "/etc/ethoscope/isexperimental"
    current_value = os.path.exists(filename)

    if new_value is None:
        return current_value

    if new_value is True and current_value is False:
        # create file
        ensure_dir_exists(filename)
        with open(filename, mode="w"):
            logging.warning(
                f"Created a new empty file in {filename}. The machine is now experimental."
            )

    elif new_value is False and current_value is True:
        # delete file
        os.remove(filename)
        logging.warning(f"Removed file {filename}. The machine is not experimental.")


def has_light_hardware(new_value=None):
    """
    Get or set whether this ethoscope has LED light hardware connected.

    When set to True, enables and starts ethoscope_light.service.
    When set to False, stops and disables the service.

    Args:
        new_value: None to query, True/False to set.

    Returns:
        bool: Whether the light service is currently enabled.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-enabled", "--quiet", "ethoscope_light.service"],
            capture_output=True,
            timeout=5,
        )
        current_value = result.returncode == 0
    except Exception:
        current_value = False

    if new_value is None:
        return current_value

    if new_value and not current_value:
        subprocess.run(
            ["systemctl", "enable", "--now", "ethoscope_light.service"],
            capture_output=True,
            timeout=10,
        )
        logging.info("Enabled ethoscope_light.service")

    elif not new_value and current_value:
        subprocess.run(
            ["systemctl", "disable", "--now", "ethoscope_light.service"],
            capture_output=True,
            timeout=10,
        )
        logging.info("Disabled ethoscope_light.service")


def was_interrupted():
    return os.path.exists(PERSISTENT_STATE)


def get_container_id(short=True):
    """
    From https://stackoverflow.com/a/71823877
    """
    with open("/proc/self/mountinfo") as file:
        for line in file:
            line = line.strip()
            if "/docker/containers/" in line:
                container_id = line.split("/docker/containers/")[-1].split("/")[0]
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
            with open(path) as f:
                info = f.readline().rstrip()
            return info

        else:
            return f"VIR{get_container_id()}"
    except Exception:
        return "NO_ID_AVAILABLE"


def get_etc_hostnames():
    """
    Parses /etc/hosts file and returns all the hostnames in a dictionary.
    """
    with open("/etc/hosts") as f:
        hostlines = f.readlines()

    hostlines = [
        line.strip()
        for line in hostlines
        if not line.startswith("#") and line.strip() != ""
    ]
    hosts = {}
    for line in hostlines:
        entries = line.split("#")[0].split()
        hosts[entries[1]] = entries[0]

    return hosts


def get_core_temperature():
    """
    Returns the internal core temperature in degrees celsius
    """
    # older versions had vcgencmd coming from raspberrypi-firmware and located in /opt/vc/bin
    # in newer versions, the command comes from raspberrypi-utils and it's in /usr/bin
    # we try this for future compatibility even though we still have to use raspberrypi-firmware for now
    # we get it from https://alaa.ad24.cz/packages/r/raspberrypi-firmware/raspberrypi-firmware-20231019-1-armv7h.pkg.tar.xz

    vcgencmd_possible_locations = ["/opt/vc/bin/vcgencmd", "/usr/bin/vcgencmd"]
    for loc in vcgencmd_possible_locations:
        if os.path.isfile(loc):
            vcgencmd = f"{loc} measure_temp"
            break

    if isMachinePI():
        try:
            with os.popen(vcgencmd) as df:
                temp = float(
                    "".join(filter(lambda d: str.isdigit(d) or d == ".", df.read()))
                )
            return temp
        except Exception:
            return 0
    else:
        return 0


def underPowered():
    """
    Return true if the PI is underpowered, false otherwise
    Code from rpi-bad-power https://github.com/shenxn/rpi-bad-power
    """
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

    except Exception:
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

    except Exception:
        return "N/A"


def get_partition_info(folder=""):
    """
    Returns information about the mounted partitions. If a folder is specified,
    returns information about the mounted partition containing that folder
    and its free available space.
    """
    try:
        command = f"df -Th {folder}".strip()
        with os.popen(command) as df:
            df_info = df.read().strip().split("\n")

        if len(df_info) < 2:
            raise ValueError(f"No partition information found for folder: {folder}")

        keys = df_info[0].split()
        values = df_info[1:]

        # For a specified folder, return a dictionary; otherwise, return a list of dictionaries
        if folder:
            return dict(zip(keys, values[0].split(), strict=False))
        else:
            return [dict(zip(keys, line.split(), strict=False)) for line in values]

    except Exception as e:
        print(f"Error: {e}")
        return


def set_datetime(time_on_node):
    """
    Set date and time on the PI
    time_on_node is the time to be set in the datetime format
    """

    cmd = 'date -s "{}"'.format(
        time_on_node.strftime("%d %b %Y %H:%M:%S")
    )  # 26 Jun 2020 15:04:25

    try:
        with os.popen(cmd, "r") as c:
            c.read()

        return True

    except Exception:
        return False


def SQL_dump(
    database_name=None,
    credentials=None,
    output_dir="/ethoscope_data/backup",
    outputfile=None,
):
    """
    Creates a SQL dump of the specified database
    """

    if credentials is None:
        credentials = {"username": "ethoscope", "password": "ethoscope"}
    if database_name is None:
        database_name = get_machine_name() + "_db"

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if outputfile is None:
        formatted_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        outputfile = f"{database_name}_{formatted_time}.sql"

    fullpath = os.path.join(output_dir, outputfile)

    cmd = "mysqldump -alv --compatible=ansi --skip-extended-insert --compact --user={} --password={} {} > {}".format(
        credentials["username"], credentials["password"], database_name, fullpath
    )

    try:
        # Exporting the database can take some time
        # I am not really sure if there is a way to get a real time feedback of the process
        with os.popen(cmd, "r") as c:
            c.read()

        return True

    except Exception:
        return False


def loggingStatus(status=None):
    """
    Set or read the current logging status
    """
    if status is None:
        try:
            with os.popen("systemctl is-active systemd-journal-upload.service") as df:
                status = df.read().split("\n")[2]
            if status.startswith("active"):
                return True
            else:
                return False
        except Exception:
            return -1

    elif status is True and not loggingStatus():
        try:
            logging.info("User requested to start remote Logging.")

            with open("/etc/systemd/journal-upload.conf", mode="w") as cf:
                cf.write("[Upload]\nURL=http://node:19532\n")
            logging.info("Modified journal-upload.conf to point to the node")

            with os.popen(
                "sleep 1 && systemctl enable --now systemd-journal-upload.service && sleep 2"
            ) as po:
                po.read()

            return loggingStatus()
        except Exception:
            return -1

    elif status is False and loggingStatus():
        try:
            with os.popen(
                "sleep 1 && systemctl disable --now systemd-journal-upload.service && sleep 2"
            ) as po:
                po.read()
            return loggingStatus()
        except Exception:
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
            return {
                "usage_percent": 0,
                "available_gb": 0,
                "needs_cleanup": False,
                "error": "Cannot get partition info",
            }

        # Extract usage percentage (format: "85%" -> 85)
        usage_str = partition_info.get("Use%", "0%")
        usage_percent = float(usage_str.rstrip("%"))

        # Extract available space (format: "1.2G" -> 1.2)
        available_str = partition_info.get("Avail", "0")
        available_gb = 0
        if available_str.endswith("G"):
            available_gb = float(available_str[:-1])
        elif available_str.endswith("M"):
            available_gb = float(available_str[:-1]) / 1024
        elif available_str.endswith("K"):
            available_gb = float(available_str[:-1]) / (1024 * 1024)

        needs_cleanup = usage_percent >= threshold_percent

        return {
            "usage_percent": usage_percent,
            "available_gb": available_gb,
            "needs_cleanup": needs_cleanup,
        }

    except Exception as e:
        logging.error(f"Error checking disk space: {e}")
        return {
            "usage_percent": 0,
            "available_gb": 0,
            "needs_cleanup": False,
            "error": str(e),
        }


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
        "files_deleted": 0,
        "space_freed_mb": 0,
        "errors": [],
        "deleted_files": [],
    }

    try:
        # Define data directories to clean
        data_dirs = [
            os.path.join(ethoscope_dir, "videos"),
            os.path.join(ethoscope_dir, "tracking"),
        ]

        # Calculate cutoff time (files older than this will be deleted)
        cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)

        # Collect all files with their modification times
        files_to_check = []
        for data_dir in data_dirs:
            if os.path.exists(data_dir):
                # Look for common ethoscope file patterns
                patterns = ["*.db", "*.h264", "*.mp4", "*.avi", "*.sql", "*.log"]
                for pattern in patterns:
                    for file_path in glob.glob(
                        os.path.join(data_dir, "**", pattern), recursive=True
                    ):
                        try:
                            mtime = os.path.getmtime(file_path)
                            file_size = os.path.getsize(file_path)
                            files_to_check.append((file_path, mtime, file_size))
                        except OSError as e:
                            cleanup_summary["errors"].append(
                                f"Cannot access {file_path}: {e}"
                            )

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

                    cleanup_summary["files_deleted"] += 1
                    cleanup_summary["space_freed_mb"] += file_size / (1024 * 1024)
                    cleanup_summary["deleted_files"].append(file_path)

                except OSError as e:
                    cleanup_summary["errors"].append(f"Cannot delete {file_path}: {e}")
                    logging.error(f"Failed to delete {file_path}: {e}")

        action = "Would delete" if dry_run else "Deleted"
        logging.info(
            f"{action} {cleanup_summary['files_deleted']} old files, "
            f"freed {cleanup_summary['space_freed_mb']:.2f} MB"
        )

    except Exception as e:
        error_msg = f"Error during cleanup: {e}"
        cleanup_summary["errors"].append(error_msg)
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

        if "error" in space_info:
            logging.warning(f"Disk space check failed: {space_info['error']}")
            return {"status": "error", "details": space_info}

        result = {
            "status": "checked",
            "usage_percent": space_info["usage_percent"],
            "available_gb": space_info["available_gb"],
            "cleanup_performed": False,
        }

        if space_info["needs_cleanup"]:
            logging.warning(
                f"Disk usage at {space_info['usage_percent']:.1f}%, "
                f"triggering cleanup of files older than {max_age_days} days"
            )

            # Perform cleanup
            cleanup_result = cleanup_old_data(
                ethoscope_dir, max_age_days, dry_run=False
            )
            result["cleanup_performed"] = True
            result["cleanup_summary"] = cleanup_result

            # Check space again after cleanup
            new_space_info = check_disk_space(ethoscope_dir, threshold_percent)
            if "error" not in new_space_info:
                result["usage_after_cleanup"] = new_space_info["usage_percent"]
                result["available_after_cleanup"] = new_space_info["available_gb"]

                if cleanup_result["files_deleted"] > 0:
                    logging.info(
                        f"Cleanup completed: freed {cleanup_result['space_freed_mb']:.2f} MB, "
                        f"disk usage now {new_space_info['usage_percent']:.1f}%"
                    )
                else:
                    logging.warning("No files were eligible for cleanup")
        else:
            logging.debug(
                f"Disk usage at {space_info['usage_percent']:.1f}%, no cleanup needed"
            )

        return result

    except Exception as e:
        error_msg = f"Error in disk space management: {e}"
        logging.error(error_msg)
        return {"status": "error", "details": error_msg}


def _unallocated_bytes_after_root():
    """Unallocated bytes on the disk immediately after the root partition.

    This is the correct signal for whether the root filesystem can still grow.
    The root partition can already carry gigabytes of *free space* and yet leave
    most of a large medium unallocated (e.g. a 29 GB image partition flashed onto
    a 120 GB SSD, or a 64 GB SD card). Measuring free space inside the filesystem
    misses that entirely, which is why expansion used to be skipped on any medium
    larger than the image partition.

    Returns:
        int: unallocated bytes following the root partition, or 0 if the root
        partition is not the last one on its disk (growing it would be unsafe)
        or the layout cannot be determined.
    """
    try:
        root_part = subprocess.run(
            ["findmnt", "/", "-o", "source", "-n"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()  # e.g. /dev/sda2 or /dev/mmcblk0p2 or /dev/nvme0n1p2
        if not root_part:
            return 0

        part_kname = os.path.basename(root_part)  # sda2 / mmcblk0p2 / nvme0n1p2
        disk = (
            subprocess.run(
                ["lsblk", "-no", "pkname", root_part],
                capture_output=True,
                text=True,
                check=False,
            )
            .stdout.strip()
            .splitlines()
        )
        disk = disk[0].strip() if disk else ""
        if not disk:
            return 0

        # Every partition appears as a sub-directory of its disk in sysfs
        # (/sys/class/block/<disk>/<part>/). These fields are always in 512-byte
        # sectors, regardless of the physical sector size.
        diskdir = f"/sys/class/block/{disk}"

        def _read_int(path):
            with open(path) as fh:
                return int(fh.read())

        disk_sectors = _read_int(f"{diskdir}/size")
        part_start = _read_int(f"{diskdir}/{part_kname}/start")
        part_sectors = _read_int(f"{diskdir}/{part_kname}/size")
        part_end = part_start + part_sectors

        # Only safe to grow the root partition if it is the LAST one: no sibling
        # partition may begin or extend beyond its end.
        for entry in os.listdir(diskdir):
            if entry == part_kname or not os.path.exists(f"{diskdir}/{entry}/start"):
                continue
            if (
                _read_int(f"{diskdir}/{entry}/start")
                + _read_int(f"{diskdir}/{entry}/size")
                > part_end
            ):
                return 0  # a partition lies beyond root -> root is not last

        return max(0, disk_sectors - part_end) * 512
    except Exception as e:
        logging.error(f"Could not determine unallocated space after root: {e}")
        return 0


def expand_rootfs():
    """
    Execute raspi-config --expand-rootfs if the system supports it and there is room for expansion.

    Returns:
        dict: {'success': bool, 'message': str, 'expanded': bool}
    """
    result = {"success": False, "message": "", "expanded": False}

    try:
        # Check if we're on a Raspberry Pi
        if not isMachinePI():
            result["message"] = (
                "Not running on Raspberry Pi - rootfs expansion not applicable"
            )
            result["success"] = True
            return result

        # Check if raspi-config exists and is executable
        raspi_config_locations = ["/usr/bin/raspi-config", "/bin/raspi-config"]
        raspi_config_path = None

        for path in raspi_config_locations:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                raspi_config_path = path
                break

        if not raspi_config_path:
            result["message"] = "raspi-config not found or not executable"
            return result

        # Expansion is needed only when the root partition does not already fill
        # its disk — i.e. there is unallocated space AFTER it. Checking free space
        # *inside* the filesystem (the previous heuristic) is wrong: a large image
        # partition can carry gigabytes of free space yet still leave most of a big
        # card/SSD unallocated, so it silently skipped expansion on any medium
        # larger than the image partition (a big SD card just as much as an SSD).
        unallocated = _unallocated_bytes_after_root()
        if unallocated < 1 * 1024**3:  # < 1 GiB unallocated -> already fills disk
            result["message"] = (
                f"Root partition already fills its disk "
                f"({unallocated / 1024**3:.2f}GB unallocated) - expansion not needed"
            )
            result["success"] = True
            return result

        try:
            # raspi-config re-detects the root device itself (findmnt/lsblk) and
            # handles SD cards, USB SSDs and NVMe alike; it grows the partition now
            # and schedules the filesystem resize for the next boot.
            expand_cmd = f"{raspi_config_path} --expand-rootfs"

            with os.popen(expand_cmd) as cmd:
                output = cmd.read().strip()
                exit_code = cmd.close()

            if exit_code is None or exit_code == 0:
                result["success"] = True
                result["expanded"] = True
                result["message"] = (
                    "Root filesystem expansion completed successfully - reboot required to take effect"
                )
                logging.info(f"Root filesystem expanded: {output}")
            else:
                result["message"] = (
                    f"raspi-config --expand-rootfs failed with exit code {exit_code}: {output}"
                )
                logging.error(result["message"])

        except Exception as e:
            result["message"] = f"Error executing raspi-config: {str(e)}"
            logging.error(result["message"])

    except Exception as e:
        result["message"] = f"Error in expand_rootfs: {str(e)}"
        logging.error(result["message"])

    return result


# libcamera ships its sensor tuning files in a pipeline-specific directory:
# "pisp" for the Pi 5's ISP, "vc4" for every earlier model. picamera2's own
# load_tuning_file() only searches vc4, which is why the path is resolved here.
#
# Both directories are installed on a Pi 3, each holding a file of the same name,
# so "first one that exists" picks the wrong pipeline. The directory must be
# chosen by Pi generation instead, which is what _tuning_dirs_for_this_pi does.
_LIBCAMERA_PIPELINE_DIRS = {
    "pisp": (
        "/usr/share/libcamera/ipa/rpi/pisp",
        "/usr/local/share/libcamera/ipa/rpi/pisp",
    ),
    "vc4": (
        "/usr/share/libcamera/ipa/rpi/vc4",
        "/usr/local/share/libcamera/ipa/rpi/vc4",
    ),
}

# The Pi generation from which libcamera uses the pisp pipeline.
_FIRST_PISP_MODEL = 5


def _tuning_dirs_for_this_pi(model_number=None):
    """
    Tuning directories to search, most appropriate pipeline first.

    Args:
        model_number (int): Raspberry Pi model number. Detected when omitted.

    Returns:
        tuple: Directories in search order. The other pipeline is kept as a
            fallback so an unusual layout still resolves something rather than
            leaving the camera on default tuning.
    """
    if model_number is None:
        try:
            model_number = pi_version().get("model_number", 0)
        except Exception:
            model_number = 0

    if model_number and model_number >= _FIRST_PISP_MODEL:
        order = ("pisp", "vc4")
    else:
        # Pi 0-4, and the unknown case: vc4 is right for every deployed device.
        order = ("vc4", "pisp")

    return tuple(d for pipeline in order for d in _LIBCAMERA_PIPELINE_DIRS[pipeline])


def get_camera_tuning_file(sensor=None, model_number=None):
    """
    Resolve the NoIR libcamera tuning file for the attached camera sensor.

    An ethoscope cannot work without an IR pass-through (NoIR) camera, so NoIR
    tuning is unconditional and is not a user setting. What *does* vary is the
    sensor - ov5647 (PiNoIR 1), imx219 (PiNoIR 2), imx477 (HQ) and imx708
    (Camera Module 3) each need their own file - and which pipeline directory
    that file must come from, which depends on the Pi generation rather than on
    which copy happens to be installed.

    Args:
        sensor (str): Sensor name such as "imx219". Detected automatically
            when omitted.
        model_number (int): Raspberry Pi model number. Detected when omitted.

    Returns:
        str: Absolute path to the NoIR tuning file, or None when the sensor
            cannot be detected or no matching file is installed. Callers must
            treat None as a degraded state and say so loudly - silently
            falling back to the default (colour) tuning changes auto-exposure
            behaviour with no trace in the data (see issue #222).
    """
    if sensor is None:
        sensor = _get_camera_sensor_info()

    if not sensor:
        logging.warning("Could not detect the camera sensor; no tuning file resolved")
        return None

    directories = _tuning_dirs_for_this_pi(model_number)

    filename = f"{sensor}_noir.json"
    for directory in directories:
        candidate = os.path.join(directory, filename)
        if os.path.isfile(candidate):
            return candidate

    logging.warning(f"No NoIR tuning file '{filename}' found in any of {directories}")
    return None


# The frame grabber runs in its own process, so what it actually loaded cannot be
# read back through the object. It records the outcome here, following the same
# file-on-disk convention already used for the detected camera model.
CAMERA_TUNING_STATUS_FILE = "/etc/ethoscope/camera-tuning"


def set_camera_tuning_status(tuning_file, path=CAMERA_TUNING_STATUS_FILE):
    """
    Record which tuning file the camera actually loaded.

    Args:
        tuning_file (str): Path that was loaded, or None if the camera fell back
            to libcamera's default (colour) tuning.
        path (str): Where to record it.
    """
    try:
        ensure_dir_exists(path)
        with open(path, "w") as f:
            f.write(tuning_file or "DEFAULT")
    except Exception as e:
        logging.error(f"Could not record camera tuning status to {path}: {e}")


def get_camera_tuning_status(path=CAMERA_TUNING_STATUS_FILE):
    """
    Report the tuning file the camera last loaded.

    Returns:
        str: The tuning file path, "DEFAULT" when the camera fell back to
            libcamera's default (colour) tuning - which means auto-exposure
            behaves differently and the run is not comparable with correctly
            tuned ones - or None if tracking has not run yet.
    """
    try:
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip() or None
    except Exception as e:
        logging.warning(f"Could not read camera tuning status from {path}: {e}")
    return None


def get_maxfps_setting(path="/etc/ethoscope/maxfps_setting"):
    """
    Reads the maximum FPS setting for camera operation.

    Args:
        path (str): Path to the configuration file

    Returns:
        int: Maximum FPS value, defaults to DEFAULT_MAXFPS if the file is
            missing or invalid
    """
    try:
        if os.path.exists(path):
            with open(path) as f:
                content = f.read().strip()
                fps_value = int(content)
                # Validate range
                if 1 <= fps_value <= 30:
                    return fps_value
                else:
                    logging.warning(
                        f"Invalid FPS value {fps_value} in {path}, using default "
                        f"{DEFAULT_MAXFPS}"
                    )
                    return DEFAULT_MAXFPS
        return DEFAULT_MAXFPS
    except (ValueError, OSError) as e:
        logging.warning(
            f"Error reading max FPS setting from {path}: {e}, using default "
            f"{DEFAULT_MAXFPS}"
        )
        return DEFAULT_MAXFPS


def set_maxfps_setting(max_fps, path="/etc/ethoscope/maxfps_setting"):
    """
    Sets the maximum FPS preference for camera operation.

    Args:
        max_fps (int): Maximum FPS value (1-30)
        path (str): Path to the configuration file
    """
    try:
        # Validate input
        if not isinstance(max_fps, int) or not (1 <= max_fps <= 30):
            raise ValueError(
                f"Max FPS must be an integer between 1 and 30, got {max_fps}"
            )

        ensure_dir_exists(path)

        with open(path, "w") as f:
            f.write(str(max_fps))

        logging.info(f"Max FPS setting updated: max_fps={max_fps}")
    except Exception as e:
        logging.error(f"Error setting max FPS preference to {path}: {e}")
        raise


def get_gain_setting(path="/etc/ethoscope/gain_setting"):
    """
    Reads the camera gain setting for optimal tracking performance.

    Args:
        path (str): Path to the configuration file

    Returns:
        float: Camera gain value, defaults to DEFAULT_CAMERA_GAIN if the file is
            missing or invalid.
    """
    try:
        if os.path.exists(path):
            with open(path) as f:
                content = f.read().strip()
                gain_value = float(content)
                # Validate range (1.0 to 16.0 is typical for Pi cameras)
                if 1.0 <= gain_value <= 16.0:
                    return gain_value
                else:
                    logging.warning(
                        f"Invalid gain value {gain_value} in {path}, using default "
                        f"{DEFAULT_CAMERA_GAIN}"
                    )
                    return DEFAULT_CAMERA_GAIN
        return DEFAULT_CAMERA_GAIN
    except (ValueError, OSError) as e:
        logging.warning(
            f"Error reading gain setting from {path}: {e}, using default "
            f"{DEFAULT_CAMERA_GAIN}"
        )
        return DEFAULT_CAMERA_GAIN


def set_gain_setting(gain, path="/etc/ethoscope/gain_setting"):
    """
    Sets the camera gain preference for optimal tracking performance.

    Args:
        gain (float): Camera gain value (1.0-16.0, lower values reduce noise artifacts)
        path (str): Path to the configuration file
    """
    try:
        # Validate input
        if not isinstance(gain, (int, float)) or not (1.0 <= gain <= 16.0):
            raise ValueError(f"Gain must be a number between 1.0 and 16.0, got {gain}")

        ensure_dir_exists(path)

        with open(path, "w") as f:
            f.write(str(float(gain)))

        logging.info(f"Camera gain setting updated: gain={gain}")
    except Exception as e:
        logging.error(f"Error setting gain preference to {path}: {e}")
        raise
