"""The device's copy of the preprocessing must stay identical to the training code.

``src/ethoscope/ethoscope/trackers/deep_tube/preprocess.py`` duplicates
``dl_tracking/preprocess.py`` because the device package cannot depend on this
directory. A change to either that is not made to both would make the network see
different canvases on a device than in training, so this test compares them. The
device file is loaded by path: the training environment need not have the ethoscope
package installed.
"""

import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pytest

from dl_tracking import preprocess as train

DEVICE_FILE = (
    Path(__file__).resolve().parents[2]
    / "src/ethoscope/ethoscope/trackers/deep_tube/preprocess.py"
)


@pytest.fixture(scope="module")
def device():
    spec = importlib.util.spec_from_file_location("device_preprocess", DEVICE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def functions(module):
    return {
        name: obj
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) and obj.__module__ == module.__name__
    }


def test_the_same_functions_with_the_same_code(device):
    ours, theirs = functions(train), functions(device)
    assert sorted(ours) == sorted(theirs)
    for name in ours:
        assert inspect.getsource(ours[name]) == inspect.getsource(theirs[name]), name


def test_the_same_constants(device):
    for name in ("CANVAS_H", "CANVAS_W", "STRIDE", "BLEND_LOGITS"):
        assert getattr(device, name) == getattr(train, name), name
    assert np.array_equal(device._NEIGHBOUR_DI, train._NEIGHBOUR_DI)
    assert np.array_equal(device._NEIGHBOUR_DJ, train._NEIGHBOUR_DJ)


def test_the_same_outputs(device):
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, (960, 1280), dtype=np.uint8)
    rects = [(int(x), int(y), 560, 60) for x, y in rng.integers(0, 700, (20, 2))]
    origins = [train.canvas_origin(*r) for r in rects]
    assert origins == [device.canvas_origin(*r) for r in rects]
    canvases = train.canvases_from_frame(frame, origins)
    assert np.array_equal(canvases, device.canvases_from_frame(frame, origins))
    assert np.array_equal(train.normalise(canvases), device.normalise(canvases))
    maps = rng.normal(size=(20, 7, 8, 72)).astype(np.float32)
    presence = rng.normal(size=(20, 1)).astype(np.float32)
    assert np.array_equal(train.decode(maps, presence), device.decode(maps, presence))
