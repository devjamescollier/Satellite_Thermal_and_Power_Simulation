# Requirements and verification

Verification methods: **T** = test (automated, runs in ctest or pytest), **A** = analysis
(a generated report with numbers), **D** = demonstration (a scripted end-to-end run).
C++ test names are `Suite.Name` in `tests/*.cpp`; Python tests are in `tests/*.py`.

| ID | Requirement | Method | Verified by |
|---|---|---|---|
| R-01 | The thermal model shall converge to the analytic radiative equilibrium of a flat plate in constant sunlight within 0.5 K. | T | `Thermal.FlatPlateReachesAnalyticEquilibrium` |
| R-02 | The orbit model's eclipse fraction shall match the analytic cylindrical-shadow value within 1% at β = 0°, 30° and 60°. | T | `Orbit.EclipseFractionMatchesAnalytic` |
| R-03 | The coupled simulation shall conserve energy: absorbed − radiated shall equal the change in stored thermal and battery energy within 0.5% of the absorbed energy over 5 orbits, with or without a radiator fault. | T | `Spacecraft.EnergyIsConservedOverFiveOrbits`, `Faults.RadiatorDegradationWarmsRadiatorAndConservesEnergy` |
| R-04 | With default parameters the spacecraft shall be power-positive: the battery shall reach full charge every orbit, and after 20 orbits temperatures shall repeat within 1 K and SOC within 1%. | T | `Spacecraft.DefaultConfigIsPowerPositiveAndPeriodic` |
| R-05 | The FSW shall keep the battery above 0 °C in nominal operation for 3 orbits. | T | `Integration.SimAndFswKeepBatteryAboveFreezingForThreeOrbits` |
| R-06 | The battery heater thermostat shall switch only outside its setpoint band, and the setpoints shall be commandable within 253.15–313.15 K. | T, D | `Fsw.ThermostatHysteresis`; [heater checkout report](reports/heater_checkout.md) |
| R-07 | The mode manager shall enter LOAD_SHED below 40% SOC, return to NOMINAL above 50%, enter SAFE below 25% SOC or on any red-limit thermistor reading, and leave SAFE only by ground command. | T, D | `Fsw.ModeTransitions`, `Fsw.SafeExitsOnlyByGroundCommand`; [SAFE recovery report](reports/safe_mode_recovery.md) |
| R-08 | Every telecommand shall be answered with an ACK, or a NACK giving the reason (malformed, unknown opcode, bad length, bad argument, wrong mode). | T, D | `Fsw.EveryCommandIsAckedOrNacked`; NACK step of the heater checkout |
| R-09 | Telemetry and telecommands shall follow `docs/icd.md`, and the Python ground segment shall decode exactly what the C++ encoders write. | T | `Ccsds.RoundTrip`, `Ccsds.WritesHousekeepingFixture` + `test_decodes_cpp_housekeeping_fixture`, `test_points.py` |
| R-10 | The battery EKF shall estimate SOC with an RMS error below 0.1% SOC after the first orbit (50-run Monte Carlo, ±15% initial error), and converge to within 2% within one orbit from a 20% initial error. | A, T | [Monte Carlo results](results/README.md) (0.034%); `Ekf.ConvergesFromTwentyPercentSocErrorWithinOneOrbit` |
| R-11 | The C++ EKF shall agree with an independent NumPy reference implementation within 1e-9 on every state, including NIS-gate rejections and a resistance fault. | T | `test_reference_matches_cpp_states`, `test_trace_exercises_gate_and_fault` |
| R-12 | The FSW shall raise BATTERY_DEGRADED when a cell's resistance doubles, with the R0 estimate within 5% of truth two orbits later, and shall reject single voltage spikes without changing its state. | T, A | `Ekf.DegradedCellR0ConvergesAndRaisesEvent`, `Ekf.NisGateRejectsVoltageSpike`; [degraded_cell report](anomalies/degraded_cell.md) |
| R-13 | Every injected fault shall raise a ground alert, and a fault-free 12-orbit run shall raise none: the degraded cell, stuck-on heater and biased battery thermistor within one orbit of mission time, and radiator degradation (which stays inside every temperature limit) within two orbits. | A, T | [Fault campaign results](anomalies/README.md) (0.21, 0.53, 0.53 and 1.27 orbits); `Fsw.RadiatorMonitorComparesOrbitMeansFromEclipseEntry`, `Integration.RadiatorDegradedOnlyWithTheFault` |
| R-14 | The ground segment shall store at least 99% of downlinked packets with no decode errors over a 2-orbit run, every dashboard panel shall return data, and every alert rule shall evaluate without error. | D, T | `scripts/smoke.sh` (runs `tools/check_grafana.py`); `test_station_writes_then_flushes_on_signal`, `test_grafana.py` |
