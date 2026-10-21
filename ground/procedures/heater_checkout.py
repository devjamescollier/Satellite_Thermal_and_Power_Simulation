"""Battery heater checkout: proves the heater, its thermostat and setpoint commanding work.

1. FSW is NOMINAL and sending telemetry; record the battery temperature.
2. An invalid setpoint pair is rejected (NACK BAD_ARGUMENT).
3. Setpoints raised above the battery temperature: the heater turns on and the battery
   warms by HEATING_K.
4. Default setpoints restored: the heater turns off.

Usage: uv run python ground/procedures/heater_checkout.py   (needs FSW and sim running)
Writes docs/reports/heater_checkout.md. Exit status 0 = pass, 1 = fail.
"""

import struct

from procedure import Procedure, temps

import params

HEATING_K = 1.5  # the 5 W heater adds ~4 K in 900 s; the orbit alone swings ~2.5 K


def setpoints(on_below_K, off_above_K):
    return struct.pack(">2f", on_below_K, off_above_K)


def battery_K(hk):
    return hk["thermistor_K"]["battery"]


def checkout(p):
    hk = p.wait_for("Telemetry flowing, FSW in NOMINAL", lambda h: h["mode"] == "NOMINAL", 60,
                    lambda h: f"mode {h['mode']}, battery {battery_K(h):.1f} K")
    start_K = battery_K(hk)
    p.send("Invalid setpoints rejected (on above off)", "SET_HEATER_SETPOINTS",
           setpoints(300.0, 290.0), expect="CMD_NACK", reason="BAD_ARGUMENT")

    on_K = min(start_K + 10.0, params.P["setpoint_max_K"] - 5.0)
    p.send(f"Raise setpoints to {on_K:.1f} / {on_K + 5:.1f} K", "SET_HEATER_SETPOINTS",
           setpoints(on_K, on_K + 5.0))
    p.wait_for("Heater on, setpoints echoed in housekeeping",
               lambda h: h["heater_on"] and abs(h["heater_on_below_K"] - on_K) < 0.01, 60,
               lambda h: f"heater {'on' if h['heater_on'] else 'off'}, "
                         f"on below {h['heater_on_below_K']:.1f} K")
    p.wait_for(f"Battery warms by {HEATING_K} K", lambda h: battery_K(h) >= start_K + HEATING_K,
               1500, lambda h: f"battery {battery_K(h):.1f} K (started {start_K:.1f} K)",
               fail_if=lambda h: not h["heater_on"])

    default_on, default_off = params.P["heater_on_below_K"], params.P["heater_off_above_K"]
    p.send(f"Restore default setpoints {default_on:.2f} / {default_off:.2f} K",
           "SET_HEATER_SETPOINTS", setpoints(default_on, default_off))
    p.wait_for("Heater off at default setpoints",
               lambda h: not h["heater_on"] and abs(h["heater_on_below_K"] - default_on) < 0.01,
               600, lambda h: f"heater {'on' if h['heater_on'] else 'off'}; {temps(h)}")


if __name__ == "__main__":
    Procedure("heater_checkout", "Battery heater checkout").run(checkout)
