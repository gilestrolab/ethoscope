#!/usr/bin/env python3
"""
Ethoscope LED Daylight Controller Daemon.

Standalone service that controls a white LED via GPIO to simulate daylight
conditions during experiments. Reads a schedule config file written by the
device tracking server and toggles the LED accordingly.

Hardware: GPIO -> BS170 MOSFET -> LED -> 100ohm -> 5Vdc.
GPIO HIGH = MOSFET on = LED on, GPIO LOW = LED off.

GPIO control uses the `pinctrl` command (available on Raspberry Pi OS Bookworm+).
"""

import datetime
import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
from optparse import OptionParser

DEFAULT_CONFIG_FILE = "/run/ethoscope/light_schedule.json"
DEFAULT_SOCKET_PATH = "/run/ethoscope/light_daemon.sock"
DEFAULT_POLL_INTERVAL = 30
DEFAULT_GPIO_PIN = 17

_CLIENT_TIMEOUT = 1.0
_LISTENER_ACCEPT_TIMEOUT = 0.5
_MAX_CMD_BYTES = 128


class LightDaemonUnavailable(RuntimeError):
    """Raised by LightDaemonClient when the daemon socket cannot be reached."""


class LightController:
    """
    Controls a GPIO-connected LED based on a time-of-day schedule.

    Reads a JSON config file at regular intervals and toggles the LED
    on or off depending on the current time and the schedule.

    Args:
        config_file: Path to the JSON schedule config file.
        poll_interval: Seconds between config file checks.
        gpio_pin: BCM GPIO pin number (default 17).
    """

    def __init__(
        self,
        config_file=DEFAULT_CONFIG_FILE,
        poll_interval=DEFAULT_POLL_INTERVAL,
        gpio_pin=DEFAULT_GPIO_PIN,
        socket_path=DEFAULT_SOCKET_PATH,
    ):
        self.config_file = config_file
        self.poll_interval = poll_interval
        self.gpio_pin = str(gpio_pin)
        self.socket_path = socket_path
        self._current_state = None  # None=unknown, True=on, False=off
        self._force = None  # None=follow schedule, True/False=forced
        self._running = True
        self._lock = threading.Lock()
        self._server_sock = None
        self._listener_thread = None

    def set_led(self, on):
        """
        Set the LED state via pinctrl.

        Args:
            on: True = LED on (GPIO driven LOW), False = LED off (GPIO driven HIGH).
        """
        if on == self._current_state:
            return

        # GPIO -> BS170 MOSFET -> LED -> 100ohm -> 5Vdc
        # GPIO HIGH (dh) = MOSFET on = LED on
        # GPIO LOW (dl) = MOSFET off = LED off
        drive = "dh" if on else "dl"
        try:
            subprocess.run(
                ["pinctrl", "set", self.gpio_pin, "op", drive],
                check=True,
                capture_output=True,
                timeout=5,
            )
            self._current_state = on
            logging.info(
                "LED %s (GPIO%s %s)", "ON" if on else "OFF", self.gpio_pin, drive
            )
        except FileNotFoundError:
            logging.error("pinctrl command not found. Is this a Raspberry Pi?")
            self._running = False
        except subprocess.CalledProcessError as e:
            logging.error("pinctrl failed: %s", e.stderr.decode().strip())
        except subprocess.TimeoutExpired:
            logging.error("pinctrl command timed out")

    def read_schedule(self):
        """
        Read and parse the schedule config file.

        Returns:
            Tuple of (lights_on, lights_off, active) where times are
            strings in HH:MM format and active is a boolean.
            Returns ("", "", False) on any error.
        """
        try:
            if not os.path.exists(self.config_file):
                return ("", "", False)

            with open(self.config_file) as f:
                data = json.load(f)

            active = data.get("active", False)
            if not active:
                return ("", "", False)

            lights_on = data.get("lights_on", "")
            lights_off = data.get("lights_off", "")

            if not lights_on or not lights_off:
                return ("", "", False)

            return (lights_on, lights_off, True)

        except (json.JSONDecodeError, OSError) as e:
            logging.warning("Failed to read schedule config: %s", e)
            return ("", "", False)

    @staticmethod
    def parse_time(time_str):
        """
        Parse an HH:MM time string into a datetime.time object.

        Args:
            time_str: Time string in HH:MM format.

        Returns:
            datetime.time object, or None if parsing fails.
        """
        try:
            parts = time_str.strip().split(":")
            return datetime.time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None

    @staticmethod
    def should_light_be_on(lights_on_str, lights_off_str, now=None):
        """
        Determine if the light should be on based on current time and schedule.

        Handles schedules that cross midnight (e.g., on at 22:00, off at 06:00).

        Args:
            lights_on_str: HH:MM string for lights-on time.
            lights_off_str: HH:MM string for lights-off time.
            now: Optional datetime.time for testing. Defaults to current local time.

        Returns:
            True if light should be on, False otherwise.
            Returns False if times cannot be parsed.
        """
        on_time = LightController.parse_time(lights_on_str)
        off_time = LightController.parse_time(lights_off_str)

        if on_time is None or off_time is None:
            return False

        if now is None:
            now = datetime.datetime.now().time()

        if on_time == off_time:
            # Same on/off time means always on (24h light)
            return True
        elif on_time < off_time:
            # Normal schedule (e.g., 07:00-19:00)
            return on_time <= now < off_time
        else:
            # Midnight-crossing schedule (e.g., 22:00-06:00)
            return now >= on_time or now < off_time

    def set_force(self, value):
        """
        Override the schedule. value=True forces ON, False forces OFF, None releases.
        Applies immediately, in addition to being honoured by the next loop tick.
        """
        with self._lock:
            self._force = value
        if value is not None:
            self.set_led(value)

    def _status_dict(self):
        with self._lock:
            force = self._force
            led = self._current_state
        lights_on, lights_off, active = self.read_schedule()
        return {
            "led": "on" if led is True else "off" if led is False else "unknown",
            "mode": "forced" if force is not None else "schedule",
            "force": None if force is None else ("on" if force else "off"),
            "schedule_active": active,
            "lights_on": lights_on,
            "lights_off": lights_off,
        }

    def _handle_command(self, cmd):
        """Translate one wire command into a one-line response (no trailing newline)."""
        normalized = " ".join(cmd.upper().split())
        if normalized == "FORCE ON":
            self.set_force(True)
            return "OK"
        if normalized == "FORCE OFF":
            self.set_force(False)
            return "OK"
        if normalized == "RELEASE":
            self.set_force(None)
            return "OK"
        if normalized == "STATUS":
            return json.dumps(self._status_dict())
        return f"ERR unknown command: {cmd!r}"

    def _start_socket_listener(self):
        """Bind the Unix socket and spawn a daemon thread to accept commands."""
        if not self.socket_path:
            return
        try:
            os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        except OSError as e:
            logging.warning("Could not create socket directory: %s", e)

        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.warning("Could not remove stale socket %s: %s", self.socket_path, e)

        try:
            self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server_sock.bind(self.socket_path)
            # Reason: single-tenant ethoscope; allow any local user (e.g. ethoscope-light CLI) to connect
            os.chmod(self.socket_path, 0o666)
            self._server_sock.listen(4)
            self._server_sock.settimeout(_LISTENER_ACCEPT_TIMEOUT)
        except OSError as e:
            logging.error("Could not bind control socket %s: %s", self.socket_path, e)
            self._server_sock = None
            return

        self._listener_thread = threading.Thread(
            target=self._listener_loop, name="light-daemon-listener", daemon=True
        )
        self._listener_thread.start()
        logging.info("Light daemon control socket: %s", self.socket_path)

    def _listener_loop(self):
        while self._running and self._server_sock is not None:
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(_CLIENT_TIMEOUT)
                data = conn.recv(_MAX_CMD_BYTES)
                cmd = data.decode("utf-8", errors="replace").strip()
                response = self._handle_command(cmd)
                conn.sendall((response + "\n").encode("utf-8"))
            except Exception as e:
                logging.warning("Light daemon socket handler error: %s", e)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _stop_socket_listener(self):
        sock = self._server_sock
        self._server_sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=1.0)
            self._listener_thread = None
        if self.socket_path:
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logging.warning("Could not remove socket on shutdown: %s", e)

    def run(self):
        """
        Main polling loop. Reads schedule and controls LED until stopped.
        Honours any force override set via the control socket.
        """
        logging.info(
            "Light daemon started. Config: %s, Poll: %ds, GPIO: %s",
            self.config_file,
            self.poll_interval,
            self.gpio_pin,
        )
        self._start_socket_listener()

        try:
            while self._running:
                with self._lock:
                    force = self._force

                if force is not None:
                    desired = force
                else:
                    lights_on, lights_off, active = self.read_schedule()
                    desired = (
                        self.should_light_be_on(lights_on, lights_off)
                        if active
                        else False
                    )

                self.set_led(desired)

                # Sleep in small increments so we can respond to signals promptly
                for _ in range(self.poll_interval):
                    if not self._running:
                        break
                    time.sleep(1)
        finally:
            self._stop_socket_listener()
            self.set_led(False)
            logging.info("Light daemon stopped.")

    def shutdown(self, signum=None, frame=None):
        """
        Signal handler: stop the main loop (LED turned off in run()).
        """
        logging.info("Received signal %s, shutting down...", signum)
        self._running = False


