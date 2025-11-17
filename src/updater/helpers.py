__author__ = "quentin"


import datetime
import http.client
import json
import logging
import os
import random
import subprocess
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request


class WrongMachineID(Exception):
    pass


try:
    pass
except Exception:
    logging.warning("Could not load netifaces. This is needed for node stuff")
try:
    import concurrent
    import concurrent.futures as futures
except Exception:
    logging.warning("Could not load concurrent. This is needed for node stuff")


class UnexpectedAction(Exception):
    pass


class NotNode(Exception):
    pass


def get_commit_version(commit):
    return {
        "id": str(commit),
        "date": datetime.datetime.utcfromtimestamp(commit.committed_date).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


def assert_node(is_node):
    if not is_node:
        raise NotNode("This device is not a node.")


def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)


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
        return "VIRTUASCOPE_" + str(random.randint(100, 999))


def scan_one_device(ip, timeout=2, port=8888, page="id"):
    """
    :param url: the url to parse
    :param timeout: the timeout of the url request
    :param port: the port to request
    :return: The message, parsed as dictionary. the "ip" field is also added to the result.
    If the url could not be reached/parsed, (None,None) is returned
    """

    url = "%s:%i/%s" % (ip, port, page)
    try:
        req = urllib.request.Request(url)
        f = urllib.request.urlopen(req, timeout=timeout)
        message = f.read()

        if not message:
            logging.error("URL error whist scanning url: %s. No message back." % url)
            raise urllib.error.URLError("No message back")
        try:
            resp = json.loads(message)
            return (resp["id"], ip)
        except ValueError:
            logging.error("Could not parse response from %s as JSON object" % url)

    except urllib.error.URLError:
        pass
        # logging.error("URL error whist scanning url: %s. Server down?" % url )

    except Exception as e:
        logging.error("Unexpected error whilst scanning url: %s" % url)
        raise e

    return None, ip


def update_dev_map_wrapped(
    devices_map,
    id,
    what="data",
    type=None,
    port=9000,
    data=None,
    result_main_dir="/ethoscope_data/results",
):
    """
    Just a routine to format our GET urls. This improves readability whilst allowing us to change convention (e.g. port) without rewriting everything.

    :param id: machine unique identifier
    :param what: e.g. /data, /control
    :param type: the type of request for POST
    :param port:
    :return:
    """

    ip = devices_map[id]["ip"]

    request_url = f"{ip}:{port}/{what}/{id}"
    if type is not None:
        request_url = request_url + "/" + type

    req = urllib.request.Request(
        url=request_url, data=data, headers={"Content-Type": "application/json"}
    )

    logging.info("requesting %s" % request_url)

    try:
        f = urllib.request.urlopen(req, timeout=10)
        message = f.read()

        if message:
            data = json.loads(message)

            if id not in devices_map:
                logging.warning(
                    "Device %s is not in device map. Rescanning subnet..." % id
                )
                generate_new_device_map(result_main_dir=result_main_dir)
            try:
                devices_map[id].update(data)
                return data

            except KeyError as e:
                logging.error("Device %s is not detected" % id)
                raise KeyError("Device %s is not detected" % id) from e

    except http.client.BadStatusLine as e:
        logging.error("BadlineSatus, most probably due to update device and auto-reset")
        raise e

    except (urllib.error.URLError, TimeoutError) as e:
        if hasattr(e, "reason"):
            logging.error("We failed to reach a server.")
            logging.error("Reason: " + str(e.reason))
            raise e
        elif hasattr(e, "code"):
            logging.error("The server couldn't fulfill the request.")
            logging.error("Error code: " + str(e.code))
            raise e
        elif isinstance(e, TimeoutError):
            logging.error("Request timed out.")
            raise e

    return devices_map


