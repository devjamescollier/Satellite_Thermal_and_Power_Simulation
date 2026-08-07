"""Ground alert rules evaluated in Python (ground/alerts.py), as the fault campaign uses them,
and the compute-usage job runner (tools/jobs.py)."""

import math
import sys
from pathlib import Path

import alerts
import params

sys.path.append(str(Path(__file__).resolve().parent.parent / "tools"))
import jobs  # noqa: E402

RULE = alerts.BY_UID
STEP_S = alerts.INTERVAL_S * alerts.DEMO_SPEED  # MET between Grafana evaluations at 60x


def housekeeping(met_s, **fields):
    temps = {f"T_{n}_K": 290.0 for n in params.NODES}
    return {"met_s": met_s, "mode": 0, "soc_est": 0.9, **temps, **fields}


def telemetry(measurement, rows, tags=None):
    t = alerts.Telemetry()
    for fields in rows:
        t.add(measurement, tags or {"source": "fsw"}, fields)
    return t


def test_red_limit_fires_on_one_sample_outside():
    red_high = params.LIMITS_K["battery"][3]
    rows = [housekeeping(s) for s in range(100)] + [housekeeping(100, T_battery_K=red_high + 0.1)]
    firing, _ = alerts.evaluate(RULE["red-limit"], telemetry("housekeeping", rows), 100)
    assert firing
    firing, _ = alerts.evaluate(RULE["red-limit"], telemetry("housekeeping", rows[:-1]), 100)
    assert not firing


def test_nis_run_length_needs_30_in_a_row_inside_the_window():
    def nis_run(n_high):
        rows = [{"met_s": s, "nis": 1.0} for s in range(100)]
        rows += [{"met_s": 100 + s, "nis": 50.0} for s in range(n_high)]
        return telemetry("estimator", rows)

    rule = RULE["nis-high"]
    assert not alerts.evaluate(rule, nis_run(29), 128)[0]
    assert alerts.evaluate(rule, nis_run(30), 129)[0]
    assert alerts.evaluate(rule, nis_run(30), 129)[1] == 30


def test_load_excess_ignores_sunlight_and_means_over_eclipse():
    rule = RULE["load-excess"]
    sunlit = [housekeeping(s, load_excess_W=math.nan) for s in range(100)]
    firing, value = alerts.evaluate(rule, telemetry("housekeeping", sunlit), 99)
    assert (firing, value) == (False, None)  # no eclipse data: no data, not an alert
    eclipse = [housekeeping(100 + s, load_excess_W=5.0) for s in range(10)]
    firing, value = alerts.evaluate(rule, telemetry("housekeeping", sunlit + eclipse), 109)
    assert firing and value == 5.0


def test_stale_telemetry_fires_on_no_data():
    t = telemetry("housekeeping", [housekeeping(0)])
    window_met = RULE["stale-telemetry"].window_s * alerts.DEMO_SPEED
    assert not alerts.evaluate(RULE["stale-telemetry"], t, 10)[0]
    assert alerts.evaluate(RULE["stale-telemetry"], t, window_met + 1)[0]


def test_event_rule_filters_on_type_and_fires_at_the_next_evaluation():
    rule = RULE["battery-degraded"]
    ack = telemetry("event", [{"met_s": 100.0, "detail": "NOOP accepted"}],
                    {"source": "fsw", "type": "CMD_ACK"})
    assert alerts.first_firing(rule, ack, 5000) == (None, None)
    degraded = telemetry("event", [{"met_s": 100.0, "detail": "R0 at 2.0x nominal"}],
                         {"source": "fsw", "type": "BATTERY_DEGRADED"})
    assert alerts.first_firing(rule, degraded, 5000) == (STEP_S, 1)


def test_rules_have_unique_ids_and_valid_reducers():
    assert len(alerts.BY_UID) == len(alerts.RULES)
    for rule in alerts.RULES:
        assert rule.reducer in ("last", "mean", "max", "count", "run_length", "red_limit")
        assert rule.op in ("gt", "lt") and rule.severity in ("critical", "warning")


def test_job_runner_records_cpu_memory_and_kills_on_timeout():
    hog = "import time; x = bytearray(64 << 20); x[::4096] = b'1' * len(x[::4096]); time.sleep(0.2)"
    stats = jobs.run_job("hog", [sys.executable, "-c", hog], timeout_s=30)
    assert stats.returncode == 0 and stats.wall_s >= 0.2
    assert stats.peak_rss_MB > 60 and stats.cpu_s > 0
    slow = jobs.run_job("slow", [sys.executable, "-c", "import time; time.sleep(30)"], 0.3)
    assert slow.returncode < 0 and slow.wall_s < 5
    assert set(jobs.stats_fields(stats)) == {"wall_s", "cpu_s", "peak_rss_MB", "returncode"}
