"""Constants read straight from common/params.hpp, the project's single source of truth.

Only the simple forms used there are parsed:
    inline constexpr <type> name = value;
    inline constexpr double name[kNumNodes] = {a, b, ...};
"""

import re
from pathlib import Path

PARAMS_HPP = Path(__file__).resolve().parent.parent / "common" / "params.hpp"
NODES = ("array", "structure", "battery", "avionics", "radiator")  # order of enum Node

_SCALAR = re.compile(r"inline constexpr \w+ (\w+) = ([-\d.e+]+);")
_ARRAY = re.compile(r"inline constexpr \w+ (\w+)\[\w+\] = \{([^}]*)\};")


def load(path=PARAMS_HPP):
    text = path.read_text()
    values = {name: float(v) for name, v in _SCALAR.findall(text)}
    for name, body in _ARRAY.findall(text):
        values[name] = [float(v) for v in body.split(",")]
    return values


P = load()
PORT_TELEMETRY = int(P["port_telemetry"])
PORT_TELECOMMANDS = int(P["port_telecommands"])
PORT_SIM_TRUTH = int(P["port_sim_truth"])
PORT_GROUND_RELAY = int(P["port_ground_relay"])
NIS_GATE = P["ekf_nis_gate"]
PREDICTED_SOC_ALERT = P["predicted_soc_alert"]

# Per node: (red_low, yellow_low, yellow_high, red_high) in Kelvin.
LIMITS_K = {
    node: tuple(P[k][i] for k in ("red_low_K", "yellow_low_K", "yellow_high_K", "red_high_K"))
    for i, node in enumerate(NODES)
}
