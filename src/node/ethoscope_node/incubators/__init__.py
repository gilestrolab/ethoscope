"""Self-contained smart-incubator control subsystem.

The default ethoscope-node install pulls the full stack and this subpackage
runs inside it via the bridge in ``ethoscope_node.api.incubator_api``. The
subpackage is *also* structured so a stripped-down venv can run just the
standalone ``ethoscope-incubator-server`` console script — useful for the
occasional lab with only incubators and no ethoscopes. Recipe (see
``pyproject.toml``):

    python -m venv inc-venv
    inc-venv/bin/pip install --no-deps -e src/node
    inc-venv/bin/pip install bottle zeroconf requests
    inc-venv/bin/ethoscope-incubator-server --port 8090

Hard constraint that makes the above work: no module under this package may
import from ``ethoscope_node.*`` outside this subpackage. Small slices of
upstream code (e.g. the device scanner base classes) are duplicated here
rather than imported, mirroring the policy in
``ethoscope_node/utils/video_helpers.py``.
"""

from ethoscope_node.incubators.firmware_client import (
    IncubatorFirmwareClient,
    IncubatorHTTPError,
)
from ethoscope_node.incubators.reconciler import Reconciler
from ethoscope_node.incubators.scanner import (
    Incubator,
    IncubatorScanner,
    ScanException,
)
from ethoscope_node.incubators.schedule import (
    SCHEDULE_FIELDS,
    build_firmware_payload,
    is_light_on,
    schedule_drifted,
)
from ethoscope_node.incubators.storage import (
    IncubatorRecord,
    IncubatorStorage,
    SQLiteIncubatorStorage,
)

__all__ = [
    "Incubator",
    "IncubatorFirmwareClient",
    "IncubatorHTTPError",
    "IncubatorRecord",
    "IncubatorScanner",
    "IncubatorStorage",
    "Reconciler",
    "SCHEDULE_FIELDS",
    "SQLiteIncubatorStorage",
    "ScanException",
    "build_firmware_payload",
    "is_light_on",
    "schedule_drifted",
]
