"""Run every dashboard panel query and alert rule through Grafana's API.

Fails (exit 1) if any panel query errors or returns no data, if a series name
does not match the panel's color overrides, or if an alert rule fails to evaluate.
Mission Control is queried over the last --minutes; Compute Usage over its own
default range, once per value of its runner variable.

Usage: uv run python tools/check_grafana.py [--minutes 15] [--allow-empty TITLE ...]
Grafana login comes from GRAFANA_ADMIN_USER / GRAFANA_ADMIN_PASSWORD (env or .env).
"""

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "ground"))  # appended: ground/cmd.py must not shadow stdlib cmd
from env import env_var  # noqa: E402

GRAFANA = env_var("GRAFANA_URL", "http://localhost:3000")


def api(path, body=None):
    user, password = env_var("GRAFANA_ADMIN_USER"), env_var("GRAFANA_ADMIN_PASSWORD")
    req = urllib.request.Request(GRAFANA + path, method="POST" if body is not None else "GET")
    login = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {login}")
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        return json.loads(err.read() or b"{}") | {"http_status": err.code}


def series_names(frames):
    """Display name of each non-time field that has at least one non-null value."""
    names = []
    for frame in frames:
        fields, values = frame["schema"]["fields"], frame["data"]["values"]
        for field, column in zip(fields, values, strict=True):
            if field["type"] != "time" and any(v is not None for v in column):
                labels = field.get("labels") or {}
                names.append(field.get("config", {}).get("displayNameFromDS")
                             or labels.get("_field") or field["name"])
    return names


def state_values(frames):
    """Every non-null value of every non-time field."""
    return [v for f in frames for field, column in zip(f["schema"]["fields"], f["data"]["values"],
                                                       strict=True)
            if field["type"] != "time" for v in column if v is not None]


def check_states(panel, values):
    """State timelines: every value must be a mapped state. Returns (problem, states seen)."""
    mapping = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    unmapped = sorted({v for v in values if str(v) not in mapping})
    seen = sorted({mapping[str(v)]["text"] for v in values if str(v) in mapping})
    return (f"unmapped values {unmapped[:5]}" if unmapped else None), seen


def check_panel(panel, start_ms, end_ms):
    """(problems, notes, series names) for one panel. Problems: a query error, no data
    from any query, a series whose name no color override matches, or (state timelines)
    a value that is not one of the mapped states."""
    problems, notes, names = [], [], []
    styled = {o["matcher"]["options"] for o in panel["fieldConfig"].get("overrides", [])}
    for target in panel["targets"]:
        query = {"refId": target["refId"], "datasource": target["datasource"],
                 "query": target["query"], "intervalMs": 1000, "maxDataPoints": 500}
        body = {"from": str(start_ms), "to": str(end_ms), "queries": [query]}
        result = api("/api/ds/query", body).get("results", {}).get(target["refId"], {})
        if "error" in result:
            problems.append(f"query {target['refId']}: {result['error']}")
            continue
        found = series_names(result.get("frames", []))
        if panel["type"] == "state-timeline" and found:
            problem, seen = check_states(panel, state_values(result["frames"]))
            if problem:
                problems.append(f"query {target['refId']}: {problem}")
            notes.append(f"query {target['refId']}: states {', '.join(seen)}")
        if not found:
            notes.append(f"query {target['refId']}: no data in this window")
        unstyled = sorted(set(found) - styled) if styled else []
        if unstyled:
            problems.append(f"query {target['refId']}: series {unstyled} match no override")
        names += found
    if not names and not problems:
        problems.append("no data from any query")
    return problems, notes, names


def check_rule(rule, now_s):
    """Evaluate one provisioned rule's queries at now_s; return (problem or None, summary)."""
    body = {"data": rule["data"], "condition": rule["condition"],
            "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_s))}
    frames = api("/api/v1/eval", body).get("results", {})
    if not frames:
        return "no evaluation result", ""
    summary = []
    for ref, res in frames.items():
        if res.get("error") or res.get("status", 200) >= 400:
            return f"{ref}: {res.get('error')}", ""
        for frame in res.get("frames", []):
            values = frame["data"]["values"]
            last = values[-1][-1] if values and values[-1] else "∅"
            summary.append(f"{ref}={last}")
    return None, " ".join(summary)


def parse_relative_ms(text):
    """'now-7d' -> milliseconds."""
    number, unit = int(text[4:-1]), text[-1]
    return number * {"m": 60, "h": 3600, "d": 86400}[unit] * 1000


def variable_choices(dashboard):
    """[(label, {name: value})] for every option of the dashboard's (single) variable."""
    variables = dashboard.get("templating", {}).get("list", [])
    if not variables:
        return [("", {})]
    var = variables[0]
    return [(f"[{var['name']}={o['value']}] ", {var["name"]: o["value"]}) for o in var["options"]]


def substitute(panel, values):
    panel = json.loads(json.dumps(panel))
    for target in panel["targets"]:
        for name, value in values.items():
            target["query"] = target["query"].replace(f"${{{name}}}", value)
    return panel


def report_panel(panel, window, label, allow_empty):
    """Print one panel's result; returns 1 if it failed."""
    problems, notes, names = check_panel(panel, *window)
    if panel["title"] in allow_empty and problems == ["no data from any query"]:
        problems, notes = [], notes + ["allowed to be empty"]
    print(f"{'FAIL' if problems else 'ok  '} panel {label}{panel['title']}: "
          f"{', '.join(names) or '-'}")
    for p in problems + [f"note: {n}" for n in notes]:
        print(f"       {p}")
    return int(bool(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=15, help="window ending now to query")
    parser.add_argument("--end", type=float, help="window end (unix s); default now")
    parser.add_argument("--allow-empty", nargs="*", default=[], help="panel titles allowed no data")
    args = parser.parse_args()
    end_s = args.end or time.time()
    start_ms, end_ms = int((end_s - args.minutes * 60) * 1000), int(end_s * 1000)

    failed = 0
    for uid in ("mission-control", "compute-usage"):
        dashboard = api(f"/api/dashboards/uid/{uid}")["dashboard"]
        window = (start_ms, end_ms)
        if uid != "mission-control":  # its own default range, e.g. now-7d
            window = (end_ms - parse_relative_ms(dashboard["time"]["from"]), end_ms)
        for label, values in variable_choices(dashboard):
            for panel in dashboard["panels"]:
                failed += report_panel(substitute(panel, values), window, label, args.allow_empty)

    for rule in api("/api/v1/provisioning/alert-rules"):
        problem, summary = check_rule(rule, end_s)
        failed += problem is not None
        print(f"{'FAIL' if problem else 'ok  '} rule  {rule['title']}: {problem or summary}")

    health = api("/api/prometheus/grafana/api/v1/rules")
    for group in health.get("data", {}).get("groups", []):
        for r in group["rules"]:
            if r.get("health") == "error":
                failed += 1
                print(f"FAIL scheduler {r['name']}: {r.get('lastError')}")
    print("all checks passed" if not failed else f"{failed} check(s) failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
