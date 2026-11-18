"""
Unit tests for the conflicts between the rsync backup services.

All three run rsync_backup_tool.py, which serves its status on port 8093, so no two
can run together. Video and sqlite used to conflict only with unified: run side by
side, the second could not bind the port and exited, and systemd restarted it every
5 s (14,160 times on one node by 2026-11-12).
"""

import configparser
import itertools
from pathlib import Path

import pytest

from ethoscope_node.api.node_api import SYSTEM_DAEMONS

SERVICES_DIR = Path(__file__).resolve().parents[5] / "services"
RSYNC_UNITS = [
    "ethoscope_backup_unified",
    "ethoscope_backup_sqlite",
    "ethoscope_backup_video",
]


def unit_conflicts(name: str) -> set[str]:
    """The units a service file names in Conflicts=, without the .service suffix."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read(SERVICES_DIR / f"{name}.service")
    value = parser.get("Unit", "Conflicts", fallback="")
    return {unit.removesuffix(".service") for unit in value.split()}


def test_the_service_files_are_where_the_test_looks():
    for name in RSYNC_UNITS:
        assert (SERVICES_DIR / f"{name}.service").is_file()


@pytest.mark.parametrize("a,b", itertools.permutations(RSYNC_UNITS, 2))
def test_each_rsync_unit_conflicts_with_the_others(a, b):
    assert b in unit_conflicts(a)


@pytest.mark.parametrize("name", RSYNC_UNITS)
def test_the_web_ui_stops_the_same_units_the_unit_file_does(name):
    assert set(SYSTEM_DAEMONS[name]["conflicts_with"]) == unit_conflicts(name)


def test_the_mysql_backup_is_not_described_as_the_node_server():
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read(SERVICES_DIR / "ethoscope_backup_mysql.service")
    assert "backup" in parser.get("Unit", "Description").lower()
