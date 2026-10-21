"""Ground-side decoding tests. The fixture is written by the C++ encoder
(test_fsw: Ccsds.WritesHousekeepingFixture), so these check both sides agree."""

from pathlib import Path

import pytest

import ccsds

FIXTURE = Path(__file__).parent / "fixtures" / "housekeeping.bin"


def test_decodes_cpp_housekeeping_fixture():
    p = ccsds.decode_packet(FIXTURE.read_bytes())
    assert p["apid"] == ccsds.APID_HOUSEKEEPING
    assert not p["is_command"]
    assert p["seq_count"] == 7
    assert p["met_s"] == 123.5
    assert p["mode"] == "LOAD_SHED"
    assert (p["heater_on"], p["payload_on"], p["sun_present"]) == (True, False, True)
    assert (p["battery_V"], p["battery_A"], p["array_A"], p["soc_est"]) == (15.5, -1.25, 0.5, 0.375)
    assert list(p["thermistor_K"].values()) == [280.5, 290.25, 275.0, 300.0, 260.5]
    assert (p["heater_on_below_K"], p["heater_off_above_K"]) == (278.0, 283.0)
    assert (p["cmd_accepted"], p["cmd_rejected"]) == (3, 1)


def test_command_round_trip():
    packet = ccsds.encode_command(ccsds.OPCODES["SET_MODE"], bytes([2]), seq_count=42)
    assert packet[0] == 0x18  # version 0, telecommand, secondary header, APID 0x30
    p = ccsds.decode_packet(packet)
    assert (p["apid"], p["is_command"], p["seq_count"]) == (ccsds.APID_COMMAND, True, 42)
    assert p["raw"] == "0102"


def test_decodes_estimator_packet():
    values = (0.75, 0.02, 0.11, 0.001, 0.002, 0.003, -0.004, 0.5, 6, 0.6875, 1.25)
    data = ccsds.ESTIMATOR.pack(*values)
    p = ccsds.decode_packet(ccsds.encode_packet(ccsds.APID_ESTIMATOR, data, 3, 10.0))
    assert p["type"] == "ESTIMATOR"
    assert (p["soc"], p["rejections"], p["predicted_soc_exit"]) == (0.75, 6, 0.6875)
    assert p["r0_ratio"] == 1.25
    assert set(p["sigma"]) == {"soc", "v_rc_V", "r0_ohm"}


def test_rejects_truncated_packet():
    with pytest.raises(ValueError):
        ccsds.decode_packet(FIXTURE.read_bytes()[:-1])
