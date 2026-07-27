"""CCSDS Space Packet encoding and decoding for the ground segment.

Decoding raises ValueError, KeyError, IndexError or struct.error on a bad packet (DECODE_ERRORS).

Mirrors common/ccsds.hpp and common/messages.hpp. Layouts are in docs/icd.md.
"""

import math
import struct

APID_HOUSEKEEPING = 0x10
APID_ESTIMATOR = 0x11
APID_EVENTS = 0x12
APID_SIM_TRUTH = 0x20  # SIM-ONLY ground truth, not flight data
APID_COMMAND = 0x30

NODES = ("array", "structure", "battery", "avionics", "radiator")
MODES = ("NOMINAL", "LOAD_SHED", "SAFE")
OPCODES = {"NOOP": 0, "SET_MODE": 1, "PAYLOAD_ON": 2, "PAYLOAD_OFF": 3, "SET_HEATER_SETPOINTS": 4}
OPCODE_NAMES = {v: k for k, v in OPCODES.items()}
EVENT_TYPES = {1: "MODE_CHANGE", 2: "CMD_ACK", 3: "CMD_NACK", 4: "BATTERY_DEGRADED",
               5: "RADIATOR_DEGRADED"}
MODE_REASONS = {
    1: "SOC_LOW",
    2: "SOC_CRITICAL",
    3: "RED_LIMIT",
    4: "GROUND_COMMAND",
    5: "SOC_RECOVERED",
}
NACK_REASONS = {
    0: "NONE",
    1: "MALFORMED",
    2: "UNKNOWN_OPCODE",
    3: "BAD_LENGTH",
    4: "BAD_ARGUMENT",
    5: "WRONG_MODE",
}

DECODE_ERRORS = (ValueError, KeyError, IndexError, struct.error)
HEADER = struct.Struct(">HHHIH")  # primary header + MET secondary header
HOUSEKEEPING = struct.Struct(">4B4f5f2f2H")
EVENT = struct.Struct(">4BH")
ESTIMATOR = struct.Struct(">8fIff")
SIM_TRUTH = struct.Struct(">4B5f4fI2f")


def encode_packet(apid, data, seq_count=0, met_s=0.0, is_command=False):
    packet_id = (0x1000 if is_command else 0) | 0x0800 | (apid & 0x7FF)
    whole_s = math.floor(met_s)
    subseconds = int((met_s - whole_s) * 65536)
    header = HEADER.pack(
        packet_id, 0xC000 | (seq_count & 0x3FFF), 6 + len(data) - 1, whole_s, subseconds
    )
    return header + bytes(data)


def encode_command(opcode, args=b"", seq_count=0):
    return encode_packet(APID_COMMAND, bytes([opcode]) + args, seq_count, is_command=True)


def decode_packet(packet):
    """Returns a dict with header fields and the decoded payload."""
    packet_id, seq, length, seconds, subseconds = HEADER.unpack_from(packet)
    if packet_id >> 13 != 0 or not packet_id & 0x0800 or len(packet) != 6 + length + 1:
        raise ValueError("malformed CCSDS packet")
    apid = packet_id & 0x7FF
    out = {
        "apid": apid,
        "is_command": bool(packet_id & 0x1000),
        "seq_count": seq & 0x3FFF,
        "met_s": seconds + subseconds / 65536,
    }
    out.update(decode_payload(apid, packet[HEADER.size :]))
    return out


def decode_payload(apid, data):
    if apid == APID_HOUSEKEEPING:
        return _housekeeping(HOUSEKEEPING.unpack(data))
    if apid == APID_ESTIMATOR:
        return _estimator(ESTIMATOR.unpack(data))
    if apid == APID_EVENTS:
        return _event(*EVENT.unpack(data))
    if apid == APID_SIM_TRUTH:
        return _sim_truth(SIM_TRUTH.unpack(data))
    return {"raw": data.hex()}


def _housekeeping(v):
    return {
        "type": "HOUSEKEEPING",
        "mode": MODES[v[0]],
        "heater_on": bool(v[1]),
        "payload_on": bool(v[2]),
        "sun_present": bool(v[3]),
        "battery_V": v[4],
        "battery_A": v[5],
        "array_A": v[6],
        "soc_est": v[7],
        "thermistor_K": dict(zip(NODES, v[8:13], strict=True)),
        "heater_on_below_K": v[13],
        "heater_off_above_K": v[14],
        "cmd_accepted": v[15],
        "cmd_rejected": v[16],
    }


def _estimator(v):
    return {
        "type": "ESTIMATOR",
        "soc": v[0],
        "v_rc_V": v[1],
        "r0_ohm": v[2],
        "sigma": {"soc": v[3], "v_rc_V": v[4], "r0_ohm": v[5]},
        "innovation_V": v[6],
        "nis": v[7],
        "rejections": v[8],
        "predicted_soc_exit": v[9],  # NaN outside eclipse or before one full eclipse
        "r0_ratio": v[10],  # r0 / nominal R0 at the battery thermistor temperature
    }


def _event(event_type, a, b, reason, cmd_seq):
    name = EVENT_TYPES.get(event_type, f"UNKNOWN_{event_type}")
    if name == "MODE_CHANGE":
        return {"type": name, "from": MODES[a], "to": MODES[b], "reason": MODE_REASONS[reason]}
    if name == "BATTERY_DEGRADED":
        return {"type": name, "r0_ratio": a / 10}
    if name == "RADIATOR_DEGRADED":
        return {"type": name, "excess_K": a / 10}
    return {
        "type": name,
        "opcode": OPCODE_NAMES.get(a, f"0x{a:02X}"),
        "cmd_seq": cmd_seq,
        "reason": NACK_REASONS.get(reason, str(reason)),
    }


def _sim_truth(v):
    return {
        "type": "SIM_TRUTH",
        "eclipse": bool(v[0]),
        "payload_on": bool(v[1]),
        "heater_on": bool(v[2]),
        "temp_K": dict(zip(NODES, v[4:9], strict=True)),
        "soc": v[9],
        "battery_V": v[10],
        "battery_A": v[11],
        "solar_W": v[12],
        "missed_cycles": v[13],
        "v_rc_V": v[14],  # EKF sign convention: V = OCV - I*R0 - V_rc, I discharge-positive
        "r0_ohm": v[15],
    }
