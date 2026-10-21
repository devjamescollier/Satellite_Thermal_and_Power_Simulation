#pragma once

// Every tunable constant in the project. SI units, temperatures in Kelvin.

namespace params {

// --- Physical constants ---
inline constexpr double pi = 3.14159265358979323846;
inline constexpr double stefan_boltzmann = 5.670374419e-8;  // W/(m^2 K^4)
inline constexpr double solar_flux_W_m2 = 1361.0;
inline constexpr double earth_radius_m = 6371.0e3;
inline constexpr double earth_mu_m3_s2 = 3.986004418e14;

// --- Orbit ---
inline constexpr double altitude_m = 500.0e3;
inline constexpr double beta_angle_deg = 30.0;

// --- Simulation ---
inline constexpr double step_s = 1.0;
inline constexpr double initial_temp_K = 290.0;
inline constexpr double initial_soc = 0.8;

// --- Thermal network ---
enum Node { kArray, kStructure, kBattery, kAvionics, kRadiator, kNumNodes };

struct ThermalNode {
  const char* name;
  double capacity_J_K;
  double sun_area_m2;  // area facing the Sun
  double absorptivity;
  double rad_area_m2;  // area radiating to space
  double emissivity;
};

struct ThermalLink {
  int a, b;
  double conductance_W_K;
};

// Indexed by Node. The array radiates from both faces; the structure is wrapped
// in MLI (low effective emissivity); battery and avionics are internal.
// clang-format off
inline constexpr ThermalNode thermal_nodes[kNumNodes] = {
    // name        C [J/K]  A_sun  alpha  A_rad  eps
    {"array", 540.0, 0.12, 0.92, 0.24, 0.85},
    {"structure", 3600.0, 0.03, 0.30, 0.30, 0.05},
    {"battery", 700.0, 0.0, 0.0, 0.0, 0.0},
    {"avionics", 1350.0, 0.0, 0.0, 0.0, 0.0},
    {"radiator", 450.0, 0.0, 0.0, 0.09, 0.85},
};
// clang-format on

inline constexpr ThermalLink thermal_links[] = {
    {kArray, kStructure, 0.2},     // hinges
    {kStructure, kBattery, 0.5},   // battery bracket
    {kStructure, kAvionics, 1.0},  // card rails
    {kStructure, kRadiator, 2.0},  // radiator mount
    {kAvionics, kRadiator, 1.5},   // heat strap
};

// --- Solar array (sun-tracking) ---
inline constexpr double array_area_m2 = thermal_nodes[kArray].sun_area_m2;
inline constexpr double array_efficiency = 0.28;  // at reference temperature
inline constexpr double array_ref_temp_K = 298.15;
inline constexpr double array_temp_coeff_per_K = -0.0025;  // relative efficiency change

// --- Battery: 4S2P Li-ion, one-RC equivalent circuit ---
inline constexpr int cells_in_series = 4;
inline constexpr double battery_capacity_C = 6.8 * 3600.0;  // 6.8 Ah
inline constexpr double soc_max = 1.0;
inline constexpr double battery_r0_ohm = 0.08;  // at reference temperature
inline constexpr double battery_r0_ref_temp_K = 298.15;
inline constexpr double battery_r0_activation_K = 3000.0;  // Arrhenius rise when cold
inline constexpr double battery_r1_ohm = 0.015;
inline constexpr double battery_c1_F = 2000.0;

// Per-cell open-circuit voltage vs. state of charge, evenly spaced 0..1.
inline constexpr int ocv_points = 11;
inline constexpr double ocv_cell_V[ocv_points] = {3.00, 3.45, 3.55, 3.62, 3.68, 3.74,
                                                  3.80, 3.87, 3.95, 4.05, 4.20};

// --- Loads ---
inline constexpr double avionics_W = 8.0;
inline constexpr double payload_W = 15.0;
inline constexpr double heater_W = 5.0;

// --- Faults (sim --fault NAME@TIME_S) ---
// degraded_cell: battery R0 doubles. stuck_on_heater: the battery heater stays on
// whatever FSW commands. biased_battery_thermistor: the battery thermistor reads
// high. radiator_degradation: radiator emissivity drops (coating damage).
inline constexpr double degraded_cell_r0_factor = 2.0;
inline constexpr double biased_thermistor_offset_K = 8.0;
inline constexpr double radiator_degraded_emissivity_factor = 0.6;  // drops 40%

// --- Sensors (1-sigma Gaussian noise) ---
inline constexpr unsigned sensor_seed = 42;
inline constexpr double thermistor_noise_K = 0.1;
inline constexpr double thermistor_resolution_K = 0.1;
inline constexpr double voltage_noise_V = 0.01;
inline constexpr double current_noise_A = 0.01;

// --- UDP bus (loopback) ---
inline constexpr int port_sensors = 5001;       // sim -> fsw
inline constexpr int port_actuators = 5002;     // fsw -> sim
inline constexpr int port_telemetry = 6001;     // fsw -> ground
inline constexpr int port_telecommands = 6002;  // ground -> fsw
inline constexpr int port_sim_truth = 6003;     // sim -> ground (sim-only)
inline constexpr int port_ground_relay = 6011;  // ground station re-sends telemetry here (cmd.py)
inline constexpr double actuator_timeout_s = 0.2;

// --- Flight software ---
inline constexpr double heater_on_below_K = 278.15;   // 5 C
inline constexpr double heater_off_above_K = 283.15;  // 10 C
inline constexpr double setpoint_min_K = 253.15;      // commandable setpoint range
inline constexpr double setpoint_max_K = 313.15;
inline constexpr double load_shed_soc = 0.40;
inline constexpr double load_shed_exit_soc = 0.50;
inline constexpr double safe_soc = 0.25;
// Limits per node (indexed by Node). Crossing a red limit sends FSW to SAFE and
// raises a ground alert; yellow limits are ground display only. docs/limits.md and
// the Grafana dashboard and alerts are generated from these (tools/gen_grafana.py).
inline constexpr double red_low_K[kNumNodes] = {150.0, 240.0, 268.15, 243.15, 200.0};
inline constexpr double yellow_low_K[kNumNodes] = {170.0, 250.0, 273.15, 253.15, 210.0};
inline constexpr double yellow_high_K[kNumNodes] = {380.0, 320.0, 313.15, 333.15, 320.0};
inline constexpr double red_high_K[kNumNodes] = {400.0, 330.0, 318.15, 343.15, 330.0};

// --- Battery EKF, state [SOC, V_rc, R0] ---
// The filter's RC branch is deliberately ~10% off the sim's (battery_r1_ohm,
// battery_c1_F) so the estimator is not a copy of the truth model.
inline constexpr double ekf_r1_ohm = 0.0165;
inline constexpr double ekf_c1_F = 1800.0;
inline constexpr double ekf_sigma0[3] = {0.10, 0.05, 0.015};  // initial 1-sigma per state
inline constexpr double ekf_q[3] = {1e-10, 5e-7, 2e-8};       // process noise per second
inline constexpr double ekf_r_V2 = 1.1e-4;      // (10.5 mV)^2: sensor noise + model error
inline constexpr double ekf_nis_gate = 10.828;  // chi-squared, 1 dof, 99.9%
// Iterated EKF: relinearise the measurement at the updated state. The OCV slope
// changes between table segments, so a single linearisation far from the truth
// collapses the SOC variance on the wrong segment.
inline constexpr int ekf_update_iterations = 5;
// After this many consecutive rejections the mismatch is real, not a spike. SOC is
// pinned by coulomb counting, so the likely cause is a resistance change: reopen
// the R0 variance and accept, so a genuine step cannot lock the filter out.
inline constexpr int ekf_max_consecutive_rejections = 5;
inline constexpr double ekf_reopen_r0_sigma_ohm = 0.05;
inline constexpr double degraded_r0_ratio = 1.5;  // vs temperature-corrected nominal
inline constexpr double degraded_hold_s = 600.0;
// Radiator monitor: each orbit's mean radiator thermistor reading (orbits run from eclipse
// entry to eclipse entry) against the thermal prediction. The expected value is the
// fault-free steady state at the default 30 deg beta angle; a mission would load it per
// beta from thermal analysis. Fault-free orbit means never exceed it by more than 0.01 K,
// and the largest orbit-to-orbit change (warm-up from the initial temperature) is 2.2 K,
// so the margin sits just above that.
inline constexpr double radiator_expected_orbit_mean_K = 284.80;
inline constexpr double radiator_orbit_margin_K = 2.5;

// --- Ground alerts (Grafana rules and tools/fault_campaign.py, defined in ground/alerts.py) ---
// Grafana evaluates every rule each alert_interval_s over a window ending now. Windows
// are wall-clock seconds, sized for the default 60x demo speed.
inline constexpr double predicted_soc_alert = 0.30;  // eclipse-exit SOC prediction
inline constexpr double nis_alert_samples = 30;      // consecutive samples above the gate
inline constexpr double load_excess_alert_W = 2.0;   // eclipse load above commanded loads
inline constexpr double r0_ratio_alert = 1.2;        // R0 vs nominal at measured temperature
inline constexpr double alert_interval_s = 10.0;
inline constexpr double alert_window_s = 30.0;  // red limit, SAFE, SOC, stale telemetry
inline constexpr double nis_window_s = 60.0;
inline constexpr double load_excess_window_s = 120.0;  // spans an eclipse at 60x
inline constexpr double r0_ratio_window_s = 60.0;
inline constexpr double event_alert_window_s = 300.0;  // keeps event alerts visible

}  // namespace params