def receive_device_IPs():
    """
    Interrogates the NODE on its current knowledge of devices, then extracts from the JSON record
    only the IPs
    """
    devices = []
    try:
        url = "http://localhost/devices"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        f = urllib.request.urlopen(req, timeout=10)
        js = json.load(f)
        for key in js:
            if js[key]["status"] != "offline" and "ip" in js[key]:
                devices.append("http://%s" % js[key]["ip"])
        # devices = [ "http://" + js[key]['ip'] for key in js.keys() if js[key]['status'] != "offline" ]
    except Exception:
        logging.error(
            "The node ethoscope server is not running or cannot be reached. A list of available ethoscopes could not be found."
        )
        logging.error(traceback.format_exc())

    return devices


def generate_new_device_map():
    """
    Generate the device map as JSON dictionary
    Interrogates only IPs passed on by the NODE, thus piggybacking on the node's knowledge of the subnet
    """
    devices_map = {}
    urls = receive_device_IPs()

    # We can use a with statement to ensure threads are cleaned up promptly
    with futures.ThreadPoolExecutor(max_workers=128) as executor:
        # Start the load operations and mark each future with its URL

        fs = [executor.submit(scan_one_device, url) for url in urls]
        for f in concurrent.futures.as_completed(fs):

            try:
                id, ip = f.result()
                if id is None:
                    continue
                devices_map[id] = {"ip": ip, "status": "Software broken", "id": id}

            except Exception:
                logging.error("Error whilst pinging url")
                logging.error(traceback.format_exc())

    if len(devices_map) < 1:
        logging.warning("No device detected")
        return devices_map

    logging.info(
        "Detected %i devices:\n%s" % (len(devices_map), str(list(devices_map.keys())))
    )

    # We can use a with statement to ensure threads are cleaned up promptly
    with futures.ThreadPoolExecutor(max_workers=128) as executor:
        # Start the load operations and mark each future with its URL
        fs = {}
        for id in list(devices_map.keys()):
            fs[executor.submit(update_dev_map_wrapped, devices_map, id)] = id

        for f in concurrent.futures.as_completed(fs):
            id = fs[f]
            try:
                data = f.result()
                devices_map[id].update(data)
            except Exception as e:
                if isinstance(e.__cause__, (TimeoutError, urllib.error.URLError)):
                    devices_map[id]["status"] = "Unreachable"
                    logging.warning(
                        "Device %s is unreachable (timeout/network error)" % id
                    )
                else:
                    devices_map[id]["status"] = "Software broken"
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc())

    # Adds the active_branch to devices_,map
    with futures.ThreadPoolExecutor(max_workers=128) as executor:
        # Start the load operations and mark each future with its URL
        fs = {}
        for id in list(devices_map.keys()):
            fs[
                executor.submit(
                    update_dev_map_wrapped,
                    devices_map,
                    id,
                    what="device/active_branch",
                    port="8888",
                )
            ] = id
        for f in concurrent.futures.as_completed(fs):
            id = fs[f]
            try:
                data = f.result()
                devices_map[id].update(data)
            except Exception as e:
                if isinstance(e.__cause__, (TimeoutError, urllib.error.URLError)):
                    devices_map[id]["status"] = "Unreachable"
                    logging.warning(
                        "Device %s is unreachable (timeout/network error)" % id
                    )
                else:
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc())

    # Adds the check_update to devices_,map
    with futures.ThreadPoolExecutor(max_workers=128) as executor:
        # Start the load operations and mark each future with its URL
        fs = {}
        for id in list(devices_map.keys()):
            fs[
                executor.submit(
                    update_dev_map_wrapped,
                    devices_map,
                    id,
                    what="device/check_update",
                    port="8888",
                )
            ] = id
        for f in concurrent.futures.as_completed(fs):
            id = fs[f]
            try:
                data = f.result()
                devices_map[id].update(data)
            except Exception as e:
                if isinstance(e.__cause__, (TimeoutError, urllib.error.URLError)):
                    devices_map[id]["status"] = "Unreachable"
                    logging.warning(
                        "Device %s is unreachable (timeout/network error)" % id
                    )
                else:
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc())

    return devices_map


