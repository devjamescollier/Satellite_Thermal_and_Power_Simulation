#pragma once

#include <vector>

#include "params.hpp"

namespace sim {

// Lumped-parameter thermal network: nodes exchange heat by conduction and
// radiate to a 0 K space sink.
struct ThermalNetwork {
  std::vector<params::ThermalNode> nodes;
  std::vector<params::ThermalLink> links;
};

ThermalNetwork default_network();

struct ThermalStepEnergy {
  double absorbed_J;  // sunlight absorbed during the step
  double radiated_J;  // radiated to space during the step
};

double absorbed_solar_W(const params::ThermalNode& node, bool in_sun);

// Advances temps_K by dt_s with RK4. heat_W is internal heat per node (may be
// negative, e.g. electrical power drawn off the array), constant over the step.
ThermalStepEnergy thermal_step(const ThermalNetwork& net, std::vector<double>& temps_K,
                               const std::vector<double>& heat_W, bool in_sun, double dt_s);

}  // namespace sim
