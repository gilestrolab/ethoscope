import os
from pathlib import Path

# Get absolute path to video file relative to this module
_TEST_DIR = Path(__file__).parent.parent / "static_files" / "videos"
VIDEO = str(_TEST_DIR / "arena_10x2_sortTubes.mp4")

# Disable frame drawing in CI environments (no display available)
# GitHub Actions sets CI=true, most CI systems have DISPLAY unset
DRAW_FRAMES = not os.getenv("CI") and os.getenv("DISPLAY") is not None
