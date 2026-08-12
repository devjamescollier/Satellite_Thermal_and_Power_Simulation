# Design notes

How the simulator, flight software, estimator and ground segment work. Interfaces are in
[icd.md](icd.md); requirements and how each is verified are in
[requirements.md](requirements.md).

## Physics model

**Orbit.** 500 km circular orbit (period ≈ 5668 s) in a frame with the Sun on +x.
The orbit plane is tilted so the Sun vector makes the beta angle (default 30°) with it.
The spacecraft is in eclipse when it is behind Earth (`x < 0`) and within one Earth
radius of the Sun–Earth line.

**Thermal.** Five lumped nodes: solar array, structure, battery, avionics and radiator.
Each node obeys

    C·dT/dt = α·A_sun·S + Q_internal − ε·σ·A_rad·T⁴ + Σ G_ij·(T_j − T_i)

and is integrated with RK4 at 1 s steps. Heat inputs are held constant over each step.
The array radiates from both faces; the structure is MLI-wrapped (low effective ε);
battery and avionics are internal and lose heat only by conduction.

**Power.** The array always faces the Sun. Its efficiency is 28% at 25 °C and falls by
0.25%/K (relative) as it warms. The bus is the battery: solar power minus loads
charges or discharges a 4S2P Li-ion pack (6.8 Ah). The pack is a one-RC equivalent
circuit with:
- a table-interpolated open-circuit-voltage curve
- an R0 that rises when cold (Arrhenius, ≈2.5× at 0 °C)
- an R1‖C1 branch with τ = 30 s

The battery current comes from solving `P = (OCV + V_rc + I·R0)·I`. Loads are
avionics (8 W, always on), payload (15 W, on by default) and battery heater (5 W,
off by default).

**Where the energy goes.**
- Electrical power drawn from the array is subtracted from the array's heat.
- Avionics and payload power heat the avionics node.
- Heater power and battery I²R losses heat the battery node.
- When the battery is full, excess solar power is shunted as heat into the radiator.

With default parameters the battery cycles between 88% and 100% SOC each orbit.
Temperatures range from about 14–17 °C (battery), 19–27 °C (avionics) and
−66 to +34 °C (array).

## Simulator ↔ flight software loop

The two processes run in **lockstep**. On each 1 s step the simulator:
1. advances the physics,
2. sends a sensor packet (port 5001),
3. waits up to 0.2 s for the matching actuator packet (port 5002).

If the reply doesn't arrive in time, the simulator keeps the previous actuator states and counts
a missed cycle. `--speed` adds real-time pacing on top of this.

**Sensors.**
- Battery voltage and current
- Solar array current (solar power ÷ bus voltage)
- A sun-presence flag
- One thermistor per node: true temperature + Gaussian noise (σ = 0.1 K, fixed seed),
  quantized to 0.1 K

**Actuators.** Battery heater on/off and payload on/off.

**Flight software cycle.** Each cycle the FSW:
1. reads the sensors,
2. executes any queued telecommands,
3. runs the battery heater thermostat (on below 5 °C, off above 10 °C; both setpoints
   can be changed by command),
4. runs the mode manager,
5. sends the actuator packet,
6. sends housekeeping, estimator telemetry, and any events.

Step 4 also runs the battery estimator (see below).

| Mode | Payload | Entered when | Left when |
|---|---|---|---|
| NOMINAL | as commanded | start; ground command; SOC > 50% from LOAD_SHED | — |
| LOAD_SHED | off | SOC < 40% | SOC > 50%, or ground command |
| SAFE | off | SOC < 25%, or any thermistor outside its red limits | ground command only |

The mode manager uses the EKF's SOC estimate. Every mode change is logged as an event.

**Telemetry and telecommands** are CCSDS Space Packets: a 6-byte primary header plus a
6-byte mission-elapsed-time secondary header.

| APID | Content |
|---|---|
| 0x10 | Housekeeping |
| 0x11 | Battery estimator: state, √diag(P), innovation, NIS, rejections, predicted SOC at eclipse exit, R0 ÷ nominal |
| 0x12 | Events and command acks |
| 0x20 | Simulator truth, **sim-only**, sent directly by the sim |
| 0x30 | Telecommands: NOOP, SET_MODE, PAYLOAD_ON, PAYLOAD_OFF, SET_HEATER_SETPOINTS |

Every telecommand gets an ACK, or a NACK with a reason. Byte-level layouts are in
[icd.md](icd.md).

## Battery state estimator

`fsw/ekf.cpp` is an Extended Kalman Filter written with Eigen.

**Model.**
- State: x = [SOC, V_rc, R0]. R0 is modelled as a random walk.
- Input: measured battery current, discharge-positive.
- Measurement: terminal voltage, V = OCV(SOC) − I·R0 − V_rc.
- Prediction: coulomb counting for SOC, the exact discrete RC decay for V_rc, and R0 held
  constant (its random-walk noise covers slow changes).

