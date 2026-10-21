#include "power.hpp"

#include <algorithm>
#include <cmath>

#include "battery_model.hpp"

namespace sim {

double solar_power_W(bool in_sun, double array_temp_K) {
  if (!in_sun) return 0.0;
  double dT = array_temp_K - params::array_ref_temp_K;
  double efficiency = params::array_efficiency * (1.0 + params::array_temp_coeff_per_K * dT);
  return std::max(efficiency, 0.0) * params::array_area_m2 * params::solar_flux_W_m2;
}

double battery_energy_J(double soc) {
  // Integral of the piecewise-linear OCV curve (trapezoids) from 0 to soc.
  const double step = 1.0 / (params::ocv_points - 1);
  double soc_V = 0.0;
  for (int i = 0; i + 1 < params::ocv_points && i * step < soc; ++i) {
    double lo = i * step, hi = std::min(soc, (i + 1) * step);
    soc_V += 0.5 * (battery::ocv_V(lo) + battery::ocv_V(hi)) * (hi - lo);
  }
  return soc_V * params::battery_capacity_C;
}

PowerState power_step(Battery& battery, const Loads& loads, bool in_sun, double array_temp_K,
                      double battery_temp_K, double dt_s) {
  PowerState s;
  s.solar_W = solar_power_W(in_sun, array_temp_K);
  s.avionics_heat_W = params::avionics_W + (loads.payload_on ? params::payload_W : 0.0);
  s.heater_W = loads.heater_on ? params::heater_W : 0.0;
  s.load_W = s.avionics_heat_W + s.heater_W;

  double battery_W = s.solar_W - s.load_W;
  if (battery_W > 0.0 && battery.soc >= params::soc_max) {
    s.shunt_W = battery_W;
    battery_W = 0.0;
  }

  // Terminal power P = V*I with V = OCV + V_rc + I*R0; solve the quadratic for I.
  double r0 = battery::r0_nominal_ohm(battery_temp_K) * battery.r0_scale;
  double emf = battery::ocv_V(battery.soc) + battery.rc_V;
  double disc = std::max(emf * emf + 4.0 * r0 * battery_W, 0.0);
  double current_A = (std::sqrt(disc) - emf) / (2.0 * r0);
  s.battery_A = current_A;
  s.battery_V = emf + current_A * r0;
  s.r0_ohm = r0;
  s.battery_heat_W =
      current_A * current_A * r0 + battery.rc_V * battery.rc_V / params::battery_r1_ohm;

  double decay = std::exp(-dt_s / (params::battery_r1_ohm * params::battery_c1_F));
  battery.rc_V = battery.rc_V * decay + current_A * params::battery_r1_ohm * (1.0 - decay);
  battery.soc += current_A * dt_s / params::battery_capacity_C;
  return s;
}

}  // namespace sim
