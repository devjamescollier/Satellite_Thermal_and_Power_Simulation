#pragma once

#include <random>
#include <vector>

#include "messages.hpp"
#include "spacecraft.hpp"

namespace sim {

// Turns the true spacecraft state into noisy, quantized sensor readings.
class SensorModel {
 public:
  explicit SensorModel(unsigned seed = params::sensor_seed) : rng_(seed) {}
  msg::SensorPacket sample(const Spacecraft& sc, const Telemetry& last_step, uint32_t seq);

 private:
  std::mt19937 rng_;
  std::normal_distribution<double> noise_K_{0.0, params::thermistor_noise_K};
  std::normal_distribution<double> noise_V_{0.0, params::voltage_noise_V};
  std::normal_distribution<double> noise_A_{0.0, params::current_noise_A};
};

void apply_actuators(Spacecraft& sc, const msg::ActuatorPacket& actuators);

// SIM-ONLY ground-truth packet (APID 0x20) for comparing FSW estimates to reality.
std::vector<uint8_t> encode_truth(const Spacecraft& sc, const Telemetry& last_step,
                                  uint32_t missed_cycles, uint16_t seq_count);

}  // namespace sim
