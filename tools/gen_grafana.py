"""Generate the Grafana dashboards, alert rules and docs/limits.md.

Limits and thresholds come from common/params.hpp and the alert rules from
ground/alerts.py, so the dashboards, alerts and docs cannot drift from the
flight values or from what tools/fault_campaign.py checks.
tests/test_grafana.py fails if the committed files are out of date.

Usage: uv run python tools/gen_grafana.py
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "ground"))  # appended: ground/cmd.py must not shadow stdlib cmd
from grafana_dashboards import build_compute_dashboard, build_dashboard  # noqa: E402
from grafana_panels import DATASOURCE  # noqa: E402

import alerts  # noqa: E402
import params  # noqa: E402

PROVISIONING = ROOT / "grafana" / "provisioning"
DASHBOARD_PATH = PROVISIONING / "dashboards" / "mission_control.json"
COMPUTE_PATH = PROVISIONING / "dashboards" / "compute_usage.json"
RULES_PATH = PROVISIONING / "alerting" / "rules.yaml"
LIMITS_PATH = ROOT / "docs" / "limits.md"


# --- Alert rules (from ground/alerts.py) -----------------------------------------

REDUCE_STEP = {"red_limit": "max", "run_length": "max", "last": "last", "count": "last",
               "mean": "mean", "max": "max"}  # alerts.Rule reducer -> Grafana reduce


def red_limit_query():
    lows = ", ".join(f'"T_{n}_K": {lim[0]}' for n, lim in params.LIMITS_K.items())
    highs = ", ".join(f'"T_{n}_K": {lim[3]}' for n, lim in params.LIMITS_K.items())
    # Flux has no exponent literals (1e9), so the dict.get defaults are written out.
    # Each node ends as its own time series tagged node=..., so Grafana alerts per node.
    return f"""import "dict"
low = [{lows}]
high = [{highs}]
from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "housekeeping" and r.source == "fsw")
  |> filter(fn: (r) => r._field =~ /^T_/)
  |> map(fn: (r) => ({{r with _value:
      if r._value < dict.get(dict: low, key: r._field, default: -1000000.0)
        or r._value > dict.get(dict: high, key: r._field, default: 1000000.0) then 1.0 else 0.0}}))
  |> max()
  |> map(fn: (r) => ({{r with node: r._field}}))
  |> group(columns: ["node"])
  |> keep(columns: ["_time", "_value", "node"])"""


def rule_query(r):
    if r.reducer == "red_limit":
        return red_limit_query()
    tags = "".join(f' and r.{k} == "{v}"' for k, v in r.tags)
    query = f"""from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "{r.measurement}" and r.source == "fsw"{tags})
  |> filter(fn: (r) => r._field == "{r.field}")"""
    if r.reducer == "run_length":  # stateCount: consecutive samples above the gate
        query += f"""
  |> stateCount(fn: (r) => r._value > {params.NIS_GATE})
  |> map(fn: (r) => ({{r with _value: float(v: r.stateCount)}}))
  |> drop(columns: ["stateCount"])
  |> max()"""
    elif r.reducer in ("last", "count"):
        query += f"\n  |> {r.reducer}()"
    return query


def grafana_rule(r):
    """Query A -> reduce B -> threshold C; fires when C is true."""
    return {
        "uid": r.uid,
        "title": r.title,
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "relativeTimeRange": {"from": int(r.window_s), "to": 0},
                "datasourceUid": DATASOURCE["uid"],
                "model": {"refId": "A", "query": rule_query(r)},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {"refId": "B", "type": "reduce", "expression": "A",
                          "reducer": REDUCE_STEP[r.reducer]},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [{"evaluator": {"type": r.op, "params": [r.threshold]}}],
                },
            },
        ],
        "noDataState": r.no_data,
        "execErrState": "Error",
        "for": "0s",
        "annotations": {"summary": r.summary},
        "labels": {"severity": r.severity},
    }


def build_rules():
    interval = f"{params.P['alert_interval_s']:.0f}s"
    group = {"orgId": 1, "name": "mission", "folder": "Mission Control", "interval": interval,
             "rules": [grafana_rule(r) for r in alerts.RULES]}
    return {"apiVersion": 1, "groups": [group]}


# --- docs/limits.md -------------------------------------------------------------


def condition_text(r):
    if r.reducer == "red_limit":
        return "any thermistor sample outside its red limits"
    if r.reducer == "run_length":
        return f"more than {r.threshold:g} samples in a row with NIS > {params.NIS_GATE:g}"
    what = f"`{r.measurement}.{r.field}`" + "".join(f" ({k} = {v})" for k, v in r.tags)
    op = ">" if r.op == "gt" else "<"
    return f"{r.reducer} of {what} {op} {r.threshold:g}"


def limits_markdown():
    rows = []
    for node, (red_lo, yel_lo, yel_hi, red_hi) in params.LIMITS_K.items():
        limits = (red_lo, yel_lo, yel_hi, red_hi)
        cells = " | ".join(f"{k:.2f} K ({k - 273.15:+.1f} °C)" for k in limits)
        rows.append(f"| {node} | {cells} |")
    table = "\n".join(rows)
    alert_rows = "\n".join(
        f"| {r.title} | {r.severity} | {condition_text(r)} | {r.window_s:g} s |"
        for r in alerts.RULES
    )
    return f"""# Temperature and alert limits

Generated from `common/params.hpp` and `ground/alerts.py` by `tools/gen_grafana.py`.
Do not edit by hand. The Grafana thresholds and alert rules come from the same values,
and `tests/test_grafana.py` checks that everything matches.

| Node | Red low | Yellow low | Yellow high | Red high |
|---|---|---|---|---|
{table}

- **Red**: the flight software goes to SAFE (any thermistor sample outside), and Grafana
  raises "Red-limit violation".
- **Yellow**: shown on the dashboard only (the yellow bands on each temperature panel).

## Alert rules

Grafana evaluates every rule each {params.P['alert_interval_s']:g} s over a window ending
now (wall-clock seconds, sized for the 60x demo speed). `tools/fault_campaign.py`
evaluates the same rules on recorded telemetry.

| Alert | Severity | Fires when | Window |
|---|---|---|---|
{alert_rows}
"""


class _BlockDumper(yaml.SafeDumper):
    """Writes multi-line strings (Flux queries) as readable | blocks."""


_BlockDumper.add_representer(
    str,
    lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None),
)


def render():
    """Path -> file contents for every generated file."""
    header = "# Generated by tools/gen_grafana.py from common/params.hpp. Do not edit by hand.\n"
    return {
        DASHBOARD_PATH: json.dumps(build_dashboard(), indent=2, ensure_ascii=False) + "\n",
        COMPUTE_PATH: json.dumps(build_compute_dashboard(), indent=2, ensure_ascii=False) + "\n",
        RULES_PATH: header + yaml.dump(build_rules(), Dumper=_BlockDumper, sort_keys=False,
                                       allow_unicode=True, width=100),
        LIMITS_PATH: limits_markdown(),
    }


def main():
    for path, text in render().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