class LightDaemonClient:
    """
    Tiny client for the light daemon's Unix-socket control API.

    Each method opens a fresh connection, sends one line, reads one line, closes.
    Raises LightDaemonUnavailable if the daemon isn't reachable.
    """

    def __init__(self, socket_path=DEFAULT_SOCKET_PATH, timeout=_CLIENT_TIMEOUT):
        self.socket_path = socket_path
        self.timeout = timeout

    def _request(self, command):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            try:
                sock.connect(self.socket_path)
                sock.sendall((command + "\n").encode("utf-8"))
                chunks = []
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break
            finally:
                sock.close()
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise LightDaemonUnavailable(str(e)) from e
        except socket.timeout as e:
            raise LightDaemonUnavailable("timeout talking to light daemon") from e
        except OSError as e:
            raise LightDaemonUnavailable(str(e)) from e

        response = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if response.startswith("ERR"):
            raise LightDaemonUnavailable(response)
        return response

    def force_on(self):
        return self._request("FORCE ON")

    def force_off(self):
        return self._request("FORCE OFF")

    def release(self):
        return self._request("RELEASE")

    def status(self):
        response = self._request("STATUS")
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            raise LightDaemonUnavailable(
                f"unparseable status response: {response!r}"
            ) from e


def main():
    parser = OptionParser(description="Ethoscope LED daylight controller daemon")
    parser.add_option(
        "-c",
        "--config-file",
        dest="config_file",
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to light schedule JSON config file (default: {DEFAULT_CONFIG_FILE})",
    )
    parser.add_option(
        "-p",
        "--poll-interval",
        dest="poll_interval",
        type="int",
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between schedule checks (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_option(
        "-g",
        "--gpio",
        dest="gpio_pin",
        type="int",
        default=DEFAULT_GPIO_PIN,
        help=f"BCM GPIO pin number (default: {DEFAULT_GPIO_PIN})",
    )
    parser.add_option(
        "-s",
        "--socket",
        dest="socket_path",
        default=DEFAULT_SOCKET_PATH,
        help=f"Path to the control socket (default: {DEFAULT_SOCKET_PATH}). "
        "Pass an empty string to disable the socket listener.",
    )
    parser.add_option(
        "-D",
        "--debug",
        dest="debug",
        default=False,
        action="store_true",
        help="Enable debug logging",
    )

    options, args = parser.parse_args()

    log_level = logging.DEBUG if options.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    controller = LightController(
        config_file=options.config_file,
        poll_interval=options.poll_interval,
        gpio_pin=options.gpio_pin,
        socket_path=options.socket_path or None,
    )

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, controller.shutdown)
    signal.signal(signal.SIGINT, controller.shutdown)

    controller.run()


if __name__ == "__main__":
    main()
