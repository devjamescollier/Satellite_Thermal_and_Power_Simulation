#pragma once

#include "params.hpp"

namespace sim {

struct Vec3 {
  double x, y, z;
};

// Circular orbit in a frame where the Sun lies along +x. The beta angle is the
// angle between the Sun vector and the orbit plane.
struct Orbit {
  double altitude_m = params::altitude_m;
  double beta_rad = params::beta_angle_deg * params::pi / 180.0;

  double radius_m() const;
  double period_s() const;
  Vec3 position_m(double t_s) const;
  bool in_eclipse(double t_s) const;  // cylindrical Earth shadow
};

}  // namespace sim
