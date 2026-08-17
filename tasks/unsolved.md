# Unsolved / deferred

Open items found during the #222 bench session (2026-08-12). Everything here is
known-broken or unverified, not forgotten.

## Testing infrastructure

- [ ] **The device server has no test coverage at all.** `device_server.py` and
      `device_listener.py` cannot be imported off a Pi (`netifaces`,
      `ethoclient`, `picamera2`), so the API surface the node drives is
      untested. Two fixes tonight (`c2e593a4` settings accumulation, the
      `test_module` result) went in unverified by tests. Stubbing three imports
      in a conftest would unblock it.
- [ ] **Check whether CI was reporting success on zero collected device tests.**
      Collection has been broken since the repo reorganisation (fixed in
      `900ecd53`), so any device test written since then has never run.
- [ ] Three tests assert `CV_VERSION in [2, 3, 4]` and fail on OpenCV 5
      (`test_img_roi_builder`, `test_target_roi_builder` x2). The project pins
      `opencv-python<5`, so they pass where that holds. Pairs with the deferred
      OpenCV 5 migration already in `todo.md`.
- [ ] `test_light_daemon.py::TestRampWalker::test_ramp_down_visits_intermediate_values`
      fails on this branch; already fixed on dev by `8d4f18e1`, resolves on merge.

## Device / infrastructure

- [ ] **Devices cannot self-update on this network.** `origin` is
      `git://node.local/ethoscope.git`, which does not resolve from a device and
      whose git daemon port is closed. If fleet-wide, `ethoscope_update.service`
      is doing nothing for anyone. Verify against a production unit.
- [ ] **Grabber-side `logging.info` never reaches the journal** - the live gain
      change was verified by its effect, not its log line. Any future
      grabber-side diagnostic will be invisible too.
- [ ] pigpio has no daemon package from Debian Trixie onwards and never
      supported the Pi 5. Resolved for now by building the new image on
      Bookworm; revisit if the fleet moves to Trixie or Pi 5, where the LED
      would need to move to a hardware-PWM GPIO (12/13/18/19).
- [ ] `DIAGNOSTICS` has no schema migration. Two columns were added tonight and
      older databases would reject the insert. Only the bench device is
      affected now, but a migration is needed once the table ships.

## Measurement, still open

- [ ] **Jitter needs flies.** With an empty arena only a handful of ROIs report,
      and they track dust and reflections. Every jitter number so far is
      indicative at best.
- [ ] **Sharpness cannot separate focus from contrast.** Both raise
      high-frequency content. Needs a defocus test at fixed illumination before
      the metric is used for attribution.
- [ ] **Retroactive noise from archived snapshots is unproven.** `IMG_SNAPSHOTS`
      is JPEG quality 50, which attenuates the estimate badly at low sigma in
      synthetic tests, though real archived frames did vary systematically
      (0.164-0.239, highest in the dark phase). Needs calibration against
      `frame_noise` on runs long enough to capture a snapshot (>5 min).
- [ ] **The decimation study** - one recording scored at several sampling rates -
      remains the decisive test of the FPS/sleep effect and has not been run.

## Bench device (ETHOSCOPE_900) cleanup, before it is imaged or returned

- [ ] pigpio built from source in `/usr/local` (`make uninstall` in `/tmp/pigpio`)
- [ ] `github` remote added to `/opt/ethoscope` (origin left untouched)
- [ ] systemd drop-in `/etc/systemd/system/ethoscope_listener.service.d/diagnostics.conf`
      forcing a 5 s diagnostics interval
- [ ] scratch scripts in `/home/ethoscope/`: `pwm_light.py`, `hold_light.py`
