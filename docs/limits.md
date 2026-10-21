# Temperature and alert limits

Generated from `common/params.hpp` and `ground/alerts.py` by `tools/gen_grafana.py`.
Do not edit by hand. The Grafana thresholds and alert rules come from the same values,
and `tests/test_grafana.py` checks that everything matches.

| Node | Red low | Yellow low | Yellow high | Red high |
|---|---|---|---|---|
| array | 150.00 K (-123.1 °C) | 170.00 K (-103.1 °C) | 380.00 K (+106.9 °C) | 400.00 K (+126.9 °C) |
| structure | 240.00 K (-33.1 °C) | 250.00 K (-23.1 °C) | 320.00 K (+46.9 °C) | 330.00 K (+56.9 °C) |
| battery | 268.15 K (-5.0 °C) | 273.15 K (+0.0 °C) | 313.15 K (+40.0 °C) | 318.15 K (+45.0 °C) |
| avionics | 243.15 K (-30.0 °C) | 253.15 K (-20.0 °C) | 333.15 K (+60.0 °C) | 343.15 K (+70.0 °C) |
| radiator | 200.00 K (-73.1 °C) | 210.00 K (-63.1 °C) | 320.00 K (+46.9 °C) | 330.00 K (+56.9 °C) |

- **Red**: the flight software goes to SAFE (any thermistor sample outside), and Grafana
  raises "Red-limit violation".
- **Yellow**: shown on the dashboard only (the yellow bands on each temperature panel).

## Alert rules

Grafana evaluates every rule each 10 s over a window ending
now (wall-clock seconds, sized for the 60x demo speed). `tools/fault_campaign.py`
evaluates the same rules on recorded telemetry.

| Alert | Severity | Fires when | Window |
|---|---|---|---|
| Red-limit violation | critical | any thermistor sample outside its red limits | 30 s |
| Predicted SOC at eclipse exit below 30% | critical | last of `estimator.predicted_soc_exit` < 0.3 | 30 s |
| FSW entered SAFE | critical | last of `housekeeping.mode` > 1.5 | 30 s |
| NIS above 10.828 for 30 consecutive samples | warning | more than 29 samples in a row with NIS > 10.828 | 60 s |
| No telemetry for 30 s | critical | count of `housekeeping.soc_est` < 1 | 30 s |
| FSW reported BATTERY_DEGRADED | warning | count of `event.met_s` (type = BATTERY_DEGRADED) > 0 | 300 s |
| FSW reported RADIATOR_DEGRADED | warning | count of `event.met_s` (type = RADIATOR_DEGRADED) > 0 | 300 s |
| Eclipse load 2 W above commanded loads | warning | mean of `housekeeping.load_excess_W` > 2 | 120 s |
| Battery R0 above 1.2x nominal for its temperature | warning | mean of `estimator.r0_ratio` > 1.2 | 60 s |
