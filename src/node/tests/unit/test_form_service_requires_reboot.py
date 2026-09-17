"""
What the machine-settings dialog's submit button promises.

The button reads "Update and Reboot" and reboots the device when the pending
edit needs one, and plain "Update" otherwise, so the label has to be derived
from the same payload that is about to be submitted. Two kinds of argument are
marked requires_reboot and they do not answer the same question:

* a *state* (the ethoscope number, remote logging, the static-IP flag) is only
  pending once the user has moved it away from what the device reported, or
  every visit to the dialog would offer to reboot a device nothing was done to;
* an *action* (expand_rootfs, flagged is_action by the device) is pending
  whenever it is on, because its default is a recommendation - on for a device
  still called ETHOSCOPE_000 - and not a state the device already holds.

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

// The machine options as an ethoscope serves them, for a device that is already
// numbered and already logging remotely.
const options = { machine_options: [{
  name: 'Ethoscope Options',
  arguments: [
    {type: 'number', name: 'etho_number', default: 107, requires_reboot: true},
    {type: 'boolean', name: 'has_light_hardware', default: false,
     requires_reboot: false},
    {type: 'boolean', name: 'remoteLogging', default: true, requires_reboot: true},
    {type: 'boolean', name: 'expand_rootfs', default: false, requires_reboot: true,
     is_action: true},
  ],
}]};

const $scope = { user_options: { update_machine: options }, selected_options: {} };
svc.initializeSelectedOptions('update_machine', options, $scope);
const pending = $scope.selected_options.update_machine;
const args = pending.machine_options.arguments;

const answers = {};
answers.untouched = svc.requiresReboot(options, pending);

args.has_light_hardware = true;
answers.state_not_needing_a_reboot = svc.requiresReboot(options, pending);
args.has_light_hardware = false;

args.etho_number = 108;
answers.renamed = svc.requiresReboot(options, pending);
args.etho_number = 107;

args.remoteLogging = false;
answers.state_turned_off = svc.requiresReboot(options, pending);
args.remoteLogging = true;

args.expand_rootfs = true;
answers.action_turned_on = svc.requiresReboot(options, pending);

// The clock auto-correct posts its own payload, naming an option group that is
// not one of the served ones.
answers.clock_autocorrect = svc.requiresReboot(
  options, {machine_options: {name: 'datetime', arguments: {datetime: 1e9}}});

console.log(JSON.stringify(answers));
"""


@pytest.fixture(scope="module")
def answers(tmp_path_factory):
    """
    Run the form service in node and return requiresReboot()'s verdict for each
    way of filling the machine-settings form.

    Returns:
        dict: Case name -> bool.
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


def test_an_untouched_form_does_not_offer_to_reboot(answers):
    """Opening the dialog on a settled device must leave the button as Update."""
    assert answers["untouched"] is False


def test_a_setting_that_takes_effect_at_once_does_not_offer_to_reboot(answers):
    """has_light_hardware is applied live: changing it is not a reboot."""
    assert answers["state_not_needing_a_reboot"] is False


def test_renaming_the_device_offers_to_reboot(answers):
    """etho_number only takes effect on the next boot."""
    assert answers["renamed"] is True


def test_turning_a_state_off_offers_to_reboot(answers):
    """A reboot-needing state is pending in either direction, not just when on."""
    assert answers["state_turned_off"] is True


def test_an_action_offers_to_reboot_whenever_it_is_on(answers):
    """expand_rootfs runs on submit, so being on is enough - default or not."""
    assert answers["action_turned_on"] is True


def test_the_clock_autocorrect_never_offers_to_reboot(answers):
    """
    The drift correction posts {datetime: ...} on its own, without the form: it
    must not inherit a reboot from whatever the dialog happens to be showing.
    """
    assert answers["clock_autocorrect"] is False
