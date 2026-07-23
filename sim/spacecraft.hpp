#pragma once

#include <string>
#include <vector>

#include "orbit.hpp"
#include "power.hpp"
#include "thermal.hpp"

namespace sim {

// Snapshot at the start of a step, plus the electrical state during it.
struct Telemetry {
  double time_s;
  bool eclipse;
  std::vector<double> temps_K;
  double soc;
  double battery_V;
  double battery_A;
  double battery_r0_ohm;
  double solar_W;
};

// A fault injected once sim time reaches time_s. Known faults are in kFaultNames
// (descriptions in params.hpp).
struct Fault {
  std::string name;
  double time_s;
  bool applied = false;
};

inline constexpr const char* kFaultNames[] = {"degraded_cell", "stuck_on_heater",
                                              "biased_battery_thermistor", "radiator_degradation"};

// Parses "NAME@TIME_S". False if malformed or the fault is unknown.
bool parse_fault(const std::string& spec, Fault& fault);

// Couples orbit, power and thermal models and keeps a running energy ledger.
struct Spacecraft {
  Orbit orbit;
  ThermalNetwork thermal = default_network();
  std::vector<double> temps_K = std::vector<double>(params::kNumNodes, params::initial_temp_K);
  Battery battery;
  Loads loads;
  std::vector<Fault> faults;
  std::vector<double> thermistor_bias_K = std::vector<double>(params::kNumNodes, 0.0);
  double time_s = 0.0;
  double absorbed_J = 0.0;  // total sunlight absorbed
  double radiated_J = 0.0;  // total radiated to space

  Telemetry step(double dt_s = params::step_s);
  void apply(const Fault& fault);
  double stored_energy_J() const;  // thermal (sum of C*T) + battery chemical
};

}  // namespace sim
