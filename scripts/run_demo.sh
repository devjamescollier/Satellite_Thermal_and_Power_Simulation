#!/usr/bin/env bash
# Mission-control demo: InfluxDB + Grafana (docker compose), ground station, FSW and sim.
# Watch it live at http://localhost:3000 (Mission Control dashboard).
#
#   scripts/run_demo.sh [--fresh] [--orbits N] [--speed X] [--fault NAME@TIME_S]... [--timeout S]
#
# Defaults: 1 orbit at 60x (about 95 s). --fault and any other arguments go to the sim.
# --fresh first deletes old telemetry from the InfluxDB bucket, so the dashboard shows
# one clean run (compute-usage history is kept).
# A NOOP is sent at the start so the events table shows a command ack.
# Every background process is stopped on exit, on Ctrl+C, and after --timeout seconds
# (default: expected run time + 2 min).
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD_DIR=${BUILD_DIR:-build}

ORBITS=1 SPEED=60 TIMEOUT="" FRESH=0
SIM_ARGS=()
while (($#)); do
  case $1 in
    --orbits) ORBITS=$2; shift 2 ;;
    --speed) SPEED=$2; shift 2 ;;
    --timeout) TIMEOUT=$2; shift 2 ;;
    --fresh) FRESH=1; shift ;;
    --fault) SIM_ARGS+=(--fault "$2"); shift 2 ;;
    *) SIM_ARGS+=("$1"); shift ;;
  esac
done
# One orbit is 5668 s of sim time; --speed 0 runs about 0.3 s per orbit (allow 5 s).
TIMEOUT=${TIMEOUT:-$(awk -v o="$ORBITS" -v s="$SPEED" \
  'BEGIN { print int((s > 0 ? o * 5668 / s : o * 5) + 120) }')}

PIDS=()
any_alive() {
  local pid
  for pid in "${PIDS[@]}"; do kill -0 "$pid" 2>/dev/null && return 0; done
  return 1
}
cleanup() {
  trap - EXIT INT TERM
  [[ ${#PIDS[@]} -eq 0 ]] && return
  kill "${PIDS[@]}" 2>/dev/null || true  # SIGTERM: the station flushes to InfluxDB
  for _ in $(seq 50); do                # up to 5 s, then force
    any_alive || return 0
    sleep 0.1
  done
  kill -9 "${PIDS[@]}" 2>/dev/null || true
} 2>/dev/null  # also hides bash's "Terminated" job notices
trap cleanup EXIT
trap 'exit 130' INT TERM

[[ -f .env ]] || { echo "run_demo: copy .env.example to .env first" >&2; exit 1; }
docker compose up -d --wait influxdb grafana  # the rest runs on the host
if [[ ! -x $BUILD_DIR/fsw/fsw || ! -x $BUILD_DIR/sim/sim ]]; then
  cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD_DIR" -j
fi
uv sync -q
PY=.venv/bin/python  # run python directly so the PIDs below are the real processes
if ((FRESH)); then "$PY" ground/influx.py delete-telemetry; fi

"$PY" ground/station.py &
PIDS+=($!)
sleep 1
kill -0 "${PIDS[0]}" 2>/dev/null || { echo "run_demo: station failed (ports busy?)" >&2; exit 1; }
"$BUILD_DIR/fsw/fsw" &
PIDS+=($!)
sleep 0.3  # let FSW bind its ports
"$BUILD_DIR/sim/sim" --orbits "$ORBITS" --speed "$SPEED" ${SIM_ARGS[@]+"${SIM_ARGS[@]}"} &
SIM_PID=$!
PIDS+=("$SIM_PID")
"$PY" ground/cmd.py --timeout 10 noop &
PIDS+=($!)

echo "run_demo: running $ORBITS orbit(s) at speed $SPEED; dashboard http://localhost:3000"
SECONDS=0
while kill -0 "$SIM_PID" 2>/dev/null; do
  if ((SECONDS >= TIMEOUT)); then
    echo "run_demo: timed out after ${TIMEOUT} s" >&2
    exit 1
  fi
  sleep 1
done
wait "$SIM_PID"
echo "run_demo: done"
