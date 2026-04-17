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
import subprocess
import time
from optparse import OptionParser

DEFAULT_CONFIG_FILE = "/run/ethoscope/light_schedule.json"
DEFAULT_POLL_INTERVAL = 30
DEFAULT_GPIO_PIN = 17


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
    ):
        self.config_file = config_file
        self.poll_interval = poll_interval
        self.gpio_pin = str(gpio_pin)
        self._current_state = None  # None=unknown, True=on, False=off
        self._running = True

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

    def run(self):
        """
        Main polling loop. Reads schedule and controls LED until stopped.
        """
        logging.info(
            "Light daemon started. Config: %s, Poll: %ds, GPIO: %s",
            self.config_file,
            self.poll_interval,
            self.gpio_pin,
        )

        while self._running:
            lights_on, lights_off, active = self.read_schedule()

            if active:
                desired = self.should_light_be_on(lights_on, lights_off)
            else:
                desired = False

            self.set_led(desired)

            # Sleep in small increments so we can respond to signals promptly
            for _ in range(self.poll_interval):
                if not self._running:
                    break
                time.sleep(1)

        # Ensure LED is off on exit
        self.set_led(False)
        logging.info("Light daemon stopped.")

    def shutdown(self, signum=None, frame=None):
        """
        Signal handler: stop the main loop (LED turned off in run()).
        """
        logging.info("Received signal %s, shutting down...", signum)
        self._running = False


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
    )

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, controller.shutdown)
    signal.signal(signal.SIGINT, controller.shutdown)

    controller.run()


if __name__ == "__main__":
    main()
