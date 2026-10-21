# SAFE mode recovery: PASS

Written by `ground/procedures/safe_mode_recovery.py` on 2026-10-21 17:47 UTC.
The procedure stops at the first failed step.

| # | Step | Result | MET (s) | Detail |
|---|---|---|---|---|
| 1 | Drill: command SAFE | PASS | 1002 | SET_MODE -> CMD_ACK |
| 2 | FSW in SAFE, payload off | PASS | 1003 | mode SAFE, payload off |
| 3 | Temperatures inside yellow limits | PASS | 1003 | array 305.2 K, structure 289.9 K, battery 290.2 K, avionics 294.6 K, radiator 283.8 K |
| 4 | Estimated SOC above 50% | PASS | 1003 | SOC 86.1% |
| 5 | Command NOMINAL | PASS | 1004 | SET_MODE -> CMD_ACK |
| 6 | FSW in NOMINAL | PASS | 1005 | mode NOMINAL |
| 7 | Command payload on | PASS | 1006 | PAYLOAD_ON -> CMD_ACK |
| 8 | Payload on | PASS | 1007 | payload on |
| 9 | Stable in NOMINAL for 600 s | PASS | 1607 | mode NOMINAL, SOC 89.2% after 599 s MET |
