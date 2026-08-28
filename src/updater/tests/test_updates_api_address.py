"""
Tests for the address handling in helpers.updates_api_wrapper.

The wrapper used to read its target with ``urlparse(ip).hostname``, which only
fills ``hostname`` in when the string carries a scheme. Every internal caller
happens to pass a full URL, so the gap went unnoticed until a bare address was
handed in from outside: it parsed to ``None``, the request went to the literal
host "None", and the failure came back as "Name or service not known" -- a
network error for what was really a formatting mismatch.

These tests pin that any reasonable spelling of an address reaches the same
device, and that an empty one is refused with a message that names the cause.
"""

import os
import sys
from unittest import mock

import pytest

# The updater package is a standalone script directory (no installable package), so make it
# importable directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers  # noqa: E402


class TestHostnameOf:
    @pytest.mark.parametrize(
        "address",
        [
            "192.168.1.22",
            "192.168.1.22:9000",
            "http://192.168.1.22",
            "http://192.168.1.22:9000",
            "http://192.168.1.22:9000/device/data",
            "//192.168.1.22",
            "  192.168.1.22  ",
        ],
    )
    def test_every_spelling_gives_the_same_host(self, address):
        assert helpers.hostname_of(address) == "192.168.1.22"

    @pytest.mark.parametrize("address", ["node", "http://node:8888"])
    def test_names_work_as_well_as_addresses(self, address):
        assert helpers.hostname_of(address) == "node"

    @pytest.mark.parametrize("address", ["", "   ", None])
    def test_an_empty_address_is_refused(self, address):
        """Better than quietly requesting http://None:8888/."""
        with pytest.raises(ValueError):
            helpers.hostname_of(address)


class TestUpdatesApiWrapperTarget:
    @pytest.fixture
    def urlopen(self):
        with mock.patch.object(helpers.urllib.request, "urlopen") as opened:
            opened.return_value.read.return_value = b'{"status": "ok"}'
            yield opened

    @pytest.mark.parametrize(
        "ip", ["192.168.1.22", "http://192.168.1.22", "http://192.168.1.22:9000"]
    )
    def test_a_bare_address_reaches_the_device(self, urlopen, ip):
        """Regression: this used to build http://None:8888/... for a bare address."""
        response = helpers.updates_api_wrapper(
            ip, "id-aaa", what="device/restart_daemon"
        )

        request = urlopen.call_args[0][0]
        assert (
            request.full_url == "http://192.168.1.22:8888/device/restart_daemon/id-aaa"
        )
        assert response == {"status": "ok"}

    def test_the_port_is_the_updater_port_not_the_one_in_the_address(self, urlopen):
        """The address may name the device web server; the updater lives elsewhere."""
        helpers.updates_api_wrapper("http://192.168.1.22:9000", "id-aaa")

        request = urlopen.call_args[0][0]
        assert request.full_url == "http://192.168.1.22:8888/check_update/id-aaa"
