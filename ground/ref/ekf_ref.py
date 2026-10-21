"""Plain NumPy reference implementation of the flight-software battery EKF.

Mirrors fsw/ekf.cpp step for step so the C++ filter can be checked against an
independent implementation. Parameters come from the JSON written by the C++
tool tools/ekf_trace, so both sides always use identical values.

State x = [SOC, V_rc, R0]. Current is discharge-positive; the measurement is
    V = OCV(SOC) - I*R0 - V_rc.

Usage: python ground/ref/ekf_ref.py DIR   (DIR holds ekf_config.json, ekf_trace.csv)
"""

import json
import sys
from pathlib import Path

import numpy as np


class EkfRef:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ocv_V = np.array(cfg["ocv_cell_V"]) * cfg["cells_in_series"]
        self.x = np.array(cfg["initial_x"], dtype=float)
        self.P = np.diag(np.square(cfg["sigma0"]))
        self.Q = np.diag(cfg["q"])
        self.rejections = 0
        self.consecutive_rejections = 0

    def _segment(self, soc):
        pos = soc * (len(self.ocv_V) - 1)  # end segments extend linearly outside 0..1
        i = min(max(int(np.floor(pos)), 0), len(self.ocv_V) - 2)
        return i, pos - i

    def ocv(self, soc):
        i, frac = self._segment(soc)
        return self.ocv_V[i] + frac * (self.ocv_V[i + 1] - self.ocv_V[i])

    def ocv_slope(self, soc):
        i, _ = self._segment(soc)
        return (self.ocv_V[i + 1] - self.ocv_V[i]) * (len(self.ocv_V) - 1)

    def measure(self, x, current_A):
        return self.ocv(x[0]) - current_A * x[2] - x[1]

    def jacobian(self, x, current_A):
        return np.array([self.ocv_slope(x[0]), -1.0, -current_A])

    def predict(self, current_A, dt_s):
        c = self.cfg
        a = np.exp(-dt_s / (c["r1_ohm"] * c["c1_F"]))
        self.x[0] -= current_A * dt_s / c["capacity_C"]
        self.x[1] = a * self.x[1] + c["r1_ohm"] * (1.0 - a) * current_A
        F = np.diag([1.0, a, 1.0])
        self.P = F @ self.P @ F.T + self.Q * dt_s

    def update(self, current_A, voltage_V):
        """Returns False if the NIS gate rejected the measurement."""
        c = self.cfg
        H = self.jacobian(self.x, current_A)
        innovation = voltage_V - self.measure(self.x, current_A)
        S = H @ self.P @ H + c["r_V2"]
        self.nis = innovation**2 / S

        if self.nis > c["nis_gate"]:
            if self.consecutive_rejections < c["max_consecutive_rejections"]:
                self.rejections += 1
                self.consecutive_rejections += 1
                return False
            self.P[2, 2] += c["reopen_r0_sigma_ohm"] ** 2
            S = H @ self.P @ H + c["r_V2"]
        self.consecutive_rejections = 0

        # Iterated EKF: Gauss-Newton steps relinearising about the latest estimate.
        prior, xi = self.x.copy(), self.x.copy()
        for _ in range(c["update_iterations"]):
            H = self.jacobian(xi, current_A)
            K = self.P @ H / (H @ self.P @ H + c["r_V2"])
            xi = prior + K * (voltage_V - self.measure(xi, current_A) - H @ (prior - xi))
        self.x = xi
        I_KH = np.eye(3) - np.outer(K, H)
        self.P = I_KH @ self.P @ I_KH.T + np.outer(K, K) * c["r_V2"]  # Joseph form
        return True


def run(cfg, dt_s, current_A, voltage_V):
    """Runs the filter over a trace. Returns (states N x 3, nis, accepted, rejections)."""
    ekf = EkfRef(cfg)
    states = np.empty((len(dt_s), 3))
    nis = np.empty(len(dt_s))
    accepted = np.empty(len(dt_s), dtype=bool)
    for k in range(len(dt_s)):
        if k > 0:
            ekf.predict(current_A[k - 1], dt_s[k])
        accepted[k] = ekf.update(current_A[k], voltage_V[k])
        states[k] = ekf.x
        nis[k] = ekf.nis
    return states, nis, accepted, ekf.rejections


def load_trace(directory):
    directory = Path(directory)
    cfg = json.loads((directory / "ekf_config.json").read_text())
    trace = np.genfromtxt(directory / "ekf_trace.csv", delimiter=",", names=True)
    return cfg, trace


def main():
    cfg, trace = load_trace(sys.argv[1])
    states, _, _, rejections = run(cfg, trace["dt_s"], trace["current_A"], trace["voltage_V"])
    cpp = np.column_stack([trace["soc"], trace["v_rc_V"], trace["r0_ohm"]])
    print(f"max |C++ - reference| per state: {np.abs(states - cpp).max(axis=0)}")
    print(f"rejections: {rejections}")


if __name__ == "__main__":
    main()
