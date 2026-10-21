#include "ekf.hpp"

#include <cmath>

#include "battery_model.hpp"

namespace fsw {
namespace {

using Mat3 = Ekf::Mat3;

Mat3 diagonal(const double (&values)[3], bool square) {
  Ekf::Vec3 d(values[0], values[1], values[2]);
  return (square ? d.cwiseProduct(d) : d).asDiagonal();
}

const Mat3 kP0 = diagonal(params::ekf_sigma0, true);
const Mat3 kQ = diagonal(params::ekf_q, false);

}  // namespace

Ekf::Ekf(double soc, double r0_ohm) : x(soc, 0.0, r0_ohm), P(kP0) {}

void Ekf::predict(double current_A, double dt_s) {
  double a = std::exp(-dt_s / (params::ekf_r1_ohm * params::ekf_c1_F));
  x(0) -= current_A * dt_s / params::battery_capacity_C;
  x(1) = a * x(1) + params::ekf_r1_ohm * (1.0 - a) * current_A;
  Mat3 F = Vec3(1.0, a, 1.0).asDiagonal();
  P = F * P * F.transpose() + kQ * dt_s;
}

namespace {

double measure_V(const Ekf::Vec3& x, double current_A) {
  return battery::ocv_V(x(0)) - current_A * x(2) - x(1);
}

Eigen::RowVector3d jacobian(const Ekf::Vec3& x, double current_A) {
  return {battery::ocv_slope_V(x(0)), -1.0, -current_A};
}

}  // namespace

bool Ekf::update(double current_A, double voltage_V) {
  Eigen::RowVector3d H = jacobian(x, current_A);
  innovation_V = voltage_V - measure_V(x, current_A);
  double S = H * P * H.transpose() + params::ekf_r_V2;
  nis = innovation_V * innovation_V / S;

  if (nis > params::ekf_nis_gate) {
    if (consecutive_rejections_ < params::ekf_max_consecutive_rejections) {
      ++rejections;
      ++consecutive_rejections_;
      return false;
    }
    P(2, 2) += params::ekf_reopen_r0_sigma_ohm * params::ekf_reopen_r0_sigma_ohm;
    S = H * P * H.transpose() + params::ekf_r_V2;
  }
  consecutive_rejections_ = 0;

  // Gauss-Newton iterations, each relinearising about the latest estimate.
  Vec3 prior = x, xi = x, K;
  for (int i = 0; i < params::ekf_update_iterations; ++i) {
    H = jacobian(xi, current_A);
    K = P * H.transpose() / (H * P * H.transpose() + params::ekf_r_V2);
    xi = prior + K * (voltage_V - measure_V(xi, current_A) - H * (prior - xi));
  }
  x = xi;
  Mat3 I_KH = Mat3::Identity() - K * H;
  P = I_KH * P * I_KH.transpose() + K * params::ekf_r_V2 * K.transpose();  // Joseph form
  return true;
}

}  // namespace fsw
