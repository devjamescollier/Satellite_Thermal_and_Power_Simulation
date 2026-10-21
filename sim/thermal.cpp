#include "thermal.hpp"

#include <iterator>

namespace sim {
namespace {

using Vec = std::vector<double>;

// dT/dt for every node. Also returns the total radiated power.
Vec derivative(const ThermalNetwork& net, const Vec& temps_K, const Vec& input_W,
               double& radiated_W) {
  Vec flow_W = input_W;
  radiated_W = 0.0;
  for (size_t i = 0; i < net.nodes.size(); ++i) {
    const auto& n = net.nodes[i];
    double t2 = temps_K[i] * temps_K[i];
    double q = n.emissivity * n.rad_area_m2 * params::stefan_boltzmann * t2 * t2;
    flow_W[i] -= q;
    radiated_W += q;
  }
  for (const auto& link : net.links) {
    double q = link.conductance_W_K * (temps_K[link.b] - temps_K[link.a]);
    flow_W[link.a] += q;
    flow_W[link.b] -= q;
  }
  for (size_t i = 0; i < flow_W.size(); ++i) flow_W[i] /= net.nodes[i].capacity_J_K;
  return flow_W;
}

Vec add_scaled(const Vec& x, const Vec& k, double scale) {
  Vec out = x;
  for (size_t i = 0; i < out.size(); ++i) out[i] += scale * k[i];
  return out;
}

}  // namespace

ThermalNetwork default_network() {
  return {{std::begin(params::thermal_nodes), std::end(params::thermal_nodes)},
          {std::begin(params::thermal_links), std::end(params::thermal_links)}};
}

double absorbed_solar_W(const params::ThermalNode& node, bool in_sun) {
  return in_sun ? node.absorptivity * node.sun_area_m2 * params::solar_flux_W_m2 : 0.0;
}

ThermalStepEnergy thermal_step(const ThermalNetwork& net, std::vector<double>& temps_K,
                               const std::vector<double>& heat_W, bool in_sun, double dt_s) {
  Vec input_W = heat_W;
  double absorbed_W = 0.0;
  for (size_t i = 0; i < net.nodes.size(); ++i) {
    double q = absorbed_solar_W(net.nodes[i], in_sun);
    input_W[i] += q;
    absorbed_W += q;
  }

  double r1, r2, r3, r4;
  Vec k1 = derivative(net, temps_K, input_W, r1);
  Vec k2 = derivative(net, add_scaled(temps_K, k1, dt_s / 2), input_W, r2);
  Vec k3 = derivative(net, add_scaled(temps_K, k2, dt_s / 2), input_W, r3);
  Vec k4 = derivative(net, add_scaled(temps_K, k3, dt_s), input_W, r4);
  for (size_t i = 0; i < temps_K.size(); ++i) {
    temps_K[i] += dt_s / 6.0 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]);
  }
  // Weighting radiation like RK4 keeps the energy ledger consistent with the update.
  double radiated_W = (r1 + 2 * r2 + 2 * r3 + r4) / 6.0;
  return {absorbed_W * dt_s, radiated_W * dt_s};
}

}  // namespace sim
