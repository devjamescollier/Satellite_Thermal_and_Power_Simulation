"""Fault campaign: runs every sim fault headless (tools/mc_run, sim + FSW in one process),
evaluates the ground alert rules (ground/alerts.py, the same rules Grafana runs) on the
recorded telemetry, and writes one anomaly report per fault to docs/anomalies/.

Each fault is injected at FAULT_AT_S into a run of ORBITS orbits; a run without a
fault is the baseline the reports compare against. Fails (exit 1) if the baseline
raises any alert, or if a fault is not caught by exactly the rules expected for it.
Detection times assume the 60x demo speed Grafana's windows are sized for.

Usage: uv run python tools/fault_campaign.py [--no-influx]
"""

import argparse
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import jobs

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "ground"))  # appended: ground/cmd.py must not shadow stdlib cmd
import alerts  # noqa: E402
import ccsds  # noqa: E402
import params  # noqa: E402
import points  # noqa: E402

OUT = ROOT / "docs" / "anomalies"
MC_RUN = ROOT / "build" / "tools" / "mc_run"
PERIOD_S = 5668.1
FAULT_AT_S = 6000.0  # just after orbit 1, once the EKF has converged
ORBITS = 12  # long enough for the slowest (thermal) faults to settle
SEED = 1


@dataclass
class Fault:
    expected: tuple  # rule uids that must fire, and no others
    signals: tuple  # (label, measurement, field, unit) compared with the baseline
    root_cause: str
    fix: str


T = "housekeeping"
FAULTS = {
    "degraded_cell": Fault(
        ("battery-degraded", "r0-ratio"),
        (("EKF R0 ÷ nominal", "estimator", "r0_ratio", ""),
         ("True R0", "truth", "r0_ohm", "Ω"),
         ("Estimated SOC", T, "soc_est", ""),
         ("NIS", "estimator", "nis", "")),
        "The battery's internal resistance doubled (injected `degraded_cell`; in a real 4S2P "
        "pack, for example one parallel string going open or cell ageing). Terminal voltage "
        "sags more under load, so the EKF's innovations jump until its R0 state catches up.",
        "Operations: confirm with a second orbit of data, then reduce depth of discharge "
        "(payload duty cycle) and raise the LOAD_SHED threshold. Flight software: the EKF "
        "assumes capacity is known; add a capacity state so a fault that also loses "
        "capacity is tracked, and update the nominal R0 table after the event.",
    ),
    "stuck_on_heater": Fault(
        ("load-excess",),
        (("Eclipse load excess", T, "load_excess_W", "W"),
         ("Battery thermistor", T, "T_battery_K", "K"),
         ("Heater commanded on", T, "heater_on", "%"),
         ("Heater actually on (truth)", "truth", "heater_on", "%"),
         ("Estimated SOC", T, "soc_est", "")),
        "The battery heater's switch failed closed (injected `stuck_on_heater`), so the 5 W "
        "heater runs whatever the thermostat commands. Housekeeping reports only the "
        "commanded state, so the only signature is extra load power and a warmer battery.",
        "Operations: if the battery stays below its yellow limit, accept the extra 5 W and "
        "keep energy margin with payload duty cycling. Design: put two switches in series "
        "so a second one can open a stuck heater, and downlink heater current or switch "
        "state so a stuck heater is visible directly.",
    ),
    "biased_battery_thermistor": Fault(
        ("r0-ratio",),
        (("Battery thermistor", T, "T_battery_K", "K"),
         ("True battery temperature", "truth", "T_battery_K", "K"),
         ("EKF R0 ÷ nominal", "estimator", "r0_ratio", "")),
        "The battery thermistor reads 8 K high (injected `biased_battery_thermistor`; for "
        "example a calibration or bonding error). The battery is no warmer, so the EKF's "
        "R0 is unchanged, but the nominal R0 it is compared with is computed at the wrong "
        "temperature. The thermostat would also switch on 8 K late in a cold case.",
        "Operations: treat battery temperature as suspect and keep heater setpoints 8 K "
        "higher until it is resolved. Flight software: add a commandable thermistor offset, "
        "and cross-check the battery thermistor against the structure node and the R0 "
        "ratio. Design: fit a redundant battery thermistor.",
    ),
    "radiator_degradation": Fault(
        ("radiator-degraded",),
        (("Radiator", T, "T_radiator_K", "K"),
         ("Avionics", T, "T_avionics_K", "K"),
         ("Battery", T, "T_battery_K", "K"),
         ("Structure", T, "T_structure_K", "K")),
        "The radiator's emissivity dropped 40% (injected `radiator_degradation`; for "
        "example coating darkening or contamination). The same heat now leaves at a higher "
        "radiator temperature, and the conductively coupled nodes warm with it. Every "
        "temperature settles inside its limits, so only the comparison of the orbit-mean "
        "radiator temperature with the thermal prediction catches it.",
        "Operations: reduce payload duty cycle to restore thermal margin, and update the "
        "thermal model and the expected orbit mean with the measured emissivity. Flight "
        "software: load the expected value per beta angle from thermal analysis, since "
        "the one in params.hpp is valid only at the default 30° beta.",
    ),
}


