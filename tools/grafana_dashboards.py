"""The Mission Control and Compute Usage dashboards (written by tools/gen_grafana.py)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "ground"))  # appended: ground/cmd.py must not shadow stdlib cmd
from grafana_panels import (  # noqa: E402
    BAND,
    DATASOURCE,
    FSW,
    GREEN,
    RED,
    TRUTH,
    YELLOW,
    color,
    dashboard,
    flux,
    state_timeline,
    states,
    targets,
    timeseries,
)

import params  # noqa: E402

# --- Mission Control ------------------------------------------------------------


def temperature_panel(node, grid):
    red_lo, yel_lo, yel_hi, red_hi = params.LIMITS_K[node]
    steps = [
        {"color": RED, "value": None},
        {"color": YELLOW, "value": red_lo},
        {"color": GREEN, "value": yel_lo},
        {"color": YELLOW, "value": yel_hi},
        {"color": RED, "value": red_hi},
    ]
    field = f"T_{node}_K"
    return timeseries(
        f"{node.capitalize()} temperature",
        grid,
        [
            flux("housekeeping", field, "fsw", "FSW thermistor"),
            flux("truth", field, "truth", "Truth"),
        ],
        "kelvin",
        overrides=[color("FSW thermistor", FSW), color("Truth", TRUTH)],
        custom={"thresholdsStyle": {"mode": "line+area"}},
        thresholds=steps,
        axis={"min": red_lo - 10, "max": red_hi + 10},
    )


def soc_panel(grid):
    band = {"custom.lineWidth": 0, "custom.fillOpacity": 25}
    upper = color("+3σ", BAND)
    upper["properties"] += [{"id": k, "value": v} for k, v in band.items()]
    upper["properties"].append({"id": "custom.fillBelowTo", "value": "−3σ"})
    lower = color("−3σ", BAND)
    lower["properties"].append({"id": "custom.lineWidth", "value": 0})
    predicted = color("Predicted at eclipse exit", "#6250d6")
    predicted["properties"] += [
        {"id": "custom.drawStyle", "value": "points"},
        {"id": "custom.pointSize", "value": 4},
    ]
    return timeseries(
        "SOC: truth vs EKF estimate (±3σ)",
        grid,
        [
            flux("estimator", "soc_plus_3sigma", "fsw", "+3σ"),
            flux("estimator", "soc_minus_3sigma", "fsw", "−3σ"),
            flux("estimator", "soc", "fsw", "EKF estimate"),
            flux("truth", "soc", "truth", "Truth"),
            flux("estimator", "predicted_soc_exit", "fsw", "Predicted at eclipse exit"),
        ],
        "percentunit",
        overrides=[upper, lower, color("EKF estimate", FSW), color("Truth", TRUTH), predicted],
    )


def build_dashboard():
    w = {"x": 0, "y": 0, "w": 12, "h": 5}
    panels = [
        state_timeline(
            "Sunlight / eclipse",
            w,
            [
                states("truth", "eclipse", "truth", "Truth"),
                states("housekeeping", "sun_present", "fsw", "FSW sun sensor",
                       extra='\n  |> map(fn: (r) => ({r with _value: 1 - r._value}))'),
            ],
            [(0, "SUNLIGHT", "#eda100"), (1, "ECLIPSE", "#52514e")],
        ),
        state_timeline(
            "FSW mode",
            {**w, "x": 12},
            # max: the most severe mode in each window, so a brief SAFE is never hidden
            [states("housekeeping", "mode", "fsw", "Mode", fn="max")],
            [(0, "NOMINAL", GREEN), (1, "LOAD_SHED", YELLOW), (2, "SAFE", RED)],
        ),
    ]
    widths = [5, 5, 5, 5, 4]
    x = 0
    for node, width in zip(params.NODES, widths, strict=True):
        panels.append(temperature_panel(node, {"x": x, "y": 5, "w": width, "h": 8}))
        x += width
    panels += [
        soc_panel({"x": 0, "y": 13, "w": 12, "h": 9}),
        timeseries(
            "Internal resistance R0: truth vs EKF estimate",
            {"x": 12, "y": 13, "w": 12, "h": 9},
            [
                flux("estimator", "r0_ohm", "fsw", "EKF estimate"),
                flux("truth", "r0_ohm", "truth", "Truth"),
            ],
            "ohm",
            overrides=[color("EKF estimate", FSW), color("Truth", TRUTH)],
        ),
        timeseries(
            "Power generated vs consumed",
            {"x": 0, "y": 22, "w": 12, "h": 8},
            [
                flux("housekeeping", "power_generated_W", "fsw", "Generated (array)"),
                flux("housekeeping", "power_consumed_W", "fsw", "Consumed (loads + shunt)"),
            ],
            "watt",
            overrides=[
                color("Generated (array)", "#eda100"),
                color("Consumed (loads + shunt)", FSW),
            ],
        ),
        timeseries(
            f"NIS (max per window) vs χ² gate {params.NIS_GATE:g}",
            {"x": 12, "y": 22, "w": 12, "h": 8},
            [flux("estimator", "nis", "fsw", "NIS", fn="max")],
            "none",
            custom={
                "thresholdsStyle": {"mode": "dashed"},
                "scaleDistribution": {"type": "log", "log": 10},
            },
            thresholds=[{"color": GREEN, "value": None}, {"color": RED, "value": params.NIS_GATE}],
        ),
        timeseries(
            "Eclipse load: measured minus commanded (power-balance check)",
            {"x": 0, "y": 30, "w": 12, "h": 7},
            [flux("housekeeping", "load_excess_W", "fsw", "Excess load")],
            "watt",
            custom={"thresholdsStyle": {"mode": "dashed"}, "drawStyle": "points", "pointSize": 3},
            thresholds=[{"color": GREEN, "value": None},
                        {"color": YELLOW, "value": params.P["load_excess_alert_W"]}],
        ),
        timeseries(
            "Battery R0 ÷ nominal at measured temperature",
            {"x": 12, "y": 30, "w": 12, "h": 7},
            [flux("estimator", "r0_ratio", "fsw", "R0 ratio")],
            "none",
            custom={"thresholdsStyle": {"mode": "dashed"}},
            thresholds=[{"color": GREEN, "value": None},
                        {"color": YELLOW, "value": params.P["r0_ratio_alert"]},
                        {"color": RED, "value": params.P["degraded_r0_ratio"]}],
        ),
        timeseries(
            "Link: packet rate",
            {"x": 0, "y": 37, "w": 12, "h": 7},
            [
                flux("link", "packet_rate_hz", "fsw", "FSW telemetry"),
                flux("link", "packet_rate_hz", "truth", "Sim truth"),
            ],
            "hertz",
            overrides=[color("FSW telemetry", FSW), color("Sim truth", TRUTH)],
        ),
        timeseries(
            "Link: errors (cumulative)",
            {"x": 12, "y": 37, "w": 12, "h": 7},
            [
                flux("link", "seq_gaps", "fsw", "Seq gaps (FSW)", fn="last"),
                flux("link", "seq_gaps", "truth", "Seq gaps (truth)", fn="last"),
                flux("link", "decode_errors", "fsw", "Decode errors (FSW)", fn="last"),
                flux("truth", "missed_cycles", "truth", "Missed actuator cycles", fn="last"),
            ],
            "short",
            overrides=[
                color("Seq gaps (FSW)", FSW),
                color("Seq gaps (truth)", TRUTH),
                color("Decode errors (FSW)", "#1baf7a"),
                color("Missed actuator cycles", "#e87ba4"),
            ],
        ),
        {
            "type": "table",
            "title": "Recent events and command acks",
            "gridPos": {"x": 0, "y": 44, "w": 24, "h": 9},
            "datasource": DATASOURCE,
            "targets": targets(
                """from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "event" and r._field == "detail")
  |> group()
  |> keep(columns: ["_time", "type", "_value"])
  |> rename(columns: {_time: "Time", type: "Type", _value: "Detail"})
  |> sort(columns: ["Time"], desc: true)
  |> limit(n: 100)"""
            ),
            "fieldConfig": {"defaults": {}, "overrides": []},
            "options": {"showHeader": True, "cellHeight": "sm"},
        },
    ]
    return dashboard("mission-control", "Mission Control", panels, "now-10m", "5s")


# --- Compute Usage dashboard ------------------------------------------------------

COMPUTE = """from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "compute" and r.runner == "${runner}")"""
JOB_FIELDS = '["job", "wall_s", "cpu_s", "peak_rss_MB"]'


def per_job_bars(title, grid, fields, unit):
    """Bar per job, latest run of each job in the time range."""
    field_filter = " or ".join(f'r._field == "{f}"' for f in fields)
    query = f"""{COMPUTE}
  |> filter(fn: (r) => {field_filter})
  |> last()
  |> pivot(rowKey: ["job"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> keep(columns: ["job", {", ".join(f'"{f}"' for f in fields)}])
  |> sort(columns: ["job"])"""
    return {
        "type": "barchart",
        "title": title,
        "gridPos": grid,
        "datasource": DATASOURCE,
        "targets": targets(query),
        "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic"}},
                        "overrides": []},
        "options": {"xField": "job", "orientation": "auto", "xTickLabelRotation": -45,
                    "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}},
    }


def stat(title, grid, field, fn, unit):
    query = f"""{COMPUTE}
  |> filter(fn: (r) => r._field == "{field}")
  |> group()
  |> {fn}()"""
    return {
        "type": "stat",
        "title": title,
        "gridPos": grid,
        "datasource": DATASOURCE,
        "targets": targets(query),
        "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "fixed", "fixedColor": FSW}},
                        "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value",
                    "graphMode": "none", "textMode": "value"},
    }


def build_compute_dashboard():
    runner = {"type": "custom", "name": "runner", "label": "Runner",
              "query": "fault_campaign,monte_carlo",
              "current": {"text": "fault_campaign", "value": "fault_campaign"},
              "options": [{"text": v, "value": v, "selected": v == "fault_campaign"}
                          for v in ("fault_campaign", "monte_carlo")]}
    jobs_table = f"""{COMPUTE}
  |> pivot(rowKey: ["_time", "job"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> keep(columns: ["_time", {JOB_FIELDS[1:-1]}, "returncode"])
  |> rename(columns: {{_time: "Finished", job: "Job", wall_s: "Wall (s)", cpu_s: "CPU (s)",
                      peak_rss_MB: "Peak memory (MB)", returncode: "Exit code"}})
  |> sort(columns: ["Finished"], desc: true)
  |> limit(n: 200)"""
    wall_over_time = f"""{COMPUTE}
  |> filter(fn: (r) => r._field == "wall_s" or r._field == "cpu_s")
  |> group(columns: ["_field"])
  |> keep(columns: ["_time", "_value", "_field"])"""
    panels = [
        stat("Jobs", {"x": 0, "y": 0, "w": 6, "h": 4}, "wall_s", "count", "short"),
        stat("Total CPU time", {"x": 6, "y": 0, "w": 6, "h": 4}, "cpu_s", "sum", "s"),
        stat("Longest job (wall)", {"x": 12, "y": 0, "w": 6, "h": 4}, "wall_s", "max", "s"),
        stat("Highest peak memory", {"x": 18, "y": 0, "w": 6, "h": 4}, "peak_rss_MB", "max",
             "decmbytes"),
        per_job_bars("Wall and CPU time per job (latest run)", {"x": 0, "y": 4, "w": 12, "h": 9},
                     ["wall_s", "cpu_s"], "s"),
        per_job_bars("Peak memory per job (latest run)", {"x": 12, "y": 4, "w": 12, "h": 9},
                     ["peak_rss_MB"], "decmbytes"),
        timeseries("Job wall and CPU time over time", {"x": 0, "y": 13, "w": 24, "h": 7},
                   [wall_over_time], "s",
                   overrides=[color("wall_s", FSW), color("cpu_s", TRUTH)],
                   custom={"drawStyle": "points", "pointSize": 5}),
        {
            "type": "table",
            "title": "Jobs (latest first)",
            "gridPos": {"x": 0, "y": 20, "w": 24, "h": 10},
            "datasource": DATASOURCE,
            "targets": targets(jobs_table),
            "fieldConfig": {"defaults": {}, "overrides": []},
            "options": {"showHeader": True, "cellHeight": "sm"},
        },
    ]
    return dashboard("compute-usage", "Compute Usage", panels, "now-7d", "30s", [runner])