**The filter deliberately uses wrong RC parameters.** Its R1 = 16.5 mΩ and C1 = 1800 F,
while the simulator uses 15 mΩ and 2000 F. If the filter used the simulator's exact model,
it would just replay the truth and the validation would show nothing. The ~10% mismatch
stands in for real parameter uncertainty, which the filter has to absorb through its process
noise. The OCV table and the nominal R0(T) curve *are* shared: they represent the cell
datasheet, which flight software would have.

**Design choices:**
- **Iterated update (IEKF, 5 Gauss-Newton steps).** The OCV curve is piecewise linear, so
  its slope jumps between table segments. A single linearisation started from a 15% SOC error
  uses the wrong segment and shrinks the SOC variance as if it had converged. The SOC/R0
  ambiguity during steady charging then locks in a 1–4% error for an orbit or more.
  With the same tuning, re-linearising during the update cut the Monte Carlo RMS SOC error
  after orbit 1 from 0.23% to 0.034%, and the worst case from 2.1% to 0.23%.
- **OCV extrapolation.** The end segments of the OCV table extend linearly instead of
  clamping. Otherwise SOC above 1.0 is unobservable, and a filter that starts high never
  comes down.
- **NIS gate.** A measurement with NIS > 10.83 (χ², 1 dof, 99.9%) is rejected and counted.
  After 5 rejections in a row the mismatch is treated as real rather than a spike. SOC is
  pinned by coulomb counting, so the likely cause is a resistance change: the filter
  widens R0's variance and accepts the measurement. A step fault therefore can't lock the
  filter out. An earlier version widened the whole covariance, and the filter blamed the
  degraded cell on SOC.

**Degradation monitor.** BATTERY_DEGRADED fires when the estimated R0 stays above 1.5× the
nominal value, temperature-corrected using the battery thermistor, for 10 minutes.

**Radiator monitor.** RADIATOR_DEGRADED fires when one orbit's mean radiator thermistor
reading (from eclipse entry to the next eclipse entry) exceeds the thermal prediction,
284.80 K, by more than 2.5 K. Real missions compare telemetry with thermal-analysis
predictions in the same way. The prediction is the fault-free steady state at the default
30° beta, where orbit means repeat within 0.02 K. The margin sits just above the largest
fault-free orbit-to-orbit change, 2.2 K during warm-up from the initial temperature.
Warm-up approaches from below, so no fault-free orbit exceeds the prediction by more than
0.01 K. A 40% emissivity loss settles about 22 K warmer while staying inside every limit;
limit checks alone would never see it.

**Eclipse-exit prediction.** During eclipse the FSW predicts the SOC at eclipse exit:

    predicted SOC = SOC_est − (average current so far) × (previous eclipse duration − elapsed) / Q

The previous eclipse's duration is measured from the sun-presence flag.

**Validation.**
- `ground/ref/ekf_ref.py` reimplements the filter in plain NumPy. `tools/ekf_trace` runs the
  C++ filter on one orbit, including a 10% initial error, a degraded_cell fault and a voltage
  spike, and writes the inputs, parameters and estimates. A pytest replays them through the
  reference. The states agree to about 2×10⁻¹⁵, against a requirement of 1×10⁻⁹.
- `tools/monte_carlo.py` runs 50 seeds × 10 orbits, each with its own sensor noise and an
  initial SOC error drawn uniformly from ±15%. Full results:
  [results/README.md](results/README.md).

| Monte Carlo metric (50 runs × 10 orbits) | Value |
|---|---|
| RMS SOC error after orbit 1 | 0.034% SOC (all steps including convergence: 0.097%) |
| Max SOC error after orbit 1 | 0.23% SOC |
| NIS inside 95% bounds | 92% of steps |
| NEES inside 95% bounds | 29% of steps after orbit 1 |
| Mean eclipse-exit prediction error | +0.14% SOC (always slightly optimistic) |

**NEES is not consistent.** Mean NEES follows a
once-per-orbit sawtooth between about 0.4 and 5, against bounds of [2.4, 3.7]:
- **Below the bounds (too conservative)** while the battery sits full. The current is about
  zero there, so R0 can't be observed, yet its random-walk variance keeps growing.
- **Above the bounds (mildly overconfident)** during charge and discharge. The deliberate RC
  mismatch, and the true R0 following battery temperature, are both deterministic errors that
  white process noise only approximates.

Raising V_rc process noise to cover the mismatch made both NEES and SOC accuracy worse.
Making the filter consistent would need either current-dependent R0 noise or a
temperature-aware R0 model. Both are listed under known simplifications below.

**Prediction bias.** The prediction error falls from +0.26% at eclipse entry to about 0 at
exit. The loads draw constant power, so battery current rises a few percent as the voltage
sags. The "average so far" therefore underestimates the current still to come.

