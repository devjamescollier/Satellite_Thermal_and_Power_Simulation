"""Plot a simulator CSV run to sanity-check the physics.

Usage: uv run python ground/plot_run.py run.csv [--save out.png]
"""

import argparse

import matplotlib.pyplot as plt
import numpy as np


def load_run(path):
    return np.genfromtxt(path, delimiter=",", names=True)


def shade_eclipses(ax, t_h, eclipse):
    """Grey bands wherever the spacecraft is in Earth's shadow."""
    ax.fill_between(
        t_h, 0, 1, where=eclipse > 0, color="0.85", transform=ax.get_xaxis_transform(), linewidth=0
    )


def plot_run(run):
    t_h = run["time_s"] / 3600.0
    temp_cols = [n for n in run.dtype.names if n.startswith("T_")]
    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(10, 10))

    for col in temp_cols:
        axes[0].plot(t_h, run[col] - 273.15, label=col[2:-2])
    axes[0].set_ylabel("Temperature [°C]")
    axes[0].legend(loc="upper right", ncol=len(temp_cols), fontsize="small")

    axes[1].plot(t_h, run["soc"] * 100.0)
    axes[1].set_ylabel("SOC [%]")

    axes[2].plot(t_h, run["battery_V"], color="C2")
    axes[2].set_ylabel("Battery [V]")
    current_ax = axes[2].twinx()
    current_ax.plot(t_h, run["battery_A"], color="C3")
    current_ax.set_ylabel("Battery [A] (+ charging)")

    axes[3].plot(t_h, run["solar_W"], color="C1")
    axes[3].set_ylabel("Solar power [W]")
    axes[3].set_xlabel("Time [h]")

    for ax in axes:
        shade_eclipses(ax, t_h, run["eclipse"])
        ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", help="CSV written by the simulator")
    parser.add_argument("--save", help="write the figure to this file instead of showing it")
    args = parser.parse_args()

    fig = plot_run(load_run(args.csv))
    if args.save:
        fig.savefig(args.save, dpi=120)
    else:
        plt.show()


if __name__ == "__main__":
    main()
