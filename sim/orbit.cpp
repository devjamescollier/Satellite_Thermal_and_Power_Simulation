#include "orbit.hpp"

#include <cmath>

namespace sim {

double Orbit::radius_m() const { return params::earth_radius_m + altitude_m; }

double Orbit::period_s() const {
  return 2.0 * params::pi * std::sqrt(std::pow(radius_m(), 3) / params::earth_mu_m3_s2);
}

Vec3 Orbit::position_m(double t_s) const {
  // In-plane basis: e1 = (cos b, 0, sin b), e2 = (0, 1, 0). Noon is at theta = 0.
  double theta = 2.0 * params::pi * t_s / period_s();
  double r = radius_m();
  return {r * std::cos(theta) * std::cos(beta_rad), r * std::sin(theta),
          r * std::cos(theta) * std::sin(beta_rad)};
}

bool Orbit::in_eclipse(double t_s) const {
  Vec3 p = position_m(t_s);
  double off_axis_sq = p.y * p.y + p.z * p.z;
  return p.x < 0.0 && off_axis_sq < params::earth_radius_m * params::earth_radius_m;
}

}  // namespace sim
