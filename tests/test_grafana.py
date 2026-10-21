"""Grafana provisioning stays in sync with params.hpp and with what the station writes."""

import json
import re
import struct
import sys
from pathlib import Path

import yaml

import alerts
import ccsds
import params
import points

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "tools"))
import gen_grafana  # noqa: E402
import jobs  # noqa: E402

PROVISIONING = ROOT / "grafana" / "provisioning"


def written_fields():
    """measurement -> field names that ground/points.py writes for one packet of each kind."""
    def fields(packet):
        (line,) = points.packet_to_lines(ccsds.decode_packet(packet), 0)
        return {kv.split("=")[0] for kv in line.split(" ")[1].split(",")}

    hk = ccsds.HOUSEKEEPING.pack(0, 0, 0, 0, *[1.0] * 11, 0, 0)
    est = struct.pack(">8fIff", *[0.5] * 8, 0, 0.5, 1.0)
    truth = ccsds.SIM_TRUTH.pack(0, 0, 0, 0, *[1.0] * 9, 0, 1.0, 1.0)
    event = ccsds.EVENT.pack(2, 0, 0, 0, 1)
    out = {
        "housekeeping": fields(ccsds.encode_packet(ccsds.APID_HOUSEKEEPING, hk)),
        "estimator": fields(ccsds.encode_packet(ccsds.APID_ESTIMATOR, est)),
        "truth": fields(ccsds.encode_packet(ccsds.APID_SIM_TRUTH, truth)),
        "event": fields(ccsds.encode_packet(ccsds.APID_EVENTS, event)),
    }
    link = points.link_line("fsw", 1.0, 0, 0, 0)
    out["link"] = {kv.split("=")[0] for kv in link.split(" ")[1].split(",")}
    out["compute"] = set(jobs.stats_fields(jobs.JobStats("job", 1.0, 1.0, 1.0, 0, 0)))
    return out


def all_queries():
    for name in ("mission_control.json", "compute_usage.json"):
        dashboard = json.loads((PROVISIONING / "dashboards" / name).read_text())
        for panel in dashboard["panels"]:
            for target in panel["targets"]:
                yield panel["title"], target["query"]
    rules = yaml.safe_load((PROVISIONING / "alerting" / "rules.yaml").read_text())
    for rule in rules["groups"][0]["rules"]:
        yield rule["title"], rule["data"][0]["model"]["query"]


def test_generated_files_are_up_to_date():
    for path, text in gen_grafana.render().items():
        assert path.read_text() == text, f"{path.name} is stale: run tools/gen_grafana.py"


def test_every_query_uses_a_written_measurement_and_field():
    written = written_fields()
    for title, query in all_queries():
        measurements = re.findall(r'r\._measurement == "(\w+)"', query)
        assert measurements, title
        for m in measurements:
            assert m in written, f"{title}: unknown measurement {m}"
            for field in re.findall(r'r\._field == "(\w+)"', query):
                assert field in written[m], f"{title}: {m} has no field {field}"
            for pattern in re.findall(r"r\._field =~ /(.+?)/", query):
                assert any(re.search(pattern, f) for f in written[m]), title


def test_no_exponent_literals_in_flux():
    for title, query in all_queries():
        assert not re.search(r"\d[eE][+-]?\d", query), f"{title}: Flux has no 1e9-style literals"


def test_grafana_rules_match_the_shared_rule_table():
    groups = yaml.safe_load((PROVISIONING / "alerting" / "rules.yaml").read_text())["groups"]
    rules = {r["uid"]: r for r in groups[0]["rules"]}
    assert set(rules) == set(alerts.BY_UID)
    for uid, r in rules.items():
        spec = alerts.BY_UID[uid]
        condition = r["data"][2]["model"]["conditions"][0]["evaluator"]
        assert (condition["type"], condition["params"][0]) == (spec.op, spec.threshold)
        assert r["data"][0]["relativeTimeRange"]["from"] == spec.window_s
        assert (r["noDataState"], r["labels"]["severity"]) == (spec.no_data, spec.severity)
    assert alerts.BY_UID["predicted-soc-low"].threshold == params.PREDICTED_SOC_ALERT
    assert str(params.NIS_GATE) in rules["nis-high"]["data"][0]["model"]["query"]
    query = rules["red-limit"]["data"][0]["model"]["query"]
    for node, (red_lo, _, _, red_hi) in params.LIMITS_K.items():
        assert f'"T_{node}_K": {red_lo}' in query and f'"T_{node}_K": {red_hi}' in query


def test_dashboard_thresholds_and_limits_doc_match_params():
    dashboard = json.loads((PROVISIONING / "dashboards" / "mission_control.json").read_text())
    limits_md = (ROOT / "docs" / "limits.md").read_text()
    for node, limits in params.LIMITS_K.items():
        title = f"{node.capitalize()} temperature"
        panel = next(p for p in dashboard["panels"] if p["title"] == title)
        steps = [s["value"] for s in panel["fieldConfig"]["defaults"]["thresholds"]["steps"][1:]]
        assert steps == list(limits)
        row = next(r for r in limits_md.splitlines() if r.startswith(f"| {node} |"))
        assert [float(k) for k in re.findall(r"([\d.]+) K", row)] == list(limits)


def test_provisioning_basics():
    assert (PROVISIONING / "plugins").is_dir()  # Grafana logs an error if it is missing
    contact = (PROVISIONING / "alerting" / "contact_points.yaml").read_text()
    assert "${ALERT_WEBHOOK_URL}" in contact
    datasource = (PROVISIONING / "datasources" / "influxdb.yaml").read_text()
    assert "${INFLUX_TOKEN}" in datasource
