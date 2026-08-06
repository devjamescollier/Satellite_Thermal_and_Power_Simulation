"""Decoded packets -> InfluxDB line protocol (ground/points.py)."""

import math
from pathlib import Path

import ccsds
import points

FIXTURE = Path(__file__).parent / "fixtures" / "housekeeping.bin"
T_NS = 1_700_000_000_123_456_789


def parse(line):
    """(measurement, tags, fields, time_ns) from one line-protocol string (no escapes)."""
    head, field_str, time_ns = line.split(" ")
    measurement, *tags = head.split(",")
    fields = dict(kv.split("=", 1) for kv in field_str.split(","))
    return measurement, dict(t.split("=") for t in tags), fields, int(time_ns)


def truth_packet(**overrides):
    v = dict(eclipse=1, payload=1, heater=0, temps=(250.0, 280.0, 290.0, 300.0, 260.0), soc=0.9,
             volts=15.8, amps=-1.5, solar=60.0, missed=2, v_rc=0.01, r0=0.08) | overrides
    data = ccsds.SIM_TRUTH.pack(v["eclipse"], v["payload"], v["heater"], 0, *v["temps"], v["soc"],
                                v["volts"], v["amps"], v["solar"], v["missed"], v["v_rc"], v["r0"])
    return ccsds.decode_packet(ccsds.encode_packet(ccsds.APID_SIM_TRUTH, data, 1, 42.0))


def estimator_packet(predicted):
    values = (0.75, 0.02, 0.11, 0.001, 0.002, 0.003, -0.004, 0.5, 6, predicted, 1.25)
    data = ccsds.ESTIMATOR.pack(*values)
    return ccsds.decode_packet(ccsds.encode_packet(ccsds.APID_ESTIMATOR, data, 3, 10.0))


def test_housekeeping_from_cpp_fixture():
    (line,) = points.packet_to_lines(ccsds.decode_packet(FIXTURE.read_bytes()), T_NS)
    measurement, tags, f, time_ns = parse(line)
    assert (measurement, tags, time_ns) == ("housekeeping", {"source": "fsw"}, T_NS)
    assert f["mode"] == "1i"  # LOAD_SHED as an integer the dashboard maps back to text
    assert (f["heater_on"], f["payload_on"], f["sun_present"]) == ("1i", "0i", "1i")
    assert float(f["T_battery_K"]) == 275.0 and float(f["T_radiator_K"]) == 260.5
    assert (f["cmd_accepted"], f["cmd_rejected"]) == ("3i", "1i")
    assert float(f["power_generated_W"]) == 15.5 * 0.5
    assert float(f["power_consumed_W"]) == 15.5 * (0.5 + 1.25)  # array minus battery charge


def test_estimator_sigma_band_and_nan_prediction():
    (line,) = points.packet_to_lines(estimator_packet(math.nan), T_NS)
    measurement, _, f, _ = parse(line)
    assert measurement == "estimator"
    assert "predicted_soc_exit" not in f  # NaN is omitted, InfluxDB cannot store it
    assert math.isclose(float(f["soc_minus_3sigma"]), 0.75 - 3 * 0.001, rel_tol=1e-6)
    assert math.isclose(float(f["soc_plus_3sigma"]), 0.75 + 3 * 0.001, rel_tol=1e-6)
    assert f["rejections"] == "6i"
    (line,) = points.packet_to_lines(estimator_packet(0.6875), T_NS)
    assert float(parse(line)[2]["predicted_soc_exit"]) == 0.6875


def test_truth_is_tagged_sim_only():
    (line,) = points.packet_to_lines(truth_packet(), T_NS)
    measurement, tags, f, _ = parse(line)
    assert (measurement, tags) == ("truth", {"source": "truth"})
    flags = (f["eclipse"], f["payload_on"], f["heater_on"], f["missed_cycles"])
    assert flags == ("1i", "1i", "0i", "2i")
    assert {k for k in f if k.startswith("T_")} == {f"T_{n}_K" for n in ccsds.NODES}


def test_events_have_type_tag_and_readable_detail():
    def event(*fields):
        packet = ccsds.encode_packet(ccsds.APID_EVENTS, ccsds.EVENT.pack(*fields), 5, 99.0)
        (line,) = points.packet_to_lines(ccsds.decode_packet(packet), T_NS)
        return line

    assert event(1, 0, 2, 3, 0).startswith("event,source=fsw,type=MODE_CHANGE ")
    assert 'detail="NOMINAL -> SAFE (RED_LIMIT)"' in event(1, 0, 2, 3, 0)
    assert 'detail="SET_MODE (seq 17) rejected: BAD_ARGUMENT"' in event(3, 1, 0, 4, 17)
    assert 'detail="NOOP (seq 18) accepted"' in event(2, 0, 0, 0, 18)
    assert 'detail="R0 at 2.0x nominal"' in event(4, 20, 0, 0, 0)
    assert 'detail="radiator orbit mean +3.3 K above prediction"' in event(5, 33, 0, 0, 0)
    assert event(5, 33, 0, 0, 0).startswith("event,source=fsw,type=RADIATOR_DEGRADED ")


def test_unknown_apid_writes_nothing():
    assert points.packet_to_lines({"apid": 0x7FF, "raw": ""}, T_NS) == []


def test_link_line_and_escaping():
    assert points.link_line("fsw", 3.0, 1, 0, 5) == (
        "link,source=fsw packet_rate_hz=3.0,seq_gaps=1i,decode_errors=0i 5"
    )
    line = points.line("m", {"a b": "x,y=z"}, {"s": 'say "hi"'}, 1)
    assert line == 'm,a\\ b=x\\,y\\=z s="say \\"hi\\"" 1'