def read_telemetry(path):
    """Decoded downlink from mc_run --packets, as the field dicts the station writes."""
    data, i, telemetry = path.read_bytes(), 0, alerts.Telemetry()
    while i < len(data):
        (n,) = struct.unpack_from(">H", data, i)
        packet = ccsds.decode_packet(data[i + 2 : i + 2 + n])
        for measurement, tags, fields in points.packet_to_points(packet):
            telemetry.add(measurement, tags, fields)
        i += 2 + n
    return telemetry


def last_orbit(telemetry, measurement, field):
    end = ORBITS * PERIOD_S
    rows = telemetry.window(measurement, end - PERIOD_S, end)
    return [f[field] for _, _, f in rows if field in f]


def describe(values, unit):
    """K: range; %: share of samples that are 1; otherwise mean and range."""
    if not values:
        return "—"
    lo, hi, mean = min(values), max(values), sum(values) / len(values)
    if unit == "%":
        return f"{100 * mean:.0f}% of samples"
    if unit == "K":
        return f"{lo:.1f} – {hi:.1f} K"
    return f"mean {mean:.3g}, range {lo:.3g} – {hi:.3g}" + (f" {unit}" if unit else "")


def detections(telemetry):
    """uid -> MET of the first firing, for every rule that fires."""
    end = ORBITS * PERIOD_S
    found = {}
    for rule in alerts.RULES:
        t, _ = alerts.first_firing(rule, telemetry, end)
        if t is not None:
            found[rule.uid] = t
    return found


def fsw_actions(telemetry):
    events = [(f["met_s"], f["detail"]) for _, tags, f in telemetry.rows.get("event", [])
              if tags["type"] in ("MODE_CHANGE", "BATTERY_DEGRADED", "RADIATOR_DEGRADED")]
    modes = sorted({ccsds.MODES[int(f["mode"])] for _, _, f in telemetry.rows[T]})
    return events, modes


def fmt_time(dt_s):
    wall_s = dt_s / alerts.DEMO_SPEED
    return f"{dt_s:.0f} s MET ({dt_s / PERIOD_S:.2f} orbits; {wall_s:.0f} s at 60x)"


