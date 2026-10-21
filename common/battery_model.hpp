#pragma once

// Battery datasheet curves shared by the simulator and the flight software.

#include <algorithm>
#include <cmath>

#include "params.hpp"

namespace battery {

// Segment index and fraction into it for the evenly spaced OCV table. Outside
// 0..1 the end segments extend linearly (frac < 0 or > 1), so SOC stays
// observable at full charge and the slope always matches the value.
inline int ocv_segment(double soc, double& frac) {
  double pos = soc * (params::ocv_points - 1);
  int i = std::clamp(static_cast<int>(std::floor(pos)), 0, params::ocv_points - 2);
  frac = pos - i;
  return i;
}

// Pack open-circuit voltage, piecewise linear in SOC.
inline double ocv_V(double soc) {
  double frac;
  int i = ocv_segment(soc, frac);
  const double* v = params::ocv_cell_V;
  return params::cells_in_series * (v[i] + frac * (v[i + 1] - v[i]));
}

// dOCV/dSOC of the pack on the current table segment.
inline double ocv_slope_V(double soc) {
  double frac;
  int i = ocv_segment(soc, frac);
  const double* v = params::ocv_cell_V;
  return params::cells_in_series * (v[i + 1] - v[i]) * (params::ocv_points - 1);
}

// Healthy-cell internal resistance, rising when cold (Arrhenius).
inline double r0_nominal_ohm(double temp_K) {
  double inv = 1.0 / temp_K - 1.0 / params::battery_r0_ref_temp_K;
  return params::battery_r0_ohm * std::exp(params::battery_r0_activation_K * inv);
}

}  // namespace battery
