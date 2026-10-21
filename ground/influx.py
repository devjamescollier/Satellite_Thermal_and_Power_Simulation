"""Batched InfluxDB 2 writes (line protocol over HTTP), used by the ground station and the
Monte Carlo and fault-campaign runners. Settings come from INFLUX_URL, INFLUX_ORG,
INFLUX_BUCKET and INFLUX_TOKEN in the environment or .env.

`python ground/influx.py delete-telemetry` deletes every telemetry point from the bucket
(scripts/run_demo.sh --fresh); compute-usage history is kept.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from env import env_var

MAX_BUFFERED_LINES = 100_000  # drop data rather than grow without bound if InfluxDB is down
TELEMETRY = ("housekeeping", "estimator", "event", "truth", "link")  # written by the station


def influx_config():
    return {k: env_var(k) for k in ("INFLUX_ORG", "INFLUX_BUCKET", "INFLUX_TOKEN")} | {
        "INFLUX_URL": env_var("INFLUX_URL", "http://localhost:8086")
    }


class InfluxWriter:
    def __init__(self, cfg=None):
        cfg = cfg or influx_config()
        query = urllib.parse.urlencode(
            {"org": cfg["INFLUX_ORG"], "bucket": cfg["INFLUX_BUCKET"], "precision": "ns"}
        )
        self.url = f"{cfg['INFLUX_URL']}/api/v2/write?{query}"
        self.token = cfg["INFLUX_TOKEN"]
        self.lines = []

    def add(self, lines):
        if len(self.lines) < MAX_BUFFERED_LINES:
            self.lines.extend(lines)

    def flush(self):
        """Write the buffer; on failure keep it for the next flush. True if written."""
        if not self.lines:
            return True
        body = "\n".join(self.lines).encode()
        req = urllib.request.Request(self.url, data=body, method="POST")
        req.add_header("Authorization", f"Token {self.token}")
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        try:
            urllib.request.urlopen(req, timeout=5).close()
            self.lines = []
            return True
        except (urllib.error.URLError, OSError) as err:
            print(f"InfluxDB write failed ({err}); keeping {len(self.lines)} lines")
            return False


def delete_telemetry(cfg=None):
    """Delete all points of the station's measurements. InfluxDB delete predicates support
    only = and AND, so each measurement is deleted separately (keeping "compute")."""
    cfg = cfg or influx_config()
    query = urllib.parse.urlencode({"org": cfg["INFLUX_ORG"], "bucket": cfg["INFLUX_BUCKET"]})
    for measurement in TELEMETRY:
        body = {"start": "1970-01-01T00:00:00Z", "stop": "2100-01-01T00:00:00Z",
                "predicate": f'_measurement="{measurement}"'}
        req = urllib.request.Request(f"{cfg['INFLUX_URL']}/api/v2/delete?{query}",
                                     data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", f"Token {cfg['INFLUX_TOKEN']}")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=30).close()
    print(f"deleted {', '.join(TELEMETRY)} from bucket {cfg['INFLUX_BUCKET']}")


if __name__ == "__main__":
    if sys.argv[1:] != ["delete-telemetry"]:
        sys.exit("usage: python ground/influx.py delete-telemetry")
    delete_telemetry()