## Faults

`sim --fault NAME@TIME_S` (repeatable) injects a fault once sim time reaches TIME_S.
Constants are in `common/params.hpp`.

| Fault | Effect in the simulator |
|---|---|
| `degraded_cell` | Battery R0 doubles |
| `stuck_on_heater` | The 5 W battery heater stays on whatever FSW commands. Housekeeping still reports the commanded state; sim truth reports the real one |
| `biased_battery_thermistor` | The battery thermistor reads 8 K high. The battery itself is unchanged |
| `radiator_degradation` | Radiator emissivity drops 40%. Every temperature settles inside its limits; the radiator monitor detects it |

`tools/fault_campaign.py` runs each fault headless and reports how it was detected:
[anomalies/README.md](anomalies/README.md).

## Ground segment and alerts

`ground/station.py` owns ports 6001 and 6003. It writes every packet to InfluxDB as one
point per packet (`ground/points.py`), tagged `source=fsw` or `source=truth`, and relays it
to port 6011 so `decode.py`, `cmd.py` and the procedures keep working alongside it. Once a
second it also writes link health: packet rate, sequence gaps and decode errors. Receive
timestamps are made unique, because InfluxDB overwrites points with equal times, and on
SIGINT or SIGTERM the station drains its sockets (up to 2 s) before the final flush.

Two fields are derived on the ground or for the ground:
- `load_excess_W` (housekeeping, eclipse only): measured load power minus the power the
  commanded loads account for. In sunlight the array current also covers power shunted off a
  full battery, so the check is only valid in eclipse.
- `r0_ratio` (estimator, from the FSW): the EKF's R0 over the nominal R0 at the measured
  battery temperature, the same ratio the degradation monitor uses.

Alert rules are defined once in `ground/alerts.py`. `tools/gen_grafana.py` turns them into
provisioned Grafana rules (Flux query → reduce → threshold), and `tools/fault_campaign.py`
evaluates the same rules in Python on recorded telemetry. Grafana evaluates every 10 s over
wall-clock windows sized for the 60× demo speed; the campaign evaluates at the matching
mission-time cadence. The dashboards, rules and [limits.md](limits.md) are generated from
`common/params.hpp`. `tools/check_grafana.py` runs every panel query and rule through
Grafana's API.

The Monte Carlo and fault-campaign runners (`tools/jobs.py`) record each job's wall time,
CPU time (from `wait4`) and peak memory, and write them to the `compute` measurement for
the Compute Usage dashboard.

## Verification tests

[requirements.md](requirements.md) maps each requirement to these tests.

| Test | Criterion |
|---|---|
| `Thermal.FlatPlateReachesAnalyticEquilibrium` | Converges to `(αS/εσ)^¼` within 0.5 K |
| `Orbit.EclipseFractionMatchesAnalytic` | β = 0°, 30°, 60° match `(1/π)·acos(√(h²+2Rh)/((R+h)cos β))` within 1% |
| `Spacecraft.EnergyIsConservedOverFiveOrbits` | `absorbed − radiated = Δ(ΣC·T + battery chemical energy)` within 0.5% of absorbed (actual 0.00017%) |
| `Spacecraft.DefaultConfigIsPowerPositiveAndPeriodic` | After 20 orbits, temperatures repeat within 1 K and SOC within 1%; the battery reaches full charge every orbit |
| `Faults.*` (4 tests) | Every fault name parses; a stuck heater draws exactly 5 W despite an off command; a biased thermistor reads +8 K on the battery only; a degraded radiator runs warmer and energy is still conserved |
| `Ccsds.RoundTrip`, `Ccsds.WritesHousekeepingFixture` | Header fields and data survive encode/decode; truncated packets are rejected; the C++ encoder writes the fixture pytest decodes |
| `Fsw.ThermostatHysteresis` | The heater switches only outside the setpoint band |
| `Fsw.ModeTransitions`, `Fsw.SafeExitsOnlyByGroundCommand` | NOMINAL ↔ LOAD_SHED with hysteresis; SAFE on critical SOC or a red limit; SAFE sticky until ground command |
| `Fsw.EveryCommandIsAckedOrNacked` | Valid commands are ACKed; bad length, unknown opcode, bad argument, wrong mode and malformed packets are NACKed with the right reason |
| `Fsw.RadiatorMonitorComparesOrbitMeansFromEclipseEntry` | Orbits run from eclipse entry to eclipse entry; the event fires once per excursion and re-arms |
| `Integration.SimAndFswKeepBatteryAboveFreezingForThreeOrbits` | 3 orbits in one process: battery above 0 °C, FSW stays NOMINAL |
| `Integration.RadiatorDegradedOnlyWithTheFault` | 12 orbits: no RADIATOR_DEGRADED without the fault, exactly one with it |
| `Ekf.ConvergesFromTwentyPercentSocErrorWithinOneOrbit` | \|SOC error\| < 2% for the whole second orbit |
| `Ekf.DegradedCellR0ConvergesAndRaisesEvent` | R0 estimate within 5% of truth 2 orbits after `degraded_cell`, and BATTERY_DEGRADED fires |
| `Ekf.NisGateRejectsVoltageSpike` | A +0.5 V spike is rejected, counted, and leaves the state unchanged |
| `test_ekf_ref.py` | The NumPy reference matches the C++ EKF within 1e-9 on every state (actual 1.9×10⁻¹⁵), including gate rejections and a fault |
| `test_ground.py`, `test_points.py` | Every packet type decodes, from the C++ fixture where possible; InfluxDB points have the right measurement, tags, field types and escaping; NaN fields are dropped |
| `test_grafana.py` | Generated files are up to date; every query names a field the station writes; Grafana rules match `ground/alerts.py`; thresholds match `params.hpp` |
| `test_alerts.py` | Each rule's Python evaluation (red limit, NIS run length, eclipse mean, no-data, event filter, evaluation cadence); the job runner records CPU and memory and kills on timeout |
| `test_station.py` | On SIGTERM and SIGINT the station flushes to a fake InfluxDB, counts decode errors and exits 0 |
| `scripts/smoke.sh` (end to end, needs Docker) | 2 orbits: ≥ 99% of packets stored, no decode errors, every panel and alert rule OK through Grafana's API |

