# Battery heater checkout: PASS

Written by `ground/procedures/heater_checkout.py` on 2026-10-21 16:58 UTC.
The procedure stops at the first failed step.

| # | Step | Result | MET (s) | Detail |
|---|---|---|---|---|
| 1 | Telemetry flowing, FSW in NOMINAL | PASS | 184 | mode NOMINAL, battery 290.2 K |
| 2 | Invalid setpoints rejected (on above off) | PASS | 185 | SET_HEATER_SETPOINTS -> CMD_NACK BAD_ARGUMENT |
| 3 | Raise setpoints to 300.2 / 305.2 K | PASS | 187 | SET_HEATER_SETPOINTS -> CMD_ACK |
| 4 | Heater on, setpoints echoed in housekeeping | PASS | 188 | heater on, on below 300.2 K |
| 5 | Battery warms by 1.5 K | PASS | 401 | battery 291.7 K (started 290.2 K) after 212 s MET |
| 6 | Restore default setpoints 278.15 / 283.15 K | PASS | 402 | SET_HEATER_SETPOINTS -> CMD_ACK |
| 7 | Heater off at default setpoints | PASS | 403 | heater off; array 300.4 K, structure 289.8 K, battery 291.4 K, avionics 293.0 K, radiator 283.3 K |
