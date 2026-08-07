"""Cross-checks the C++ EKF against the NumPy reference on identical inputs.

tools/ekf_trace (C++) runs one simulated orbit, including a 10% initial SOC error,
a degraded_cell fault and a voltage spike. The reference replays the same current
and voltage samples and must reproduce every state to 1e-9.
"""

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from ref import ekf_ref

ROOT = Path(__file__).resolve().parent.parent
TRACE_BIN = Path(os.environ.get("EKF_TRACE_BIN", ROOT / "build" / "tools" / "ekf_trace"))


@pytest.fixture(scope="module")
def trace(tmp_path_factory):
    if not TRACE_BIN.exists():
        pytest.fail(f"{TRACE_BIN} not found: build the C++ tools first (cmake --build build)")
    out = tmp_path_factory.mktemp("ekf_trace")
    subprocess.run([str(TRACE_BIN), str(out)], check=True, capture_output=True, timeout=120)
    return ekf_ref.load_trace(out)


def test_reference_matches_cpp_states(trace):
    cfg, t = trace
    states, nis, accepted, _ = ekf_ref.run(cfg, t["dt_s"], t["current_A"], t["voltage_V"])
    cpp = np.column_stack([t["soc"], t["v_rc_V"], t["r0_ohm"]])
    assert np.abs(states - cpp).max() < 1e-9
    assert np.allclose(nis, t["nis"], rtol=1e-9, atol=1e-12)
    assert np.array_equal(accepted, t["accepted"].astype(bool))


def test_trace_exercises_gate_and_fault(trace):
    cfg, t = trace
    _, _, accepted, rejections = ekf_ref.run(cfg, t["dt_s"], t["current_A"], t["voltage_V"])
    assert not accepted[1500]  # the injected spike
    assert rejections >= cfg["max_consecutive_rejections"]  # the fault step reopened R0
    assert t["r0_ohm"][-1] > 1.8 * t["r0_ohm"][1000]  # R0 roughly doubled after the fault
