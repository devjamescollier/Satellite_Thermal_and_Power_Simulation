#include "sensors.hpp"

#include <cmath>

#include "ccsds.hpp"

namespace sim {

msg::SensorPacket SensorModel::sample(const Spacecraft& sc, const Telemetry& last_step,
                                      uint32_t seq) {
  msg::SensorPacket s{};
  s.seq = seq;
  s.sun_present = !last_step.eclipse;
  s.time_s = sc.time_s;
  s.battery_V = last_step.battery_V + noise_V_(rng_);
  s.battery_A = last_step.battery_A + noise_A_(rng_);
  s.array_A = last_step.solar_W / last_step.battery_V;
  for (int i = 0; i < params::kNumNodes; ++i) {
    double noisy_K = sc.temps_K[i] + sc.thermistor_bias_K[i] + noise_K_(rng_);
    s.thermistor_K[i] =
        std::round(noisy_K / params::thermistor_resolution_K) * params::thermistor_resolution_K;
  }
  return s;
}

void apply_actuators(Spacecraft& sc, const msg::ActuatorPacket& actuators) {
  sc.loads.heater_on = actuators.heater_on || sc.loads.heater_stuck_on;
  sc.loads.payload_on = actuators.payload_on;
}

std::vector<uint8_t> encode_truth(const Spacecraft& sc, const Telemetry& last_step,
                                  uint32_t missed_cycles, uint16_t seq_count) {
  ccsds::Writer w;
  w.u8(last_step.eclipse);
  w.u8(sc.loads.payload_on);
  w.u8(sc.loads.heater_on);
  w.u8(0);  // spare
  for (double temp_K : sc.temps_K) w.f32(static_cast<float>(temp_K));
  w.f32(static_cast<float>(sc.battery.soc));
  w.f32(static_cast<float>(last_step.battery_V));
  w.f32(static_cast<float>(last_step.battery_A));
  w.f32(static_cast<float>(last_step.solar_W));
  w.u32(missed_cycles);
  w.f32(static_cast<float>(-sc.battery.rc_V));  // EKF sign convention (discharge-positive)
  w.f32(static_cast<float>(last_step.battery_r0_ohm));
  return ccsds::encode({ccsds::kApidSimTruth, false, seq_count, sc.time_s}, w.bytes);
}

}  // namespace sim
