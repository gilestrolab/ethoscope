#!/usr/bin/env python3
"""Plot the FPS x gain x illumination matrix from the ETHOSCOPE_900 bench run."""
import csv

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#9a9892"
# Categorical hues, fixed order, validated for CVD separation.
FPS_COLOUR = {"2": "#2a78d6", "5": "#eb6834", "10": "#1baf7a"}
LIGHT_MARKER = {"IR": "o", "LED": "s"}

rows = [r for r in csv.DictReader(open("matrix.csv")) if r["frame_noise"]]

# The six series land on top of each other - that is the finding - so nudge them
# apart horizontally, otherwise the panel reads as a single series.
DODGE = {("IR", "2"): -0.30, ("IR", "5"): -0.18, ("IR", "10"): -0.06,
         ("LED", "2"): 0.06, ("LED", "5"): 0.18, ("LED", "10"): 0.30}

fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4), facecolor=SURFACE)
fig.subplots_adjust(left=0.06, right=0.995, top=0.80, bottom=0.14, wspace=0.28)

for ax in axes:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color="#e6e5e1", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d8d7d2")
    ax.tick_params(colors=INK2, labelsize=9)

# ---- Panel A: noise vs gain -------------------------------------------------
ax = axes[0]
for light in ("IR", "LED"):
    for fps in ("2", "5", "10"):
        pts = sorted(
            (float(r["gain"]) + DODGE[(light, fps)], float(r["frame_noise"]))
            for r in rows
            if r["light"] == light and r["maxfps"] == fps
        )
        if not pts:
            continue
        ax.plot(
            *zip(*pts),
            marker=LIGHT_MARKER[light],
            color=FPS_COLOUR[fps],
            linewidth=2,
            markersize=8,
            markeredgecolor=SURFACE,
            markeredgewidth=1.5,
            alpha=0.9,
        )
# Fitted relationship (from the same 22 cells).
xs = [1, 10]
ax.plot(xs, [0.523 + 0.0824 * x for x in xs], color=MUTED, linewidth=1.5,
        linestyle=(0, (5, 4)), zorder=0)
ax.text(4.6, 0.60, "noise = 0.523 + 0.0824 x gain\nR² = 0.965 (n = 22)",
        color=INK2, fontsize=9, style="italic")
for g, spread in ((3, "0.6%"), (5, "0.9%"), (7, "1.6%"), (10, "0.8%")):
    vals = [float(r["frame_noise"]) for r in rows if int(float(r["gain"])) == g]
    ax.annotate(spread, (g, max(vals)), textcoords="offset points",
                xytext=(0, 11), ha="center", color=MUTED, fontsize=8.5)
ax.set_xlabel("analogue gain", color=INK2, fontsize=10)
ax.set_ylabel("frame noise (grey levels)", color=INK2, fontsize=10)
ax.set_ylim(0.42, 1.45)   # headroom for the spread annotations
ax.set_title("Noise depends only on gain", color=INK, fontsize=11.5,
             fontweight="bold", loc="left", pad=10)

# ---- Panel B: sharpness vs gain --------------------------------------------
ax = axes[1]
for light in ("IR", "LED"):
    for fps in ("2", "5", "10"):
        pts = sorted(
            (float(r["gain"]) + DODGE[(light, fps)], float(r["sharpness"]))
            for r in rows
            if r["light"] == light and r["maxfps"] == fps
        )
        if not pts:
            continue
        ax.plot(
            *zip(*pts),
            marker=LIGHT_MARKER[light],
            color=FPS_COLOUR[fps],
            linewidth=2,
            markersize=8,
            markeredgecolor=SURFACE,
            markeredgewidth=1.5,
            alpha=0.9,
        )
ax.set_xlabel("analogue gain", color=INK2, fontsize=10)
ax.set_ylabel("sharpness (variance of Laplacian)", color=INK2, fontsize=10)
ax.set_ylim(0, 82)
ax.set_title("So is sharpness", color=INK, fontsize=11.5,
             fontweight="bold", loc="left", pad=10)

# ---- Panel C: the control - frame rate genuinely varied ---------------------
ax = axes[2]
for i, fps in enumerate(("2", "5", "10")):
    vals = [float(r["achieved_fps"]) for r in rows
            if r["maxfps"] == fps and r["achieved_fps"] not in ("", "0.0")]
    if not vals:
        continue
    ax.scatter([i] * len(vals), vals, s=64, color=FPS_COLOUR[fps],
               edgecolor=SURFACE, linewidth=1.5, alpha=0.9, zorder=3)
    ax.plot([i - 0.22, i + 0.22], [sum(vals) / len(vals)] * 2,
            color=FPS_COLOUR[fps], linewidth=2.5, zorder=4)
    ax.text(i, max(vals) + 0.45, f"{min(vals):.1f}–{max(vals):.1f} Hz",
            ha="center", color=INK2, fontsize=9)
ax.set_xticks([0, 1, 2])
ax.set_xticklabels(["cap 2", "cap 5", "cap 10"])
ax.set_ylim(0, 7.6)
ax.set_xlabel("maxfps setting", color=INK2, fontsize=10)
ax.set_ylabel("achieved frame rate (Hz)", color=INK2, fontsize=10)
ax.set_title("...while the frame rate really did vary", color=INK, fontsize=11.5,
             fontweight="bold", loc="left", pad=10)

# ---- Legend -----------------------------------------------------------------
handles = [
    plt.Line2D([], [], color=FPS_COLOUR[f], linewidth=2, marker="o",
               markersize=8, markeredgecolor=SURFACE, label=f"maxfps {f}")
    for f in ("2", "5", "10")
] + [
    plt.Line2D([], [], color=INK2, linewidth=0, marker=LIGHT_MARKER[light],
               markersize=8, markeredgecolor=SURFACE,
               label={"IR": "IR only", "LED": "LED 100%"}[light])
    for light in ("IR", "LED")
]
fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.06, 0.965),
           ncol=5, frameon=False, fontsize=9.5, labelcolor=INK2,
           handletextpad=0.5, columnspacing=1.6)

fig.text(0.06, 0.995, "ETHOSCOPE_900 · Pi 3 · imx219 NoIR · dark bench, fan on · 22 of 30 cells",
         color=MUTED, fontsize=9, va="top")

fig.savefig("matrix_plot.png", dpi=170, facecolor=SURFACE)
print("wrote matrix_plot.png")
