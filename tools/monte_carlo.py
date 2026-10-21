"""Monte Carlo validation of the FSW battery EKF.

Runs tools/mc_run (sim + FSW in one process) for many seeds in parallel. Each seed
draws its own sensor noise and an initial SOC error in +-15%. Writes PNGs and a
results README to docs/results/, and each run's wall time, CPU time and peak memory
to InfluxDB (Compute Usage dashboard; skipped with --no-influx).

Usage: uv run python tools/monte_carlo.py [--runs 50] [--orbits 10] [--no-influx]
"""

import argparse
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import jobs  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "results"
PERIOD_S = 5668.1  # orbit period at 500 km, for the x axes
STATE_DIM = 3

BLUE, INK, INK_2, SURFACE, BAND = "#2a78d6", "#0b0b0b", "#52514e", "#fcfcfb", "#d9d8d3"


def chi2_quantile(p, dof):
    """Wilson-Hilferty approximation (accurate to ~0.1% for dof >= 30)."""
    z = {0.025: -1.959964, 0.975: 1.959964}[p]
    return dof * (1 - 2 / (9 * dof) + z * np.sqrt(2 / (9 * dof))) ** 3


def run_seeds(binary, runs, orbits, workdir, write_influx):
    paths = {f"seed_{seed:02d}": workdir / f"seed_{seed}.csv" for seed in range(1, runs + 1)}
    cmds = {job: [str(binary), "--seed", job.split("_")[1], "--orbits", str(orbits),
                  "--out", str(path)] for job, path in paths.items()}
    jobs.record("monte_carlo", jobs.run_all(cmds, timeout_s=600), write_influx)
    results = [np.genfromtxt(path, delimiter=",", names=True) for path in paths.values()]
    n = min(len(r) for r in results)
    return {name: np.stack([r[name][:n] for r in results]) for name in results[0].dtype.names}


def prediction_errors(d):
    """Error of every eclipse-exit SOC prediction vs the true SOC at that exit."""
    times, errors = [], []
    for run in range(d["eclipse"].shape[0]):
        eclipse, pred, soc = d["eclipse"][run], d["predicted_soc_exit"][run], d["soc_true"][run]
        exits = np.flatnonzero((eclipse[:-1] == 1) & (eclipse[1:] == 0)) + 1
        entries = np.flatnonzero((eclipse[:-1] == 0) & (eclipse[1:] == 1)) + 1
        for exit_idx in exits:
            start = entries[entries < exit_idx].max(initial=-1)
            if start < 0:
                continue
            window = np.arange(start, exit_idx)
            ok = np.isfinite(pred[window])
            times.append(window[ok] - start)
            errors.append(pred[window][ok] - soc[exit_idx])
    return np.concatenate(times), np.concatenate(errors)


