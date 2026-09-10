"""
Regression guard for the option-argument binding in the device forms.

`ethoscopeFormService.updateUserOptions()` re-seeds the arguments of an option
group when the user picks a different class. The tracking and recording modals
hand that arguments object to the shared option-argument partial once, with
ng-init, so the widgets keep writing to whatever object was current when they
were rendered. Replacing the object rather than re-seeding it in place left the
widgets writing to an orphan while the payload carried the freshly seeded
defaults: picking TargetGridROIBuilder and typing a 2x8 grid started the device
with n_rows=1, n_cols=1, i.e. a single ROI covering the whole arena.

There is no JS test runner in this repo, so the service file is driven directly
through node with a minimal Angular stub.
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

// As served by the device: FileBasedROIBuilder first, so it is the one the form
// seeds and renders before the user picks the grid builder.
const user_options = { tracking: { roi_builder: [
  { name: 'FileBasedROIBuilder',
    arguments: [{name: 'template_name', type: 'str', default: ''}] },
  { name: 'TargetGridROIBuilder', arguments: [
      {name: 'n_cols', type: 'number', default: 1},
      {name: 'n_rows', type: 'number', default: 1},
      {name: 'horizontal_fill', type: 'number', default: 0.9},
      {name: 'vertical_fill', type: 'number', default: 0.9},
  ]},
]}};

const $scope = { user_options, selected_options: {}, $apply: () => {} };
svc.initializeSelectedOptions('tracking', user_options.tracking, $scope);

// What ng-init captures: the arguments object that exists in the digest right
// after the radio click, before the deferred re-seed runs.
const argModel = $scope.selected_options.tracking.roi_builder.arguments;

svc.updateUserOptions('tracking', 'roi_builder', 'TargetGridROIBuilder', $scope);

setTimeout(() => {
  argModel.n_cols = 2;
  argModel.n_rows = 8;
  argModel.horizontal_fill = 0.9;
  argModel.vertical_fill = 0.7;
  console.log(JSON.stringify($scope.selected_options.tracking.roi_builder));
}, 20);
"""


@pytest.fixture(scope="module")
def submitted_roi_builder(tmp_path_factory):
    """
    Run the form service in node and return the roi_builder payload the modal
    would POST to /controls/start.

    Returns:
        dict: The `roi_builder` option group, name and arguments.
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


def test_selected_class_is_submitted(submitted_roi_builder):
    """The class the user picked is the one sent to the device."""
    assert submitted_roi_builder["name"] == "TargetGridROIBuilder"


def test_typed_grid_reaches_the_device(submitted_roi_builder):
    """Values typed into the widgets are the ones submitted, not the defaults."""
    args = submitted_roi_builder["arguments"]
    assert (args["n_cols"], args["n_rows"]) == (2, 8)
    assert (args["horizontal_fill"], args["vertical_fill"]) == (0.9, 0.7)


def test_stale_template_argument_is_dropped(submitted_roi_builder):
    """
    Switching class clears the previous class's arguments, so the device is not
    handed a template_name that TargetGridROIBuilder cannot accept.
    """
    assert "template_name" not in submitted_roi_builder["arguments"]
