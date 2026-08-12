# Interface Control Document

All interfaces run over UDP on the loopback interface (127.0.0.1). Units are SI.
Temperatures are in Kelvin.

| Port | Direction | Content | Encoding |
|---|---|---|---|
| 5001 | sim → fsw | Sensor packet, once per 1 s sim step | Raw struct, host byte order |
| 5002 | fsw → sim | Actuator packet, one reply per sensor packet | Raw struct, host byte order |
| 6001 | fsw → ground | Telemetry: APIDs 0x10 (housekeeping), 0x11 (estimator), 0x12 (events) | CCSDS, big-endian |
| 6002 | ground → fsw | Telecommands: APID 0x30 | CCSDS, big-endian |
| 6003 | sim → ground | **Sim-only** truth: APID 0x20 | CCSDS, big-endian |

Source of truth: `common/messages.hpp`, `common/ccsds.hpp`, `common/params.hpp`, and the
encoders in `fsw/flight_software.cpp` and `sim/sensors.cpp`.
Python mirror: `ground/ccsds.py`.

## Internal bus (sim ↔ fsw)

The sim and FSW always run on the same machine, so these structs are sent as raw
bytes (little-endian on x86/ARM). Each struct is checked with a `static_assert` on its size.

### Sensor packet (80 bytes)

| Offset | Field | Type | Units | Notes |
|---|---|---|---|---|
| 0 | seq | u32 | — | Increments every step |
| 4 | sun_present | u32 | bool | Sun sensor |
| 8 | time_s | f64 | s | Sim time at end of step |
| 16 | battery_V | f64 | V | Pack terminal voltage (noise σ = 10 mV) |
| 24 | battery_A | f64 | A | Positive = charging (noise σ = 10 mA) |
| 32 | array_A | f64 | A | Solar array current into the bus |
| 40 | thermistor_K[0] | f64 | K | Array |
| 48 | thermistor_K[1] | f64 | K | Structure |
| 56 | thermistor_K[2] | f64 | K | Battery |
| 64 | thermistor_K[3] | f64 | K | Avionics |
| 72 | thermistor_K[4] | f64 | K | Radiator |

Each thermistor reading is the true temperature plus Gaussian noise (σ = 0.1 K, seeded),
quantized to 0.1 K. Voltage and current carry Gaussian noise from the same seeded generator.

### Actuator packet (8 bytes)

| Offset | Field | Type | Units | Notes |
|---|---|---|---|---|
| 0 | seq | u32 | — | Echoes the sensor packet being answered |
| 4 | heater_on | u8 | bool | Battery heater (5 W) |
| 5 | payload_on | u8 | bool | Payload (15 W) |
| 6 | spare | u8[2] | — | Zero |

The sim waits up to 0.2 s for the matching reply. If none arrives, it keeps the
previous actuator state and counts a missed cycle.

## CCSDS Space Packets

The format follows CCSDS 133.0-B. All multi-byte fields are big-endian, and floats are
IEEE-754 binary32. The offsets below are measured from the start of the packet.

### Primary header (6 bytes)

| Offset | Bits | Field | Value |
|---|---|---|---|
| 0 | 15–13 | Version | 0 |
| 0 | 12 | Type | 0 = telemetry, 1 = telecommand |
| 0 | 11 | Secondary header flag | 1 |
| 0 | 10–0 | APID | See below |
| 2 | 15–14 | Sequence flags | 0b11 (unsegmented) |
| 2 | 13–0 | Sequence count | Per APID, wraps at 16384 |
| 4 | 15–0 | Data length | Bytes after the primary header, minus 1 |

### Secondary header: mission elapsed time (6 bytes)

| Offset | Field | Type | Units |
|---|---|---|---|
| 6 | met_seconds | u32 | s |
| 10 | met_subseconds | u16 | 1/65536 s |

MET is sim time, taken from the most recent sensor packet. Telecommands may leave it as 0.

### APID 0x10: Housekeeping (64 bytes total, once per cycle)

| Offset | Field | Type | Units | Notes |
|---|---|---|---|---|
| 12 | mode | u8 | enum | 0 NOMINAL, 1 LOAD_SHED, 2 SAFE |
| 13 | heater_on | u8 | bool | Commanded heater state |
| 14 | payload_on | u8 | bool | Commanded payload state |
| 15 | sun_present | u8 | bool | |
| 16 | battery_V | f32 | V | |
| 20 | battery_A | f32 | A | Positive = charging |
| 24 | array_A | f32 | A | |
| 28 | soc_est | f32 | 0–1 | EKF SOC estimate (same as APID 0x11 soc) |
| 32 | thermistor_array_K | f32 | K | |
| 36 | thermistor_structure_K | f32 | K | |
| 40 | thermistor_battery_K | f32 | K | |
| 44 | thermistor_avionics_K | f32 | K | |
| 48 | thermistor_radiator_K | f32 | K | |
| 52 | heater_on_below_K | f32 | K | Thermostat setpoint |
| 56 | heater_off_above_K | f32 | K | Thermostat setpoint |
| 60 | cmd_accepted | u16 | count | |
| 62 | cmd_rejected | u16 | count | |

### APID 0x11: Battery estimator (56 bytes total, once per cycle)

