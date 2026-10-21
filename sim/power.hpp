#pragma once

#include "params.hpp"

namespace sim {

struct Battery {
  double soc = params::initial_soc;
  double rc_V = 0.0;      // voltage across the RC branch
  double r0_scale = 1.0;  // > 1 after a degraded_cell fault
};

struct Loads {
  bool payload_on = true;
  bool heater_on = false;
  bool heater_stuck_on = false;  // stuck_on_heater fault: on whatever is commanded
};

// Electrical state over one step. Current is positive when charging.
struct PowerState {
  double solar_W = 0.0;
  double load_W = 0.0;
  double battery_V = 0.0;
  double battery_A = 0.0;
  double r0_ohm = 0.0;           // internal resistance used this step
  double battery_heat_W = 0.0;   // I^2 R losses
  double avionics_heat_W = 0.0;  // avionics + payload
  double heater_W = 0.0;
  double shunt_W = 0.0;  // excess solar power dumped when the battery is full
};

double solar_power_W(bool in_sun, double array_temp_K);
double battery_energy_J(double soc);  // chemical energy stored above SOC = 0

// Balances solar power, loads and battery, then advances the battery by dt_s.
PowerState power_step(Battery& battery, const Loads& loads, bool in_sun, double array_temp_K,
                      double battery_temp_K, double dt_s);

}  // namespace sim
