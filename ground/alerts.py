"""Ground alert rules, defined once for two users:
- tools/gen_grafana.py turns each rule into a provisioned Grafana alert (Flux query,
  reduce, threshold);
- tools/fault_campaign.py evaluates the same rules here on recorded telemetry.

Rules read the fields ground/points.py writes, so both see the same values. Grafana
evaluates every rule each alert_interval_s over a window ending now (wall-clock
seconds); evaluate() does the same in mission time, with windows scaled by the
sim speed (the demo default is 60x).

Reducers: last, mean, max, count (Grafana's reduce step), plus two special rules:
red_limit (any thermistor outside its red limits) and run_length (consecutive
samples above the threshold, restarting at the window start like Flux stateCount).
"""

import bisect
import math
from dataclasses import dataclass

import params

DEMO_SPEED = 60.0
INTERVAL_S = params.P["alert_interval_s"]


@dataclass(frozen=True)
class Rule:
    uid: str
    title: str
    summary: str  # Grafana annotation; may use {{ $values.B }} and {{ $labels.node }}
    measurement: str
    field: str  # "T_" means every T_<node>_K field (red_limit)
    reducer: str
    op: str  # gt or lt
    threshold: float
    window_s: float
    no_data: str = "OK"  # Grafana state when the window holds no data
    tags: tuple = ()  # extra (tag, value) filters besides source
    severity: str = "critical"  # or "warning": a diagnosis aid, not a safety limit


P = params.P
RULES = [
    Rule("red-limit", "Red-limit violation",
         "{{ $labels.node }} crossed its red limit (docs/limits.md)",
         "housekeeping", "T_", "red_limit", "gt", 0, P["alert_window_s"]),
    Rule("predicted-soc-low",
         f"Predicted SOC at eclipse exit below {params.PREDICTED_SOC_ALERT:.0%}",
         "EKF predicts SOC {{ $values.B }} at eclipse exit",
         "estimator", "predicted_soc_exit", "last", "lt", params.PREDICTED_SOC_ALERT,
         P["alert_window_s"]),
    Rule("fsw-safe", "FSW entered SAFE",
         "Flight software is in SAFE mode; ground command needed to exit",
         "housekeeping", "mode", "last", "gt", 1.5, P["alert_window_s"]),
    Rule("nis-high",
         f"NIS above {params.NIS_GATE:g} for {P['nis_alert_samples']:.0f} consecutive samples",
         "EKF innovations inconsistent: {{ $values.B }} samples in a row",
         "estimator", "nis", "run_length", "gt", P["nis_alert_samples"] - 1, P["nis_window_s"],
         severity="warning"),
    Rule("stale-telemetry", "No telemetry for 30 s",
         "No FSW housekeeping received in the last 30 s",
         "housekeeping", "soc_est", "count", "lt", 1, P["alert_window_s"], no_data="Alerting"),
    Rule("battery-degraded", "FSW reported BATTERY_DEGRADED",
         "Flight software flagged a degraded battery cell (R0 above 1.5x nominal for 10 min)",
         "event", "met_s", "count", "gt", 0, P["event_alert_window_s"],
         tags=(("type", "BATTERY_DEGRADED"),), severity="warning"),
    Rule("radiator-degraded", "FSW reported RADIATOR_DEGRADED",
         "Flight software found an orbit-mean radiator temperature above its thermal "
         "prediction (docs/limits.md)",
         "event", "met_s", "count", "gt", 0, P["event_alert_window_s"],
         tags=(("type", "RADIATOR_DEGRADED"),), severity="warning"),
    Rule("load-excess",
         f"Eclipse load {P['load_excess_alert_W']:g} W above commanded loads",
         "Loads draw {{ $values.B }} W more than the commanded states explain",
         "housekeeping", "load_excess_W", "mean", "gt", P["load_excess_alert_W"],
         P["load_excess_window_s"], severity="warning"),
    Rule("r0-ratio",
         f"Battery R0 above {P['r0_ratio_alert']:g}x nominal for its temperature",
         "EKF R0 is {{ $values.B }}x nominal at the measured battery temperature",
         "estimator", "r0_ratio", "mean", "gt", P["r0_ratio_alert"], P["r0_ratio_window_s"],
         severity="warning"),
]
BY_UID = {r.uid: r for r in RULES}


class Telemetry:
    """Decoded field dicts (as ground/points.py writes them) per measurement, by MET."""

    def __init__(self):
        self.rows = {}  # measurement -> list of (met_s, tags, fields)
        self.times = {}  # measurement -> list of met_s, for bisect

    def add(self, measurement, tags, fields):
        """Rows must arrive in MET order. NaN fields are dropped, as InfluxDB has no NaN."""
        fields = {k: v for k, v in fields.items() if not (isinstance(v, float) and math.isnan(v))}
        self.rows.setdefault(measurement, []).append((fields["met_s"], tags, fields))
        self.times.setdefault(measurement, []).append(fields["met_s"])

    def window(self, measurement, start_s, end_s):
        rows, times = self.rows.get(measurement, []), self.times.get(measurement, [])
        return rows[bisect.bisect_right(times, start_s) : bisect.bisect_right(times, end_s)]


def _reduce(rule, rows):
    """The value Grafana's B step would produce, or None for no data."""
    rows = [r for r in rows if all(r[1].get(k) == v for k, v in rule.tags)]
    if rule.reducer == "red_limit":
        temps = [(k, v) for _, _, f in rows for k, v in f.items() if k.startswith("T_")]
        if not temps:
            return None
        limits = {f"T_{n}_K": (lim[0], lim[3]) for n, lim in params.LIMITS_K.items()}
        return float(any(t < limits[k][0] or t > limits[k][1] for k, t in temps))
    values = [f[rule.field] for _, _, f in rows if rule.field in f]
    if rule.reducer == "count":
        return len(values) or None
    if not values:
        return None
    if rule.reducer == "last":
        return values[-1]
    if rule.reducer == "mean":
        return sum(values) / len(values)
    if rule.reducer == "max":
        return max(values)
    if rule.reducer == "run_length":  # Flux stateCount: -1 when false, else run length
        run, best = 0, -1
        for v in values:
            run = run + 1 if v > params.NIS_GATE else 0
            best = max(best, run if run else -1)
        return best
    raise ValueError(rule.reducer)


def evaluate(rule, telemetry, now_s, speed=DEMO_SPEED):
    """(firing, value) for rule at mission time now_s; value None means no data."""
    rows = telemetry.window(rule.measurement, now_s - rule.window_s * speed, now_s)
    value = _reduce(rule, rows)
    if value is None:
        return rule.no_data == "Alerting", None
    firing = value > rule.threshold if rule.op == "gt" else value < rule.threshold
    return firing, value


def first_firing(rule, telemetry, end_s, speed=DEMO_SPEED, start_s=0.0):
    """MET of the first evaluation (every INTERVAL_S of wall time) at which rule fires."""
    step_s = INTERVAL_S * speed
    for k in range(1, math.floor((end_s - start_s) / step_s) + 1):
        now_s = start_s + k * step_s
        firing, value = evaluate(rule, telemetry, now_s, speed)
        if firing:
            return now_s, value
    return None, None