def report(name, fault, telemetry, baseline, found):
    events, modes = fsw_actions(telemetry)
    after = {uid: t for uid, t in found.items() if t >= FAULT_AT_S}
    first = min(after.values(), default=None)
    detected = ", ".join(f"{alerts.BY_UID[u].title} after {fmt_time(t - FAULT_AT_S)}"
                         for u, t in sorted(after.items(), key=lambda kv: kv[1]))
    rows = "\n".join(f"| {label} | {describe(last_orbit(baseline, m, f), unit)} | "
                     f"{describe(last_orbit(telemetry, m, f), unit)} |"
                     for label, m, f, unit in fault.signals)
    actions = "\n".join(f"- MET {t:.0f} s, {fmt_time(t - FAULT_AT_S)} after the fault: {d}"
                        for t, d in events) or "- No events. The FSW took no action."
    gap = ""
    if not after:
        margins = [(n, lim[2] - max(last_orbit(telemetry, T, f"T_{n}_K")))
                   for n, lim in params.LIMITS_K.items()]
        node, margin = min(margins, key=lambda nm: nm[1])
        gap = (f"\nNo ground alert fired in {ORBITS} orbits. Every temperature settled inside its "
               f"limits; the smallest margin left is {node}, {margin:.1f} K below its yellow-high "
               "limit. Limit-based monitoring cannot see this fault until that margin is gone.\n")
    path = OUT / f"{name}.md"
    path.write_text(f"""# Anomaly report: {name}

Generated by `tools/fault_campaign.py`; do not edit by hand. Fault injected at MET
{FAULT_AT_S:.0f} s in a {ORBITS}-orbit headless run (seed {SEED}), compared with the same run
without the fault. Alerts are the Grafana rules, evaluated as Grafana would at 60x.

**Detection:** {detected or "**not detected**"}.
{gap}
## What the telemetry showed (last orbit)

| Signal | Nominal | With fault |
|---|---|---|
{rows}

## What the flight software did

{actions}

FSW modes during the run: {", ".join(modes)}.

## Root cause

{fault.root_cause}

## Recommended fix

{fault.fix}
""")
    return first, after, events


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-influx", action="store_true", help="don't write compute usage")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cmds = {}
        for name in ["none", *FAULTS]:
            cmd = [str(MC_RUN), "--seed", str(SEED), "--orbits", str(ORBITS),
                   "--out", str(tmp / f"{name}.csv"), "--packets", str(tmp / f"{name}.bin")]
            cmds[name] = cmd + ([] if name == "none" else ["--fault", f"{name}@{FAULT_AT_S:g}"])
        jobs.record("fault_campaign", jobs.run_all(cmds, timeout_s=600), not args.no_influx)
        runs = {name: read_telemetry(tmp / f"{name}.bin") for name in cmds}

    problems, rows = [], []
    baseline_alerts = detections(runs["none"])
    if baseline_alerts:
        problems.append(f"baseline raised {sorted(baseline_alerts)}")
    for name, fault in FAULTS.items():
        found = detections(runs[name])
        first, after, events = report(name, fault, runs[name], runs["none"], found)
        early = sorted(u for u, t in found.items() if t < FAULT_AT_S)
        if early or set(after) != set(fault.expected):
            problems.append(f"{name}: fired {sorted(found)}, expected {sorted(fault.expected)}")
        titles = [alerts.BY_UID[u].title for u in sorted(after, key=after.get)]
        by = ", ".join(titles) or "none"
        when = fmt_time(first - FAULT_AT_S) if first else "—"
        fsw = "; ".join(d for _, d in events) or "no action"
        rows.append(f"| [{name}]({name}.md) | {by} | {when} | {fsw} |")
        print(f"{name:28s} detected by {by}; {when}")
    (OUT / "README.md").write_text(f"""# Fault campaign results

Generated by `uv run python tools/fault_campaign.py`; do not edit by hand. Each fault is
injected at MET {FAULT_AT_S:.0f} s into a {ORBITS}-orbit headless run. The baseline run
without a fault raised {"no alerts" if not baseline_alerts else sorted(baseline_alerts)}.

| Fault | Detected by | Time to first detection | FSW action |
|---|---|---|---|
{chr(10).join(rows)}
""")
    if problems:
        sys.exit("fault campaign FAILED:\n  " + "\n  ".join(problems))
    print("fault campaign: all faults behaved as expected")


if __name__ == "__main__":
    main()
