"""Building blocks for the generated Grafana dashboards: Flux queries and panel JSON."""

DATASOURCE = {"type": "influxdb", "uid": "influxdb"}
FSW, TRUTH, BAND = "#2a78d6", "#eb6834", "#86b6ef"  # palette slots 1 and 2, light blue band
RED, YELLOW, GREEN = "red", "yellow", "green"
MIN_INTERVAL = "2s"  # smallest display window: 1 Hz real-time data never leaves empty windows


# --- Flux helpers ---------------------------------------------------------------


def flux(measurement, field, source, label, fn="mean", extra=""):
    """One series per display window, renamed to label so the legend reads cleanly.
    Empty windows come back as nulls, so time series break at gaps between runs."""
    return f"""from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "{measurement}" and r.source == "{source}")
  |> filter(fn: (r) => r._field == "{field}"){extra}
  |> aggregateWindow(every: v.windowPeriod, fn: {fn}, createEmpty: true)
  |> keep(columns: ["_time", "_value", "_field"])
  |> set(key: "_field", value: "{label}")"""


def states(measurement, field, source, label, extra="", fn="last"):
    """Integer states for state timelines: one raw sample per display window (last, or max
    to show the most severe state), never an average, so 0/1 stays 0/1; null for empty
    windows (gaps between runs). Raw samples alone exceed Grafana's 5001-row limit at 60x."""
    return f"""from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "{measurement}" and r.source == "{source}")
  |> filter(fn: (r) => r._field == "{field}"){extra}
  |> toInt()
  |> aggregateWindow(every: v.windowPeriod, fn: {fn}, createEmpty: true)
  |> keep(columns: ["_time", "_value", "_field"])
  |> set(key: "_field", value: "{label}")"""


def targets(*queries):
    return [
        {"refId": chr(65 + i), "datasource": DATASOURCE, "query": q}
        for i, q in enumerate(queries)
    ]


def color(name, hex_color):
    return {
        "matcher": {"id": "byName", "options": name},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": hex_color}}],
    }


# --- Panels ---------------------------------------------------------------------


def timeseries(title, grid, queries, unit, overrides=(), custom=None, thresholds=None, axis=None):
    defaults = {
        "unit": unit,
        "color": {"mode": "fixed", "fixedColor": FSW},
        # spanNulls false: break the line at empty windows (gaps between runs).
        "custom": {"lineWidth": 2, "fillOpacity": 0, "showPoints": "never", "spanNulls": False,
                   **(custom or {})},
        **(axis or {}),
    }
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
    return {
        "type": "timeseries",
        "title": title,
        "gridPos": grid,
        "datasource": DATASOURCE,
        "interval": MIN_INTERVAL,
        "targets": targets(*queries),
        "fieldConfig": {"defaults": defaults, "overrides": list(overrides)},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
    }


def state_timeline(title, grid, queries, mappings):
    """mappings: [(raw value, text, color)]. The fixed color mode keeps threshold steps
    (Grafana's "-∞+" item) out of the legend, which then lists only the mapped states."""
    options = {str(v): {"text": text, "color": c, "index": i}
               for i, (v, text, c) in enumerate(mappings)}
    return {
        "type": "state-timeline",
        "title": title,
        "gridPos": grid,
        "datasource": DATASOURCE,
        "interval": MIN_INTERVAL,
        "targets": targets(*queries),
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": "text"},
                "mappings": [{"type": "value", "options": options}],
                "custom": {"fillOpacity": 80, "lineWidth": 0, "spanNulls": False},
            },
            "overrides": [],
        },
        "options": {
            "showValue": "auto",
            "mergeValues": True,
            "rowHeight": 0.8,
            "alignValue": "center",
            "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
        },
    }


def dashboard(uid, title, panels, time_from, refresh, variables=()):
    for i, panel in enumerate(panels, start=1):
        panel["id"] = i
    return {
        "uid": uid,
        "title": title,
        "tags": ["satellite", "generated"],
        "timezone": "browser",
        "editable": False,
        "refresh": refresh,
        "time": {"from": time_from, "to": "now"},
        "templating": {"list": list(variables)},
        "schemaVersion": 39,
        "version": 1,
        "panels": panels,
    }