## What the project demonstrates

- **Multiphysics coupling.** Orbit, a lumped thermal network (RK4) and an equivalent-circuit
  battery are coupled step by step, with every watt accounted for: array power is not
  heat, I²R losses heat the battery, and shunted power heats the radiator. Energy is
  conserved to 0.0002% over 5 orbits.
- **Estimation.** An iterated EKF on [SOC, V_rc, R0], deliberately run with the wrong RC
  parameters. It has a NIS gate that can't lock out a genuine step change, is validated by
  Monte Carlo and cross-checked against an independent reference. Its weaknesses (NEES) are
  reported, not hidden.
- **Flight software.** Lockstep sim/FSW over UDP, CCSDS packets, a mode manager with
  hysteresis and a sticky SAFE mode, ACK/NACK for every command, fault monitors, all
  linked as libraries so tests run the whole loop in one process.
- **Observability.** Telemetry to InfluxDB with link health, generated Grafana dashboards
  and alerts, and checks that every query and rule runs against the real Grafana API.
  Compute usage is recorded per job.
- **Operations.** Scripted procedures with pass/fail reports, a fault campaign that
  measures detection time for every fault, anomaly reports, an operator runbook,
  Docker packaging and CI.

## Known simplifications

- No Earth albedo or Earth infrared heating. The only external heat source is direct sunlight.
- Space is a 0 K sink, and there is no radiative exchange between nodes.
- Cylindrical Earth shadow: no penumbra, no atmospheric refraction, no seasonal change
  in solar flux (constant 1361 W/m²).
- Beta angle is fixed. There is no orbit precession or J2.
- The array tracks the Sun perfectly. The body's sunlit area is a constant projected area.
- The array delivers its full rated power to the bus (ideal maximum power point tracking, no
  converter losses).
- Charging stops abruptly at 100% SOC (no CC/CV taper). Coulombic efficiency is 100%.
- Battery OCV does not depend on temperature. Only R0 does.
- Heat inputs are held constant within each 1 s step. The power and thermal models are
  coupled explicitly, step by step.
- Sensor noise is white Gaussian: 10 mV, 10 mA, 0.1 K. Sensor biases exist only as injected
  faults.
- The sim ↔ FSW bus sends raw structs in host byte order over loopback, so sim, FSW and
  station share one network namespace in Docker. Everything to or from the ground is CCSDS
  and big-endian.
- One red-limit violation in a single sample is enough to trigger SAFE, with no persistence
  filter.
- With default parameters the battery stays warm enough that the heater never turns on unless
  the ground raises the setpoints.
- EKF R0 is a pure random walk: it ignores the battery temperature, and its noise doesn't
  depend on current. This causes the NEES sawtooth described above.
- Battery capacity is known exactly to the EKF (no capacity fade).
- The eclipse-exit prediction assumes constant current, which makes it optimistic by up to
  0.26% SOC early in eclipse.
- Housekeeping reports commanded heater and payload states, not measured ones, and no
  shunt power. Load anomalies are visible only through the eclipse power balance.
- Grafana alert windows are wall-clock seconds sized for the 60× demo speed. At real time
  the windows cover far less of an orbit.
- The radiator monitor's expected orbit mean is the fault-free steady state at the default
  30° beta angle. At another beta (`--beta`) it would need a new prediction.
