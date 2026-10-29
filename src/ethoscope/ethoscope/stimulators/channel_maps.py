"""
ROI-to-channel maps for the multimodule (motors, valves, LEDs).

The module board drives 20 channels. Odd channels are the motor connectors
(channel 2k-1 is Mk), even channels the valve/LED connectors (channel 2k-2 is
Vk); connectors 1-5 face one side of the arena, 6-10 the other. Which tube a
connector serves depends on the arena, so a map is picked by what is driven
(motor, valve, LED), by how many LEDs the module reports, and by the number of
ROIs. The maps are those of the legacy classes written for each layout.

20-tube arena (two columns of ten, ROIs 1-10 and 11-20):

- motors: ROIs 1,3,5,7,9,12,14,16,18,20 -> 1,3,...,19 (mAGO,
  OptomotorSleepDepriver)
- LEDs, 10-LED module: the same ROIs -> 0,2,...,18 (OptomotorSleepDepriver)
- LEDs, 20-LED module: ROI n -> n-1 (MODULE 4)
- valves: ROIs 1,3,5,...,19 -> 0,2,...,18 (mAGO)

10-tube arena (one column of ten long tubes): odd ROIs are served from
connectors 1-5, even ROIs from connectors 6-10.

- valves and LEDs: ROI 1->0, 2->10, 3->2, 4->12, ..., 10->18 (AGO,
  OptoSleepDepriver)
- motors: ROI 1->1, 2->11, 3->3, 4->13, ..., 10->19. No legacy class drove
  motors on this arena; each ROI gets the motor beside its valve/LED connector.
"""

# Arenas with up to this many ROIs use the 10-tube layout.
TEN_TUBE_ARENA_ROIS = 10

# --- 20-tube arena ---
_MOTORS_20_TUBES = {
    1: 1,
    3: 3,
    5: 5,
    7: 7,
    9: 9,
    12: 11,
    14: 13,
    16: 15,
    18: 17,
    20: 19,
}

_LEDS_10_OF_20_TUBES = {
    1: 0,
    3: 2,
    5: 4,
    7: 6,
    9: 8,
    12: 10,
    14: 12,
    16: 14,
    18: 16,
    20: 18,
}

_LEDS_20_OF_20_TUBES = {i: i - 1 for i in range(1, 21)}

_VALVES_20_TUBES = {
    1: 0,
    3: 2,
    5: 4,
    7: 6,
    9: 8,
    11: 10,
    13: 12,
    15: 14,
    17: 16,
    19: 18,
}

# --- 10-tube arena ---
_EVEN_10_TUBES = {
    1: 0,
    2: 10,
    3: 2,
    4: 12,
    5: 4,
    6: 14,
    7: 6,
    8: 16,
    9: 8,
    10: 18,
}

_MOTORS_10_TUBES = {roi: channel + 1 for roi, channel in _EVEN_10_TUBES.items()}


def get_channel_map(channel_type, led_count=None, n_rois=None):
    """
    Return the ROI-to-channel mapping for a stimulus type, module and arena.

    Args:
        channel_type (str): One of "motor", "led", "valve".
        led_count (int, optional): Number of LEDs the module reports. More than
            10 (MODULE 4) drives one LED per ROI on a 20-tube arena.
        n_rois (int, optional): Number of ROIs of the arena. Up to 10 selects
            the 10-tube layout; more, or None (not known), the 20-tube layout.

    Returns:
        dict: Mapping of ROI index to hardware channel number.

    Raises:
        ValueError: If channel_type is not recognized.
    """
    ten_tubes = n_rois is not None and n_rois <= TEN_TUBE_ARENA_ROIS

    if channel_type == "motor":
        cmap = _MOTORS_10_TUBES if ten_tubes else _MOTORS_20_TUBES
    elif channel_type == "led":
        if ten_tubes:
            cmap = _EVEN_10_TUBES
        elif isinstance(led_count, (int, float)) and led_count > 10:
            cmap = _LEDS_20_OF_20_TUBES
        else:
            cmap = _LEDS_10_OF_20_TUBES
    elif channel_type == "valve":
        cmap = _EVEN_10_TUBES if ten_tubes else _VALVES_20_TUBES
    else:
        raise ValueError(
            f"Unknown channel_type: {channel_type!r}. "
            f"Must be 'motor', 'led', or 'valve'"
        )
    return dict(cmap)
