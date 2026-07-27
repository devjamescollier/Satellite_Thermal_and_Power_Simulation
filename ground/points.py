"""Decoded CCSDS packets -> InfluxDB line protocol.

One measurement per packet type, tagged source=fsw (flight telemetry) or
source=truth (sim-only). Flags are stored as 0/1 integers so dashboards and
alerts can average and compare them. NaN fields are omitted (InfluxDB has no NaN).
"""

import math

import ccsds
import params


def _field_value(v):
    if isinstance(v, bool):
        return f"{int(v)}i"
    if isinstance(v, int):
        return f"{v}i"
    if isinstance(v, float):
        return repr(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _escape_tag(v):
    return str(v).replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")


def line(measurement, tags, fields, time_ns):
    fields = {k: v for k, v in fields.items() if not (isinstance(v, float) and math.isnan(v))}
    tag_str = "".join(f",{_escape_tag(k)}={_escape_tag(v)}" for k, v in sorted(tags.items()))
    field_str = ",".join(f"{k}={_field_value(v)}" for k, v in fields.items())
    return f"{measurement}{tag_str} {field_str} {time_ns}"


def _temps(prefix_dict):
    return {f"T_{node}_K": t for node, t in prefix_dict.items()}


def expected_load_W(p):
    """Load power the commanded states account for."""
    P = params.P
    return P["avionics_W"] + P["payload_W"] * p["payload_on"] + P["heater_W"] * p["heater_on"]


def housekeeping_fields(p):
    v, i_array, i_batt = p["battery_V"], p["array_A"], p["battery_A"]
    consumed_W = v * (i_array - i_batt)  # array power not going into the battery
    return {
        "met_s": p["met_s"],
        "mode": ccsds.MODES.index(p["mode"]),
        "heater_on": p["heater_on"],
        "payload_on": p["payload_on"],
        "sun_present": p["sun_present"],
        "battery_V": v,
        "battery_A": i_batt,
        "array_A": i_array,
        "soc_est": p["soc_est"],
        **_temps(p["thermistor_K"]),
        "heater_on_below_K": p["heater_on_below_K"],
        "heater_off_above_K": p["heater_off_above_K"],
        "cmd_accepted": p["cmd_accepted"],
        "cmd_rejected": p["cmd_rejected"],
        "power_generated_W": v * i_array,
        # In sunlight with a full battery this includes power shunted off the array.
        "power_consumed_W": consumed_W,
        # Eclipse only (no array, no shunt): measured load minus what commands explain.
        "load_excess_W": math.nan if p["sun_present"] else consumed_W - expected_load_W(p),
    }


def estimator_fields(p):
    s = p["sigma"]
    return {
        "met_s": p["met_s"],
        "soc": p["soc"],
        "soc_minus_3sigma": p["soc"] - 3 * s["soc"],
        "soc_plus_3sigma": p["soc"] + 3 * s["soc"],
        "v_rc_V": p["v_rc_V"],
        "r0_ohm": p["r0_ohm"],
        "sigma_soc": s["soc"],
        "sigma_v_rc_V": s["v_rc_V"],
        "sigma_r0_ohm": s["r0_ohm"],
        "innovation_V": p["innovation_V"],
        "nis": p["nis"],
        "rejections": p["rejections"],
        "predicted_soc_exit": p["predicted_soc_exit"],
        "r0_ratio": p["r0_ratio"],
    }


def event_detail(p):
    t = p["type"]
    if t == "MODE_CHANGE":
        return f"{p['from']} -> {p['to']} ({p['reason']})"
    if t == "BATTERY_DEGRADED":
        return f"R0 at {p['r0_ratio']:.1f}x nominal"
    if t == "RADIATOR_DEGRADED":
        return f"radiator orbit mean {p['excess_K']:+.1f} K above prediction"
    verdict = "accepted" if t == "CMD_ACK" else f"rejected: {p['reason']}"
    return f"{p['opcode']} (seq {p['cmd_seq']}) {verdict}"


def truth_fields(p):
    return {
        "met_s": p["met_s"],
        "eclipse": p["eclipse"],
        "payload_on": p["payload_on"],
        "heater_on": p["heater_on"],
        **_temps(p["temp_K"]),
        "soc": p["soc"],
        "battery_V": p["battery_V"],
        "battery_A": p["battery_A"],
        "solar_W": p["solar_W"],
        "missed_cycles": p["missed_cycles"],
        "v_rc_V": p["v_rc_V"],
        "r0_ohm": p["r0_ohm"],
    }


def packet_to_points(p):
    """(measurement, tags, fields) for one decoded packet (empty for unknown APIDs)."""
    apid = p["apid"]
    if apid == ccsds.APID_HOUSEKEEPING:
        return [("housekeeping", {"source": "fsw"}, housekeeping_fields(p))]
    if apid == ccsds.APID_ESTIMATOR:
        return [("estimator", {"source": "fsw"}, estimator_fields(p))]
    if apid == ccsds.APID_EVENTS:
        fields = {"met_s": p["met_s"], "detail": event_detail(p)}
        return [("event", {"source": "fsw", "type": p["type"]}, fields)]
    if apid == ccsds.APID_SIM_TRUTH:
        return [("truth", {"source": "truth"}, truth_fields(p))]
    return []


def packet_to_lines(p, time_ns):
    """Line-protocol strings for one decoded packet."""
    return [line(m, tags, fields, time_ns) for m, tags, fields in packet_to_points(p)]


def link_line(source, packet_rate_hz, seq_gaps, decode_errors, time_ns):
    fields = {
        "packet_rate_hz": packet_rate_hz,
        "seq_gaps": seq_gaps,
        "decode_errors": decode_errors,
    }
    return line("link", {"source": source}, fields, time_ns)
