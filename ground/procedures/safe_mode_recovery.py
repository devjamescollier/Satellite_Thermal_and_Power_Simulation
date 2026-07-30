"""SAFE mode recovery: returns the spacecraft from SAFE to NOMINAL once it is safe to do so.

1. FSW is in SAFE with the payload off (with --drill, command SAFE first).
2. Preconditions: every temperature inside its yellow limits, estimated SOC above the
   LOAD_SHED exit threshold. If either fails, stop: stay in SAFE and investigate.
3. Command NOMINAL, then payload on; confirm both in housekeeping.
4. Watch STABLE_S of mission time: FSW must stay NOMINAL.

Usage: uv run python ground/procedures/safe_mode_recovery.py [--drill]
Writes docs/reports/safe_mode_recovery.md. Exit status 0 = pass, 1 = fail.
"""

import argparse

from procedure import Procedure, temps

import ccsds
import params

STABLE_S = 600.0


def outside_yellow(hk):
    return [n for n, t in hk["thermistor_K"].items()
            if not params.LIMITS_K[n][1] <= t <= params.LIMITS_K[n][2]]


def recovery(p, drill):
    if drill:
        p.send("Drill: command SAFE", "SET_MODE", bytes([ccsds.MODES.index("SAFE")]))
    hk = p.wait_for("FSW in SAFE, payload off",
                    lambda h: h["mode"] == "SAFE" and not h["payload_on"], 60,
                    lambda h: f"mode {h['mode']}, payload {'on' if h['payload_on'] else 'off'}")

    hot_or_cold = outside_yellow(hk)
    p.check("Temperatures inside yellow limits", not hot_or_cold,
            f"outside: {', '.join(hot_or_cold)}; stay in SAFE" if hot_or_cold else temps(hk))
    exit_soc = params.P["load_shed_exit_soc"]
    p.check(f"Estimated SOC above {exit_soc:.0%}", hk["soc_est"] > exit_soc,
            f"SOC {hk['soc_est']:.1%}" + ("" if hk["soc_est"] > exit_soc else "; wait to charge"))

    p.send("Command NOMINAL", "SET_MODE", bytes([ccsds.MODES.index("NOMINAL")]))
    p.wait_for("FSW in NOMINAL", lambda h: h["mode"] == "NOMINAL", 60,
               lambda h: f"mode {h['mode']}")
    p.send("Command payload on", "PAYLOAD_ON")
    hk = p.wait_for("Payload on", lambda h: h["payload_on"], 60,
                    lambda h: f"payload {'on' if h['payload_on'] else 'off'}")
    start_s = hk["met_s"]
    p.wait_for(f"Stable in NOMINAL for {STABLE_S:.0f} s",
               lambda h: h["met_s"] - start_s >= STABLE_S, STABLE_S + 60,
               lambda h: f"mode {h['mode']}, SOC {h['soc_est']:.1%}",
               fail_if=lambda h: h["mode"] != "NOMINAL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--drill", action="store_true", help="command SAFE first (training)")
    args = parser.parse_args()
    Procedure("safe_mode_recovery", "SAFE mode recovery").run(lambda p: recovery(p, args.drill))
