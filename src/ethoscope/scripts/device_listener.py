#!/usr/bin/env python
#
#  device_listener.py
#
#  Copyright 2022 Giorgio F. Gilestro <gg@jenner>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  This ethoscope listener controls the most basic ethoscope functions:
#
#  - Start / stop tracking with given options
#  - Start / stop video recording with given options
#
#  Every other action is controlled through the web server.
#  Decoupling these two activities increases robustness
#  Essentially it allows us to restart the web process and the avahi component without affecting the ethoscope
#  When it is running


__author__ = "giorgio"

import json
import logging
import os
import socket
import threading
import traceback
from optparse import OptionParser

from ethoscope.control.record import ControlThreadVideoRecording
from ethoscope.control.tracking import ControlThread
from ethoscope.utils import pi
from ethoscope.utils.scheduler import TimedStopError


class commandingThread(threading.Thread):
    def __init__(self, ethoscope_info, host="", port=5000):
        self.host = host
        self.port = port
        self.size = 1024 * 16  # Match ethoclient's COMM_PACKET_SIZE

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)

        self.ethoscope_info = ethoscope_info
        self.control = ControlThread(
            machine_id=ethoscope_info["MACHINE_ID"],
            name=ethoscope_info["MACHINE_NAME"],
            version=ethoscope_info["GIT_VERSION"],
            ethoscope_dir=ethoscope_info["ETHOSCOPE_DIR"],
            data=None,
        )

        self.running = True
        threading.Thread.__init__(self)

    def stop(self):
        self.running = False
        # makes a dummy connection
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            (self.host, self.port)
        )
        self.sock.close()

    def run(self):
        """
        listen for new incoming clients
        creates a new subthread for each incoming client
        """

        while self.running:
            try:
                client, address = self.sock.accept()
                threading.Thread(
                    target=self.handle_client, args=(client, address)
                ).start()
            except OSError:
                if not self.running:
                    break
                else:
                    logging.exception("Socket error in listener thread")
                    break

    def handle_client(self, client, address):
        """
        start listening for registered client
        """

        try:
            # Receive data in chunks until we have valid JSON
            recv = b""
            while True:
                chunk = client.recv(self.size)
                if not chunk:
                    break
                recv += chunk
                try:
                    json.loads(recv.decode("utf-8"))
                    break  # Valid JSON received
                except json.JSONDecodeError:
                    continue  # Keep receiving

            if recv:
                message = json.loads(recv)
                try:
                    response_data = self.action(message["command"], message["data"])
                    result = json.dumps({"response": response_data}).encode("utf-8")
                except Exception as e:
                    # Send error response instead of closing connection
                    error_msg = f"Error executing command '{message.get('command', 'unknown')}': {str(e)}"
                    logging.error(error_msg)
                    logging.error(traceback.format_exc())
                    result = json.dumps({"response": f"ERROR: {error_msg}"}).encode(
                        "utf-8"
                    )
                client.send(result)
            else:
                # Empty request received
                result = json.dumps(
                    {"response": "ERROR: Empty request received"}
                ).encode("utf-8")
                client.send(result)

        except Exception as e:
            # Log the error and close connection
            logging.error(f"Client communication error: {str(e)}")
            logging.error(traceback.format_exc())
        finally:
            client.close()

    # How long to wait for a control thread to wind down before answering the
    # client anyway. Long enough for a tracking thread to close its database,
    # short enough that a wedged one does not hang the caller for ever - the
    # old code joined without a timeout.
    _STOP_JOIN_TIMEOUT = 30

    # Statuses that mean the device is doing something, whichever kind of control
    # thread reported them. See _busy_with() for why the thread alone will not do.
    _ACTIVE_STATUSES = ("initialising", "running", "recording", "streaming", "stopping")

    def _busy_with(self):
        """
        Name the activity currently under way, if any.

        Two things have to agree here, and neither alone is enough:

        ``is_alive()`` catches a tracking thread that has already taken, or is
        about to take, the camera but does not yet call itself "running" - a
        status check would read that as idle.

        The reported status catches video recording and streaming, where
        ``ControlThreadVideoRecording.run()`` sets the recorder up, hands the
        camera to its own capture thread and returns. The control thread is dead
        within a second of the start while the device goes on recording for
        hours, so ``is_alive()`` reads *that* as idle - which left the Stop
        button doing nothing at all for recordings and streams.

        Returns:
            str: The status of the activity under way, or None when the device
                is idle.
        """
        status = self.control.info.get("status")
        if self.control.is_alive() or status in self._ACTIVE_STATUSES:
            return status
        return None

    def _stop_current_activity(self):
        """
        Stop whatever the device is doing and wait for the thread to finish.

        Returns:
            bool: True if an activity was stopped, False if there was none.
        """
        if self._busy_with() is None:
            return False

        # A recording or streaming control thread returned the moment it handed
        # the camera over, so there is nothing left to join - and joining a
        # thread that was never started raises. Decided before stop() rather
        # than after, since a tracking thread only unwinds once stopped.
        joinable = self.control.is_alive()

        logging.info("Stopping monitor")
        self.control.stop()
        if joinable:
            logging.info("Joining monitor")
            self.control.join(timeout=self._STOP_JOIN_TIMEOUT)
        if self.control.is_alive():
            # Reason: say so rather than pretend. The thread still holds the
            # camera, so the next start will be refused instead of quietly
            # fighting it for the sensor.
            logging.error(
                f"The control thread did not stop within {self._STOP_JOIN_TIMEOUT}s "
                "and is still holding the camera."
            )
        else:
            logging.info("Monitor stopped")
        return True

    def action(self, action, data=None):
        """
        act on client's instructions
        """

        # Reason: this tested `not data`, which rejects an empty config as well
        # as a missing one. They are not the same thing:
        # ControlThread._parse_user_options() fills in the default class for
        # every field it does not find, so {} is a complete, valid request for
        # a fully defaulted run - which is exactly what --run without --json
        # asks for. Only None means "the caller sent no configuration at all".
        if data is None and action in ["start", "start_record"]:
            return "This action requires JSON data"

        # Reason: start/start_record/stream used to overwrite self.control while
        # the previous control thread was still alive. That thread kept running,
        # kept its database open and kept the camera, but nothing referenced it
        # any more, so it could never be stopped. The new thread then failed to
        # acquire the camera ("Device or resource busy"), sat in "initialising",
        # and two minutes later the initialisation watchdog SIGKILLed the whole
        # listener - taking the healthy experiment with it. Refuse instead: an
        # experiment already under way is data, and replacing it is not
        # something to do by accident.
        if action in ["start", "start_record", "stream"]:
            busy = self._busy_with()
            if busy is not None:
                return (
                    f"ERROR: this ethoscope is already busy ({busy}). Stop the "
                    "current activity before starting a new one."
                )

        if action == "help":
            return (
                "Commands that do not require JSON info: help, info, status, stop, stream, remove, restart.\n"
                "Commands that do require JSON info: start, start_record.\n"
                "set_autostop takes optional JSON info: a duration or a stop_at to "
                "reschedule the automatic stop, or nothing at all to cancel it."
            )

        elif action == "info":
            return self.control.info

        elif action == "status":
            return self.control.info["status"]

        # `data is not None` rather than `data`, for the reason given at the
        # guard above: {} is a valid request for a fully defaulted run. The
        # guard has already turned None into a message, so this only decides
        # whether an empty config falls through to "action not available".
        elif action == "start" and data is not None:
            #            if self.control.controltype != "tracking":
            self.control = ControlThread(
                machine_id=self.ethoscope_info["MACHINE_ID"],
                name=self.ethoscope_info["MACHINE_NAME"],
                version=self.ethoscope_info["GIT_VERSION"],
                ethoscope_dir=self.ethoscope_info["ETHOSCOPE_DIR"],
                data=data,
            )

            self.control.start()

            logging.info("Starting tracking")
            return "Starting tracking activity"

        elif action == "stream":
            self.control = ControlThreadVideoRecording(
                machine_id=self.ethoscope_info["MACHINE_ID"],
                name=self.ethoscope_info["MACHINE_NAME"],
                version=self.ethoscope_info["GIT_VERSION"],
                ethoscope_dir=self.ethoscope_info["ETHOSCOPE_VIDEOS_DIR"],
                data={"recorder": {"name": "Streamer", "arguments": {}}},
            )

            self.control.start()
            return "Starting streaming activity"

        elif action == "start_record" and data is not None:
            self.control = ControlThreadVideoRecording(
                machine_id=self.ethoscope_info["MACHINE_ID"],
                name=self.ethoscope_info["MACHINE_NAME"],
                version=self.ethoscope_info["GIT_VERSION"],
                ethoscope_dir=self.ethoscope_info["ETHOSCOPE_VIDEOS_DIR"],
                data=data,
            )

            self.control.start()
            return "Starting recording or streaming activity"

        elif action == "stop":
            # Reason: this used to be gated on a status of running/recording/
            # streaming, so a thread stuck in "initialising" - the state a
            # camera that will not open leaves it in - could not be stopped at
            # all, and the only way out was to kill the process or reboot the
            # Pi. ControlThread.stop() already knows which states it can act on,
            # including "initialising", so let it decide.
            if not self._stop_current_activity():
                return "There is no activity to stop."
            return "Stopping ethoscope activity"

        elif action == "set_autostop":
            if self.control.info["status"] not in [
                "running",
                "recording",
                "streaming",
            ]:
                return (
                    "ERROR: There is no experiment running, so there is nothing to "
                    "stop automatically."
                )

            try:
                result = self.control.set_autostop(data)
            except TimedStopError as e:
                # What the user typed, read back to them. Falling through to the
                # generic handler would bury it in a traceback.
                return f"ERROR: {e}"

            logging.info(f"Automatic stop changed to {result}")
            return result

        elif action == "remove" and self._busy_with() is None:
            logging.info("Removing persistent file.")
            try:
                if os.path.exists(pi.PERSISTENT_STATE):
                    os.remove(pi.PERSISTENT_STATE)
                    return "The persistent file was succesfully removed"
                else:
                    return "The persistent file does not exist"
            except Exception:
                return "The persistent file exists but could not be removed"

        elif action == "restart" and self._busy_with() is None:
            logging.info("Restarting the ethoscope device service")
            with os.popen("systemctl restart ethoscope_device.service") as df:
                outcome = df.read()
                logging.info(outcome)
                return outcome

        elif action == "test_module" and not data:
            logging.info("Sending the test command to the connected module")
            return pi.getModuleCapabilities(test=True)

        elif action == "test_module" and data:
            logging.info("Restarting the ethoscope device service")
            return pi.getModuleCapabilities(command=data["command"])

        else:
            # raise Exception("No such command: %s. Available commands are info, status, start, stop, start_record, stream " % action)
            return "This ethoscope action is not available."


