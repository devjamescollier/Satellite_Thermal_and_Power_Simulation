#include "control.hpp"

#include <algorithm>
#include <limits>

#include "battery_model.hpp"

namespace fsw {

using msg::Mode;
using msg::ModeReason;

bool Thermostat::update(double temp_K) {
  if (temp_K < on_below_K) heater_on = true;
  else if (temp_K > off_above_K) heater_on = false;
  return heater_on;
}

std::optional<ModeChange> ModeManager::update(double soc,
                                              const double (&temps_K)[params::kNumNodes]) {
  if (mode == Mode::kSafe) return std::nullopt;
  for (int i = 0; i < params::kNumNodes; ++i) {
    if (temps_K[i] < params::red_low_K[i] || temps_K[i] > params::red_high_K[i]) {
      return set(Mode::kSafe, ModeReason::kRedLimit);
    }
  }
  if (soc < params::safe_soc) return set(Mode::kSafe, ModeReason::kSocCritical);
  if (mode == Mode::kNominal && soc < params::load_shed_soc) {
    return set(Mode::kLoadShed, ModeReason::kSocLow);
  }
  if (mode == Mode::kLoadShed && soc > params::load_shed_exit_soc) {
    return set(Mode::kNominal, ModeReason::kSocRecovered);
  }
  return std::nullopt;
}

std::optional<ModeChange> ModeManager::set(Mode to, ModeReason reason) {
  if (to == mode) return std::nullopt;
  ModeChange change{mode, to, reason};
  mode = to;
  return change;
}

double EclipsePredictor::update(bool sun_present, double current_A, double soc, double dt_s) {
  if (sun_present) {
    if (in_eclipse) last_duration_s = elapsed_s;
    in_eclipse = false;
    elapsed_s = charge_C = 0.0;
    return std::numeric_limits<double>::quiet_NaN();
  }
  in_eclipse = true;
  elapsed_s += dt_s;
  charge_C += current_A * dt_s;
  if (last_duration_s <= 0.0 || elapsed_s <= 0.0) return std::numeric_limits<double>::quiet_NaN();
  double remaining_s = std::max(last_duration_s - elapsed_s, 0.0);
  return soc - (charge_C / elapsed_s) * remaining_s / params::battery_capacity_C;
}

bool DegradationMonitor::update(double r0_est_ohm, double battery_temp_K, double dt_s) {
  if (r0_est_ohm <= params::degraded_r0_ratio * battery::r0_nominal_ohm(battery_temp_K)) {
    above_s = 0.0;
    raised = false;
    return false;
  }
  above_s += dt_s;
  if (raised || above_s < params::degraded_hold_s) return false;
  return raised = true;
}

bool RadiatorMonitor::update(bool sun_present, double radiator_K) {
  bool raise = false;
  if (was_sunlit && !sun_present) {  // eclipse entry closes an orbit
    if (orbit_started && samples > 0) {
      last_excess_K = sum_K / samples - params::radiator_expected_orbit_mean_K;
      bool over = last_excess_K > params::radiator_orbit_margin_K;
      raise = over && !raised;
      raised = over;
    }
    orbit_started = true;
    sum_K = 0.0;
    samples = 0;
  }
  if (orbit_started) {
    sum_K += radiator_K;
    ++samples;
  }
  was_sunlit = sun_present;
  return raise;
}

double estimate_soc(double pack_V) {
  double cell_V = pack_V / params::cells_in_series;
  const double* ocv = params::ocv_cell_V;
  if (cell_V <= ocv[0]) return 0.0;
  for (int i = 0; i + 1 < params::ocv_points; ++i) {
    if (cell_V < ocv[i + 1]) {
      double frac = (cell_V - ocv[i]) / (ocv[i + 1] - ocv[i]);
      return (i + frac) / (params::ocv_points - 1);
    }
  }
  return 1.0;
}

}  // namespace fsw