def style(ax, title, ylabel):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.tick_params(colors=INK_2)
    ax.grid(color=BAND, linewidth=0.6)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def plot_consistency(t_orb, mean, lo, hi, title, ylabel, path):
    fig, ax = plt.subplots(figsize=(9, 3.6), facecolor=SURFACE)
    ax.axhspan(lo, hi, color=BAND, alpha=0.7, linewidth=0, label="95% bounds")
    ax.plot(t_orb, mean, color=BLUE, linewidth=1, label="mean over runs")
    ax.set_yscale("log")
    ax.set_xlabel("Time [orbits]", color=INK_2)
    style(ax, title, ylabel)
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_soc_error(t_orb, d, path):
    err = 100 * (d["soc_est"] - d["soc_true"])
    envelope = 300 * d["soc_sigma"].mean(axis=0)
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, facecolor=SURFACE)
    for ax, ylim, title in (
        (axes[0], None, "SOC error, all runs"),
        (axes[1], (-1, 1), "SOC error, zoomed to ±1%"),
    ):
        ax.fill_between(t_orb, -envelope, envelope, color=BAND, linewidth=0, label="±3σ (mean P)")
        for run in err:
            ax.plot(t_orb, run, color=BLUE, linewidth=0.4, alpha=0.35)
        ax.plot([], [], color=BLUE, linewidth=1, label="estimate − truth, one line per run")
        if ylim:
            ax.set_ylim(*ylim)
        style(ax, title, "SOC error [%]")
    axes[0].legend(frameon=False, loc="upper right")
    axes[1].set_xlabel("Time [orbits]", color=INK_2)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_prediction(times_s, errors, path):
    minutes = times_s / 60
    bins = np.arange(0, minutes.max() + 1, 1.0)
    idx = np.digitize(minutes, bins) - 1
    centers = bins[:-1] + 0.5
    pct = 100 * errors
    stats = [pct[idx == i] for i in range(len(centers))]
    keep = [i for i, s in enumerate(stats) if len(s)]
    mean = np.array([stats[i].mean() for i in keep])
    p5 = np.array([np.percentile(stats[i], 5) for i in keep])
    p95 = np.array([np.percentile(stats[i], 95) for i in keep])

    fig, ax = plt.subplots(figsize=(9, 3.6), facecolor=SURFACE)
    ax.fill_between(centers[keep], p5, p95, color=BAND, linewidth=0, label="5–95% of predictions")
    ax.plot(centers[keep], mean, color=BLUE, linewidth=2, label="mean error")
    ax.axhline(0, color=INK_2, linewidth=0.8)
    ax.set_xlabel("Time since eclipse entry [min]", color=INK_2)
    style(ax, "Eclipse-exit SOC prediction error (predicted − true at exit)", "Error [% SOC]")
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--orbits", type=float, default=10)
    parser.add_argument("--bin", type=Path, default=ROOT / "build" / "tools" / "mc_run")
    parser.add_argument("--no-influx", action="store_true", help="don't write compute usage")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        d = run_seeds(args.bin, args.runs, args.orbits, Path(tmp), not args.no_influx)
    runs = args.runs
    t_orb = d["time_s"][0] / PERIOD_S
    after_first = t_orb >= 1.0

    nees_mean = d["nees"].mean(axis=0)
    nees_lo, nees_hi = (chi2_quantile(p, STATE_DIM * runs) / runs for p in (0.025, 0.975))
    nis_mean = d["nis"].mean(axis=0)
    nis_lo, nis_hi = (chi2_quantile(p, runs) / runs for p in (0.025, 0.975))
    nees_in = 100 * np.mean((nees_mean >= nees_lo) & (nees_mean <= nees_hi))
    nees_in_after = 100 * np.mean(
        (nees_mean[after_first] >= nees_lo) & (nees_mean[after_first] <= nees_hi)
    )
    nis_in = 100 * np.mean((nis_mean >= nis_lo) & (nis_mean <= nis_hi))
    soc_err = d["soc_est"] - d["soc_true"]
    rms_all = 100 * np.sqrt(np.mean(soc_err**2))
    rms_after = 100 * np.sqrt(np.mean(soc_err[:, after_first] ** 2))
    max_after = 100 * np.abs(soc_err[:, after_first]).max()
    pred_t, pred_err = prediction_errors(d)

    OUT.mkdir(parents=True, exist_ok=True)
    plot_consistency(
        t_orb,
        nees_mean,
        nees_lo,
        nees_hi,
        f"NEES, mean of {runs} runs (3 states)",
        "NEES",
        OUT / "nees.png",
    )
    plot_consistency(
        t_orb,
        nis_mean,
        nis_lo,
        nis_hi,
        f"NIS, mean of {runs} runs (1 measurement)",
        "NIS",
        OUT / "nis.png",
    )
    plot_soc_error(t_orb, d, OUT / "soc_error.png")
    plot_prediction(pred_t, pred_err, OUT / "prediction_error.png")

    numbers = {
        "NEES inside 95% bounds (all steps)": f"{nees_in:.1f}%",
        "NEES inside 95% bounds (after orbit 1)": f"{nees_in_after:.1f}%",
        "NIS inside 95% bounds (all steps)": f"{nis_in:.1f}%",
        "RMS SOC error (all steps)": f"{rms_all:.3f}% SOC",
        "RMS SOC error (after orbit 1)": f"{rms_after:.3f}% SOC",
        "Max SOC error (after orbit 1)": f"{max_after:.3f}% SOC",
        "Mean eclipse-exit prediction error": f"{100 * pred_err.mean():+.3f}% SOC",
        "Mean absolute prediction error": f"{100 * np.abs(pred_err).mean():.3f}% SOC",
    }
    write_readme(runs, args.orbits, numbers, (nees_lo, nees_hi), (nis_lo, nis_hi), len(pred_err))
    for k, v in numbers.items():
        print(f"{k:42s} {v}")


def write_readme(runs, orbits, numbers, nees_bounds, nis_bounds, n_predictions):
    rows = "\n".join(f"| {k} | {v} |" for k, v in numbers.items())
    (OUT / "README.md").write_text(f"""# EKF Monte Carlo results

Generated by `uv run python tools/monte_carlo.py`. Do not edit by hand.

{runs} runs × {orbits:g} orbits. Each run has its own sensor-noise seed and an initial
EKF SOC error drawn uniformly from ±15%. The sim and FSW run in one process at the
default 30° beta angle with default loads. Truth is taken from the battery at the start
of each step, which is the state that produced the measurement.

| Metric | Value |
|---|---|
{rows}

- NEES is averaged over runs at each step and compared with χ²({3 * runs})/{runs}
  95% bounds [{nees_bounds[0]:.2f}, {nees_bounds[1]:.2f}].
- NIS is averaged the same way and compared with χ²({runs})/{runs}
  bounds [{nis_bounds[0]:.2f}, {nis_bounds[1]:.2f}].
- Prediction error covers all {n_predictions} predictions made during eclipses after the
  first one (the first eclipse has no previous duration to use). Each prediction is
  compared with the true SOC at that eclipse's exit.

![NEES](nees.png)
![NIS](nis.png)
![SOC error](soc_error.png)
![Prediction error](prediction_error.png)
""")


if __name__ == "__main__":
    main()
