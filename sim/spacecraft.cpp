#include "spacecraft.hpp"

#include <cstdlib>

namespace sim {

bool parse_fault(const std::string& spec, Fault& fault) {
  size_t at = spec.find('@');
  if (at == std::string::npos) return false;
  fault = {spec.substr(0, at), std::atof(spec.c_str() + at + 1)};
  for (const char* name : kFaultNames) {
    if (fault.name == name) return true;
  }
  return false;
}

void Spacecraft::apply(const Fault& f) {
  using namespace params;
  if (f.name == "degraded_cell") battery.r0_scale *= degraded_cell_r0_factor;
  if (f.name == "stuck_on_heater") loads.heater_stuck_on = loads.heater_on = true;
  if (f.name == "biased_battery_thermistor")
    thermistor_bias_K[kBattery] += biased_thermistor_offset_K;
  if (f.name == "radiator_degradation") {
    thermal.nodes[kRadiator].emissivity *= radiator_degraded_emissivity_factor;
  }
}

Telemetry Spacecraft::step(double dt_s) {
  using namespace params;
  for (Fault& f : faults) {
    if (f.applied || time_s < f.time_s) continue;
    apply(f);
    f.applied = true;
  }
  bool eclipse = orbit.in_eclipse(time_s);
  Telemetry t{time_s, eclipse, temps_K, battery.soc, 0.0, 0.0, 0.0, 0.0};  // filled below

  PowerState p = power_step(battery, loads, !eclipse, temps_K[kArray], temps_K[kBattery], dt_s);
  t.battery_V = p.battery_V;
  t.battery_A = p.battery_A;
  t.battery_r0_ohm = p.r0_ohm;
  t.solar_W = p.solar_W;

  // Where the electrical power ends up as heat.
  std::vector<double> heat_W(kNumNodes, 0.0);
  heat_W[kArray] = -p.solar_W;  // converted to electricity, not heat
  heat_W[kAvionics] = p.avionics_heat_W;
  heat_W[kBattery] = p.battery_heat_W + p.heater_W;
  heat_W[kRadiator] = p.shunt_W;

  ThermalStepEnergy e = thermal_step(thermal, temps_K, heat_W, !eclipse, dt_s);
  absorbed_J += e.absorbed_J;
  radiated_J += e.radiated_J;
  time_s += dt_s;
  return t;
}

double Spacecraft::stored_energy_J() const {
  double energy_J = battery_energy_J(battery.soc);
  for (size_t i = 0; i < temps_K.size(); ++i) {
    energy_J += thermal.nodes[i].capacity_J_K * temps_K[i];
  }
  return energy_J;
}

}  // namespace sim
