#pragma once

#include <Eigen/Dense>
#include <cstdint>

namespace fsw {

// Battery Extended Kalman Filter. State x = [SOC, V_rc, R0] with R0 a random
// walk. Current is discharge-positive; the measurement is terminal voltage
//   V = OCV(SOC) - I*R0 - V_rc.
// The update is iterated (IEKF). ground/ref/ekf_ref.py mirrors this class line for line.
class Ekf {
 public:
  using Vec3 = Eigen::Vector3d;
  using Mat3 = Eigen::Matrix3d;

  Ekf(double soc, double r0_ohm);
  void predict(double current_A, double dt_s);
  bool update(double current_A, double voltage_V);  // false if the NIS gate rejected it

  Vec3 sigma() const { return P.diagonal().cwiseSqrt(); }

  Vec3 x;
  Mat3 P;
  double innovation_V = 0.0;
  double nis = 0.0;
  uint32_t rejections = 0;

 private:
  int consecutive_rejections_ = 0;
};

}  // namespace fsw
