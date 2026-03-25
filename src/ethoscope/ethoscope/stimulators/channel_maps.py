"""
Centralized ROI-to-channel mappings for mAGO-based hardware modules.

All mAGO firmware modules share the same serial protocol but use different
channel layouts depending on module type and connected hardware. This module
consolidates the scattered channel maps from individual stimulator classes.

Channel layout reference:
- Odd channels (1,3,5,...,19): Motors
- Even channels (0,2,4,...,18): LEDs or Valves
- 10-ROI layout: ROIs {1,3,5,7,9,12,14,16,18,20}
- 20-ROI interleaved: ROIs {1-10} mapped across all 20 channels
"""

# 10-ROI layout: motors on odd channels
_MOTORS_ODD_10ROI = {
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

# 10-ROI layout: LEDs/valves on even channels
_EVEN_10ROI = {
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

# 10-ROI layout: valves on even channels (mAGO uses different ROI numbering for valves)
_VALVES_MAGO_10ROI = {
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

# 10-ROI interleaved across 20 channels (AGO/OptoSleepDepriver layout)
_INTERLEAVED_20CH = {
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


def get_channel_map(channel_type):
    """
    Return ROI-to-channel mapping for the given channel type.

    The channel type determines the physical layout based on what hardware
    component is being addressed. All modern mAGO modules use one of these
    standard layouts.

    Args:
        channel_type (str): One of "motor", "led", "valve"

    Returns:
        dict: Mapping of ROI index to hardware channel number

    Raises:
        ValueError: If channel_type is not recognized
    """
    if channel_type == "motor":
        return dict(_MOTORS_ODD_10ROI)
    elif channel_type == "led":
        return dict(_EVEN_10ROI)
    elif channel_type == "valve":
        return dict(_VALVES_MAGO_10ROI)
    else:
        raise ValueError(
            f"Unknown channel_type: {channel_type!r}. "
            f"Must be 'motor', 'led', or 'valve'"
        )
