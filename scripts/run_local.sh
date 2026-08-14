#!/usr/bin/env bash
# Starts flight software and the simulator together; stops FSW when the sim ends.
# Extra arguments go to the sim, e.g.:  scripts/run_local.sh --orbits 2 --speed 60
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD_DIR=${BUILD_DIR:-build}

if [[ ! -x $BUILD_DIR/fsw/fsw || ! -x $BUILD_DIR/sim/sim ]]; then
  cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD_DIR" -j
fi

SIM_PID=""
"$BUILD_DIR/fsw/fsw" &
FSW_PID=$!
trap 'kill $FSW_PID $SIM_PID 2>/dev/null || true' EXIT
trap 'exit 130' INT TERM  # Ctrl+C or kill: stop both via the EXIT trap
sleep 0.3  # let FSW bind its ports

"$BUILD_DIR/sim/sim" "$@" &
SIM_PID=$!
wait "$SIM_PID"  # waiting (not foreground) lets the traps run immediately
