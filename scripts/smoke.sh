#!/usr/bin/env bash
# End-to-end smoke test: 2 orbits through sim, FSW and ground station into InfluxDB,
# then every Grafana panel query and alert rule through Grafana's API.
# Needs docker and a .env. Extra arguments go to run_demo.sh (e.g. --speed 120).
set -euo pipefail
cd "$(dirname "$0")/.."
ORBITS=2
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
SECONDS=0

scripts/run_demo.sh --orbits "$ORBITS" --speed 0 --timeout 120 "$@"

set -a; source .env; set +a
count() {  # measurement $1, field $2: per-series aggregate $3 (count, max) since START, summed
  curl -sf --max-time 30 "$INFLUX_URL/api/v2/query?org=$INFLUX_ORG" \
    -H "Authorization: Token $INFLUX_TOKEN" -H "Content-Type: application/vnd.flux" \
    --data "from(bucket: \"$INFLUX_BUCKET\") |> range(start: $START)
      |> filter(fn: (r) => r._measurement == \"$1\" and r._field == \"$2\")
      |> $3() |> group() |> sum() |> keep(columns: [\"_value\"])" |
    tr -d '\r' | awk -F, 'NR == 2 { print $4 } END { if (NR < 2) print 0 }'
}

steps=$((ORBITS * 5668))
failed=0
for m in housekeeping estimator truth; do
  n=$(count "$m" met_s count)
  echo "smoke: $m points: $n (expected about $steps)"
  ((n * 100 >= steps * 99)) || { echo "smoke: FAIL too few $m points" >&2; failed=1; }
done
errors=$(count link decode_errors max)
echo "smoke: decode errors: $errors, sequence gaps: $(count link seq_gaps max)"
[[ $errors == 0 ]] || { echo "smoke: FAIL decode errors" >&2; failed=1; }

minutes=$(((SECONDS + 59) / 60 + 1))
uv run python tools/check_grafana.py --minutes "$minutes" || failed=1
((failed == 0)) && echo "smoke: PASS" || { echo "smoke: FAIL" >&2; exit 1; }