Battery EKF state after this cycle's update. The EKF uses its own sign convention:
current is discharge-positive, and V = OCV(SOC) − I·R0 − V_rc.

| Offset | Field | Type | Units | Notes |
|---|---|---|---|---|
| 12 | soc | f32 | 0–1 | |
| 16 | v_rc | f32 | V | RC-branch voltage, EKF convention |
| 20 | r0 | f32 | Ω | Internal resistance |
| 24 | sigma_soc | f32 | 0–1 | √P₀₀ |
| 28 | sigma_v_rc | f32 | V | √P₁₁ |
| 32 | sigma_r0 | f32 | Ω | √P₂₂ |
| 36 | innovation | f32 | V | Measured − predicted voltage, before update |
| 40 | nis | f32 | — | innovation² / S; gated at 10.828 (χ², 1 dof, 99.9%) |
| 44 | rejections | u32 | count | Total measurements rejected by the NIS gate |
| 48 | predicted_soc_exit | f32 | 0–1 | Predicted SOC at eclipse exit; NaN in sunlight or before one full eclipse has been seen |
| 52 | r0_ratio | f32 | — | r0 ÷ nominal R0 at the battery thermistor reading. ≈ 1 when healthy; the degradation monitor flags > 1.5 held for 600 s |

### APID 0x12: Events and command acknowledgements (18 bytes total)

| Offset | Field | Type | MODE_CHANGE | CMD_ACK / CMD_NACK |
|---|---|---|---|---|
| 12 | type | u8 | 1 | 2 = ACK, 3 = NACK |
| 13 | a | u8 | Previous mode | Opcode (0xFF if the packet was unreadable) |
| 14 | b | u8 | New mode | 0 |
| 15 | reason | u8 | Mode reason | Nack reason (0 for an ACK) |
| 16 | cmd_seq | u16 | 0 | Sequence count of the command |

BATTERY_DEGRADED (type 4) fires once each time the estimated R0 stays above 1.5× the
temperature-corrected nominal value for 10 minutes. Its fields are: a = R0 / nominal in
tenths (for example 19 means 1.9×), b = 0, reason = 0, cmd_seq = 0.

RADIATOR_DEGRADED (type 5) fires once each time an orbit's mean radiator temperature (eclipse
entry to eclipse entry) exceeds the expected 284.80 K by more than 2.5 K. Its fields are:
a = the excess in tenths of a kelvin, capped at 255 (for example 33 means +3.3 K), b = 0,
reason = 0, cmd_seq = 0. It re-arms after an orbit back inside the margin.

Mode reasons: 1 SOC_LOW, 2 SOC_CRITICAL, 3 RED_LIMIT, 4 GROUND_COMMAND, 5 SOC_RECOVERED.

Nack reasons: 1 MALFORMED, 2 UNKNOWN_OPCODE, 3 BAD_LENGTH, 4 BAD_ARGUMENT, 5 WRONG_MODE.

### APID 0x20: Sim truth (64 bytes total), SIM-ONLY

The simulator sends this packet so ground tools can compare FSW estimates with the true state.
It does not exist on a real spacecraft, and the FSW never sees it.

| Offset | Field | Type | Units |
|---|---|---|---|
| 12 | eclipse | u8 | bool |
| 13 | payload_on | u8 | bool (applied load state) |
| 14 | heater_on | u8 | bool (applied load state) |
| 15 | spare | u8 | — |
| 16 | temp_array_K | f32 | K |
| 20 | temp_structure_K | f32 | K |
| 24 | temp_battery_K | f32 | K |
| 28 | temp_avionics_K | f32 | K |
| 32 | temp_radiator_K | f32 | K |
| 36 | soc | f32 | 0–1 (true) |
| 40 | battery_V | f32 | V |
| 44 | battery_A | f32 | A |
| 48 | solar_W | f32 | W |
| 52 | missed_cycles | u32 | count |
| 56 | v_rc | f32 | V (true RC voltage, EKF convention: positive when discharging) |
| 60 | r0 | f32 | Ω (true internal resistance used this step, including faults) |

Battery state (soc, v_rc) is taken after the step. r0, battery_V, battery_A and solar_W
are the values used during the step.

### APID 0x30: Telecommands

Every telecommand has the type bit set. User data starts with a one-byte opcode at offset 12.
Every command is answered with a CMD_ACK or CMD_NACK event on APID 0x12.

| Opcode | Name | Arguments (offset: type) | Total bytes | Nacks |
|---|---|---|---|---|
| 0 | NOOP | — | 13 | BAD_LENGTH |
| 1 | SET_MODE | 13: u8 mode (0–2) | 14 | BAD_LENGTH, BAD_ARGUMENT |
| 2 | PAYLOAD_ON | — | 13 | BAD_LENGTH, WRONG_MODE (only allowed in NOMINAL) |
| 3 | PAYLOAD_OFF | — | 13 | BAD_LENGTH |
| 4 | SET_HEATER_SETPOINTS | 13: f32 on_below_K, 17: f32 off_above_K | 21 | BAD_LENGTH, BAD_ARGUMENT (needs on < off, 253.15 ≤ on, off ≤ 313.15) |

A packet with the wrong APID, the type bit clear, or a bad header is nacked as MALFORMED.
