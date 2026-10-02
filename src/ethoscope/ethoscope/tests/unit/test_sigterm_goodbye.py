#!/usr/bin/env python3
"""
Unit test for the device server leaving the network cleanly when systemd stops it.

At reboot and poweroff systemd sends SIGTERM. The server used to die on it before
unregistering its mDNS service, so the node's zeroconf cache kept the device and
did not notice it come back (2026-10-02). SIGTERM now raises SystemExit, which
runs the server's ``finally`` and sends the mDNS goodbye.
"""

import os
import signal
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))


def test_sigterm_becomes_a_clean_exit():
    import device_server

    with pytest.raises(SystemExit) as stop:
        device_server._exit_on_sigterm(signal.SIGTERM, None)
    assert stop.value.code == 0


def test_the_handler_is_installed_before_the_server_starts():
    import inspect

    import device_server

    source = inspect.getsource(device_server)
    main_block = source[source.index('if __name__ == "__main__"') :]
    installed = main_block.index("signal.signal(signal.SIGTERM, _exit_on_sigterm)")
    assert installed < main_block.index("zc.register_service(serviceInfo)")
