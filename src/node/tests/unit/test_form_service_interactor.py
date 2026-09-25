"""
Regression guard: a run started without stimulators must not stimulate.

The device hides DefaultStimulator from /user_options (41c1975a), so the first
interactor it serves is ComposedStimulator. `initializeSelectedOptions()` seeded
every option group with its first class, and the interactor section of the
start modal has no widget for that seed - only the "Add Stimulator" sequence.
With an empty sequence the controller kept the seeded class, so every run
started without a stimulator was sent ComposedStimulator with its defaults
(inactivity-triggered motor pulses on every module channel). From April 2026
nearly every recording on the lab node carries it.

There is no JS test runner in this repo, so the service file is driven directly
through node with a minimal Angular stub (as in test_form_service_arguments.py).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC_JS = (
    Path(__file__).resolve().parents[2]
    / "static"
    / "js"
    / "controllers"
    / "ethoscopeFormService.js"
)

HARNESS = """
const fs = require('fs');
let factoryFn = null;
global.angular = {
  module: () => ({ factory: (n, fn) => { factoryFn = fn; } }),
  extend: Object.assign,
};
global.moment = undefined;
eval(fs.readFileSync(%(service)s, 'utf8'));
const svc = factoryFn(() => {}, (fn) => setTimeout(fn, 0));

// As served by a Pi: DefaultStimulator is hidden, so ComposedStimulator is first.
const user_options = { tracking: {
  interactor: [
    { name: 'ComposedStimulator', arguments: [
        {name: 'trigger_type', type: 'select', default: 'inactivity'},
        {name: 'action_type', type: 'select', default: 'motor_pulse'},
    ]},
    { name: 'SleepDepStimulator', arguments: [] },
  ],
  roi_builder: [
    { name: 'FileBasedROIBuilder',
      arguments: [{name: 'template_name', type: 'str', default: ''}] },
  ],
}};

const $scope = { user_options, selected_options: {}, stimulatorSequence: [],
                 $apply: () => {} };
svc.initializeSelectedOptions('tracking', user_options.tracking, $scope);
const seeded = JSON.parse(JSON.stringify($scope.selected_options.tracking));

svc.addStimulatorToSequence($scope);
console.log(JSON.stringify({ seeded: seeded, sequence: $scope.stimulatorSequence }));
"""


@pytest.fixture(scope="module")
def form_state(tmp_path_factory):
    """
    Run the form service in node and return what it seeds and what
    "Add Stimulator" produces.

    Returns:
        dict: 'seeded' (selected_options.tracking right after initialisation)
            and 'sequence' (the stimulator sequence after one Add Stimulator).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    harness = tmp_path_factory.mktemp("formservice") / "harness.js"
    harness.write_text(HARNESS % {"service": json.dumps(str(STATIC_JS))})

    out = subprocess.run(
        [node, str(harness)], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_interactor_is_not_seeded(form_state):
    """Opening the form does not pre-select a stimulator the user cannot see."""
    assert "interactor" not in form_state["seeded"]


def test_other_groups_are_still_seeded(form_state):
    """Only the interactor is exempt; ordinary option groups keep their default."""
    assert form_state["seeded"]["roi_builder"]["name"] == "FileBasedROIBuilder"


def test_add_stimulator_still_uses_composed_defaults(form_state):
    """Choosing to stimulate still starts from ComposedStimulator's defaults."""
    (stim,) = form_state["sequence"]
    assert stim["name"] == "ComposedStimulator"
    assert stim["arguments"]["trigger_type"] == "inactivity"
