# CLAUDE.md

Software-in-the-loop digital twin of a small LEO satellite's thermal and electrical
power systems. Three programs talk over UDP: a C++ spacecraft simulator (`sim/`),
C++ flight software (`fsw/`), and a Python ground station (`ground/`), with
InfluxDB + Grafana dashboards later. Built in 5 stages; see README.md for status.

## Ground rules

- Simple, clean, readable code. Short files and functions. No needless abstraction
  or extra frameworks.
- C++17, CMake, GoogleTest via FetchContent.
- Python 3.11+, dependencies in `pyproject.toml` managed with uv, ruff for linting.
- SI units internally, Kelvin for temperature. Put units in names where helpful
  (`temp_K`, `power_W`).
- All tunable constants live in one header: `common/params.hpp`.
- `sim` and `fsw` are each a library plus a thin `main()`, so tests and Monte Carlo
  tools can link them directly.
- Do not run any git commands (no init, commit, or push).
- Every stage ends with all tests passing and README.md updated.

## Commands

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
uv run pytest
uv run ruff check ground tests tools
uv run python tools/monte_carlo.py           # regenerates docs/results/ (~20 s)
scripts/run_local.sh --orbits 2 --speed 60   # fsw + sim over UDP
uv run python ground/decode.py               # print telemetry
uv run python ground/cmd.py noop             # send a telecommand
./build/sim/sim --orbits 5 --out run.csv && uv run python ground/plot_run.py run.csv
```

Any change to `fsw/ekf.cpp` must be mirrored in `ground/ref/ekf_ref.py` (pytest checks
they agree within 1e-9). Any new filter parameter must be written by `tools/ekf_trace.cpp`.

Packet layouts live in `docs/icd.md`. Any change to `common/messages.hpp`,
`common/ccsds.hpp` or a payload encoder must update `docs/icd.md` and `ground/ccsds.py`.