if __name__ == "__main__":

    parser = OptionParser()
    parser.add_option(
        "-r",
        "--run",
        dest="run",
        default=False,
        help="Runs tracking directly",
        action="store_true",
    )
    parser.add_option(
        "-v",
        "--record-video",
        dest="record_video",
        default=False,
        help="Records video instead of tracking",
        action="store_true",
    )
    parser.add_option(
        "-j", "--json", dest="json", default=None, help="A JSON config file"
    )
    parser.add_option(
        "-e",
        "--ethoscope-dir",
        dest="ethoscope_dir",
        default="/ethoscope_data",
        help="Root directory for ethoscope data storage",
    )
    parser.add_option(
        "-D",
        "--debug",
        dest="debug",
        default=False,
        help="Shows all logging messages",
        action="store_true",
    )

    options, args = parser.parse_args()
    option_dict = vars(options)

    if option_dict["debug"]:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    if option_dict["json"]:
        with open(option_dict["json"]) as f:
            json_data = json.loads(f.read())
    else:
        json_data = {}

    # Calculate subdirectories from root ethoscope directory
    ethoscope_root = option_dict["ethoscope_dir"]

    ethoscope_info = {
        "MACHINE_ID": pi.get_machine_id(),
        "MACHINE_NAME": pi.get_machine_name(),
        "GIT_VERSION": pi.get_git_version(),
        "ETHOSCOPE_DIR": ethoscope_root,
        "ETHOSCOPE_VIDEOS_DIR": os.path.join(ethoscope_root, "videos"),
        "ETHOSCOPE_TRACKING_DIR": os.path.join(ethoscope_root, "tracking"),
        "ETHOSCOPE_CACHE_DIR": os.path.join(ethoscope_root, "cache"),
        "ETHOSCOPE_UPLOAD": os.path.join(ethoscope_root, "upload"),
        "DATA": json_data,
    }

    # Ensure proper directory structure and migrate from legacy if needed - July 2025 - We will remove this at some point
    from ethoscope.utils.video import ensure_video_directory_structure

    ensure_video_directory_structure(
        ethoscope_root, ethoscope_info["ETHOSCOPE_VIDEOS_DIR"]
    )

    ethoscope = commandingThread(ethoscope_info)
    ethoscope.start()
    logging.info("Ethoscope controlling server started and listening")

    if pi.was_interrupted():
        # Reason: this used to auto-restart tracking after an unclean shutdown,
        # back when ControlThread pickled its state on the way down. That resume
        # logic has been removed and nothing writes the file any more, so the
        # settings of the interrupted run are not recoverable - the metadata
        # cache keeps the user, location and run_id, but not the tracker, ROI
        # builder or stimulator. Starting anyway would look like a resume while
        # silently running on default settings, which is worse than not
        # resuming, so report the leftover file and leave the device alone.
        logging.warning(
            f"Found a leftover state file at {pi.PERSISTENT_STATE}. Resuming "
            "automatically after an unclean shutdown is no longer supported - "
            "the settings of the interrupted experiment are not recorded "
            "anywhere - so tracking has NOT been restarted. Start it from the "
            "node, and send the 'remove' command to clear the file."
        )

    if option_dict["run"]:
        # Reason: the JSON config was read into ethoscope_info["DATA"] and then
        # never passed on, so this always came back "This action requires JSON
        # data" - and the reply was discarded, so --run silently did nothing at
        # all. An empty config is legitimate here and means "use the defaults".
        requested = "start_record" if option_dict["record_video"] else "start"
        outcome = ethoscope.action(requested, ethoscope_info["DATA"])

        if isinstance(outcome, str) and outcome.startswith("ERROR:"):
            logging.error(f"Could not {requested}: {outcome}")
        else:
            logging.info(f"{requested}: {outcome}")
