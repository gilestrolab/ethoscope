import os
from pathlib import Path

# Get absolute path to video file relative to this module
_TEST_DIR = Path(__file__).parent.parent / "static_files" / "videos"
VIDEO = str(_TEST_DIR / "arena_10x2_sortTubes.mp4")
DRAW_FRAMES = True
