# Operator runbook

This system is a simulated small satellite in low Earth orbit, with its flight software and
a ground station. It runs about 60 times faster than real time, so one orbit (94 minutes in
orbit) takes about 95 seconds on screen. Everything you need is in the web dashboards; the
commands below are typed into a terminal opened in the project folder.

## Start and stop

Before the first start, someone sets up the `.env` settings file once (copied from
`.env.example`). After that:

| To | Type |
|---|---|
| Start everything (3 orbits, about 5 minutes) | `docker compose up -d` |
| Open the dashboards | <http://localhost:3000> (user name and password are in `.env`) |
| Run another pass when the sim has finished | `docker compose down`, then `docker compose up -d` (a fresh start for the flight software too) |
| Stop everything (recorded data is kept) | `docker compose down` |
| Check that everything is running | `docker compose ps` (all should say "Up" or "healthy"; `sim` says "Exited (0)" once its pass is done) |

**Sending commands.** While a pass is running:

| Command | Type |
|---|---|
| Check the link (no effect on the spacecraft) | `docker compose exec station python ground/cmd.py noop` |
| Change mode | `docker compose exec station python ground/cmd.py set-mode nominal` (or `safe`, `load_shed`) |
| Payload on / off | `docker compose exec station python ground/cmd.py payload-on` (or `payload-off`) |

Every command prints **ACK** (accepted) or **NACK** with a reason. "No ack" means the
spacecraft is not running: check that the `sim` pass has not finished.

**Procedures** are scripted checklists that send commands, check the results and write a
pass/fail report to `docs/reports/`:

| Procedure | Type | Takes |
|---|---|---|
| Battery heater checkout | `docker compose exec station python ground/procedures/heater_checkout.py` | about 30 s |
| SAFE mode recovery | `docker compose exec station python ground/procedures/safe_mode_recovery.py` | about 15 s |
| SAFE recovery drill (puts it in SAFE first) | add `--drill` to the line above | about 15 s |

A procedure stops at the first failed step and says why. Do not repeat a failed SAFE
recovery without fixing what it reported.

## Mission Control dashboard

Opens by default. Data appears within a few seconds of a pass starting.

| Panel | What it shows | Normal |
|---|---|---|
| Sunlight / eclipse | When the spacecraft is in sunlight or Earth's shadow | About 60 s sunlight, 35 s eclipse per orbit |
| FSW mode | NOMINAL (green), LOAD_SHED (yellow, payload off to save power), SAFE (red, minimum activity) | NOMINAL throughout |
| Five temperature panels | Each part's temperature in Kelvin (°C = K − 273). Blue: spacecraft sensor; orange: simulation truth. Background bands: green fine, yellow caution, red limit | Inside the green band. Battery about 281–291 K; the solar array swings widely, about 206–307 K |
| SOC | Battery charge, 0–100%. Blue: spacecraft's estimate with its uncertainty band; orange: truth; purple dots: predicted charge at the end of the current eclipse (from the second orbit on) | 88–100%, estimate on top of truth |
| Internal resistance R0 | Battery resistance, estimated and true. It is higher when the battery is cold | About 0.11–0.15 Ω, estimate on top of truth |
| Power generated vs consumed | Solar power and power used. When the battery is full, "consumed" also includes surplus solar power being dumped, so it rises to match generation | Generation about 45–56 W in sunlight, 0 in eclipse |
| NIS | How well the battery estimator's predictions match the measurements | Mostly below the dashed line |
| Eclipse load: measured minus commanded | In eclipse, power drawn beyond what the switched-on equipment should use | Close to 0 W |
| Battery R0 ÷ nominal | Battery resistance compared with what it should be at the measured temperature | Close to 1.0; yellow line 1.2, red line 1.5 |
| Link: packet rate / errors | Telemetry arriving at the ground, and anything lost or garbled | Steady rate; errors stay at 0 |
| Recent events and command acks | Mode changes, battery warnings and command replies, newest first | Only your own commands |

## Alerts

Alerts appear under Alerting in Grafana and are sent to the team's chat channel.
**Critical** alerts need action now; **warning** alerts need investigating this shift.
Thresholds are listed in [limits.md](limits.md).

| Alert | Meaning | Likely causes | What to do |
|---|---|---|---|
| **Red-limit violation** (critical) | A part is outside its safe temperature range. The spacecraft has gone to SAFE by itself | Heater fault, cooling problem, unusual sun angle | Note which part (named in the alert). Watch it recover in SAFE. Run SAFE recovery only once it is back inside its yellow band |
| **FSW entered SAFE** (critical) | The spacecraft is in SAFE mode; it stays there until commanded out | A red limit, very low battery (below 25%), or a SAFE command | Check the events table for the reason. Fix or wait out the cause, then run the SAFE mode recovery procedure |
| **Predicted SOC at eclipse exit below 30%** (critical) | The battery is expected to be nearly flat when the spacecraft leaves Earth's shadow | Too much load for this eclipse, a weak battery | Command `payload-off` now. If the battery estimate keeps falling, command `set-mode safe` |
| **No telemetry for 30 s** (critical) | Nothing has been received from the spacecraft | Pass finished or not started; a stopped container | Normal when no pass is running. Otherwise run `docker compose ps` and restart what is stopped |
| **NIS above gate for 30 samples in a row** (warning) | The battery estimator disagrees with the measurements for a sustained period | A real battery change, or a voltage or current sensor problem | Check the R0 panel and the events table for BATTERY_DEGRADED. Report to the battery engineer |
| **FSW reported BATTERY_DEGRADED** (warning) | The spacecraft's own monitor says the battery resistance has stayed above 1.5× normal for 10 minutes | Cell ageing or a failed cell | Keep the payload off in eclipse to limit battery drain, and report to the battery engineer. See [degraded_cell](anomalies/degraded_cell.md) |
| **Eclipse load above commanded loads** (warning) | Something is drawing power that nothing was switched on for | A heater stuck on, a short circuit | Check the battery temperature panel: if it is rising, a stuck heater is likely. Watch the battery charge and consider payload off. See [stuck_on_heater](anomalies/stuck_on_heater.md) |
| **FSW reported RADIATOR_DEGRADED** (warning) | Over the last orbit the radiator ran more than 2.5 K warmer on average than the thermal prediction | Radiator coating damage or contamination, a change in heat load | Check the temperature panels for a rise across all parts over several orbits. Reduce payload use to restore margin and report to the thermal engineer. See [radiator_degradation](anomalies/radiator_degradation.md) |
| **Battery R0 above 1.2× nominal for its temperature** (warning) | Battery resistance does not match the battery temperature | A degraded battery, **or** a faulty battery temperature sensor | If BATTERY_DEGRADED also appears, treat it as a battery problem. If not, suspect the temperature sensor: compare it with the structure temperature. See [biased_battery_thermistor](anomalies/biased_battery_thermistor.md) |

## Compute Usage dashboard

Shows how long the analysis jobs (Monte Carlo and fault campaign) took and how much
memory they used. Pick the job type at the top. Only engineers need this one.