def updates_api_wrapper(ip, id, what="check_update", type=None, port=8888, data=None):
    response = ""

    hn = urllib.parse.urlparse(ip).hostname

    request_url = f"http://{hn}:{port}/{what}/{id}"

    # if type is not None:
    #     request_url = request_url + "/" + type
    if data is not None:
        data = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        url=request_url, data=data, headers={"Content-Type": "application/json"}
    )

    logging.info("requesting %s" % request_url)

    try:
        f = urllib.request.urlopen(req, timeout=10)
        message = f.read()

        if message:
            response = json.loads(message)

    except http.client.BadStatusLine as e:
        logging.error("BadlineSatus, most probably due to update device and auto-reset")
        raise e

    except (urllib.error.URLError, TimeoutError) as e:
        if hasattr(e, "reason"):
            logging.error("We failed to reach a server.")
            logging.error("Reason: " + str(e.reason))
            raise e
        elif hasattr(e, "code"):
            logging.error("The server couldn't fulfill the request.")
            logging.error("Error code: " + str(e.code))
            raise e
        elif isinstance(e, TimeoutError):
            logging.error("Request timed out.")
            raise e

    return response


def _reload_daemon(name):
    subprocess.call(["systemctl", "restart", name])


def _get_active_backup_services():
    """
    Detect which backup services are currently running.

    Returns:
        list: Names of active backup services
    """
    backup_services = [
        "ethoscope_backup_mysql",
        "ethoscope_backup_video",
        "ethoscope_backup_sqlite",
        "ethoscope_backup_unified",
    ]

    active_services = []
    for service in backup_services:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip() == "active":
                active_services.append(service)
                logging.info(f"Detected active backup service: {service}")
        except Exception as e:
            logging.warning(f"Failed to check status of {service}: {e}")

    return active_services


def reload_node_daemon():
    """
    Reload node services after an update.

    This includes:
    - systemctl daemon-reload (to pick up any service file changes)
    - ethoscope_node (main node server)
    - ethoscope_update_node (update daemon)
    - Any active backup services (ethoscope_backup_*)
    """
    logging.info("Reloading node services after update")

    # Reload systemd daemon to pick up any service file changes
    logging.info("Running systemctl daemon-reload")
    subprocess.call(["systemctl", "daemon-reload"])

    # Restart main node service
    logging.info("Restarting ethoscope_node service")
    _reload_daemon("ethoscope_node")

    # Restart update service
    logging.info("Restarting ethoscope_update_node service")
    _reload_daemon("ethoscope_update_node")

    # Restart any active backup services
    active_backup_services = _get_active_backup_services()
    for service in active_backup_services:
        logging.info(f"Restarting active backup service: {service}")
        _reload_daemon(service)

    logging.info("Node service reload complete")


def reload_device_daemon():
    """
    Reload device services after an update.

    This includes:
    - systemctl daemon-reload (to pick up any service file changes)
    - ethoscope_listener (main listener service)
    - ethoscope_GPIO_listener (GPIO handler)
    - ethoscope_device (device web server)
    """
    logging.info("Reloading device services after update")

    # Reload systemd daemon to pick up any service file changes
    logging.info("Running systemctl daemon-reload")
    subprocess.call(["systemctl", "daemon-reload"])

    # Restart device services
    logging.info("Restarting ethoscope_listener service")
    _reload_daemon("ethoscope_listener")

    logging.info("Restarting ethoscope_GPIO_listener service")
    _reload_daemon("ethoscope_GPIO_listener")

    time.sleep(3)

    logging.info("Restarting ethoscope_device service")
    _reload_daemon("ethoscope_device")

    # Restart update service
    logging.info("Restarting ethoscope_update service")
    _reload_daemon("ethoscope_update")

    logging.info("Device service reload complete")
