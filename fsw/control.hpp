#pragma once

#include <optional>

#include "messages.hpp"

namespace fsw {

// Battery heater bang-bang controller with hysteresis.
struct Thermostat {
  double on_below_K = params::heater_on_below_K;
  double off_above_K = params::heater_off_above_K;
  bool heater_on = false;

  bool update(double temp_K);
};

struct ModeChange {
  msg::Mode from, to;
  msg::ModeReason reason;
};

// NOMINAL -> LOAD_SHED on low SOC, back when it recovers; any mode -> SAFE on
// critical SOC or a red limit. SAFE is left only by ground command.
struct ModeManager {
  msg::Mode mode = msg::Mode::kNominal;

  std::optional<ModeChange> update(double soc, const double (&temps_K)[params::kNumNodes]);
  std::optional<ModeChange> set(msg::Mode to, msg::ModeReason reason);
};

// Predicts SOC at eclipse exit from the average eclipse current so far and the
// previous eclipse's measured duration. Returns NaN when there is no prediction
// (in sunlight, or before a full eclipse has been seen).
struct EclipsePredictor {
  double last_duration_s = 0.0;  // 0 = unknown
  double elapsed_s = 0.0;
  double charge_C = 0.0;  // discharged so far this eclipse
  bool in_eclipse = false;

  double update(bool sun_present, double current_A, double soc, double dt_s);
};

// Flags a degraded cell when estimated R0 stays above degraded_r0_ratio times the
// temperature-corrected nominal for degraded_hold_s. Fires once per excursion.
struct DegradationMonitor {
  double above_s = 0.0;
  bool raised = false;

  bool update(double r0_est_ohm, double battery_temp_K, double dt_s);  // true = raise event
};

// Flags radiator degradation: compares each orbit's mean radiator temperature (orbit =
// eclipse entry to eclipse entry) with radiator_expected_orbit_mean_K. Fires once per
// excursion, when an orbit's mean exceeds it by more than radiator_orbit_margin_K.
struct RadiatorMonitor {
  double sum_K = 0.0;
  long samples = 0;
  bool orbit_started = false;  // true after the first eclipse entry
  bool was_sunlit = false;
  bool raised = false;
  double last_excess_K = 0.0;  // last complete orbit's mean minus the expected value

  bool update(bool sun_present, double radiator_K);  // true = raise event
};

// Crude SOC from the OCV table at the measured voltage; used to initialise the EKF.
double estimate_soc(double pack_V);

}  // namespace fsw
