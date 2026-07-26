#pragma once

#include <deque>
#include <map>
#include <utility>
#include <vector>

#include "ccsds.hpp"
#include "control.hpp"
#include "ekf.hpp"

namespace fsw {

// Housekeeping telemetry contents (APID 0x10).
struct Housekeeping {
  msg::Mode mode;
  bool heater_on, payload_on, sun_present;
  float battery_V, battery_A, array_A, soc_est;
  float thermistor_K[params::kNumNodes];
  float heater_on_below_K, heater_off_above_K;
  uint16_t cmd_accepted, cmd_rejected;
};

std::vector<uint8_t> encode_housekeeping(const Housekeeping& hk);  // user data only
// Estimator telemetry (APID 0x11), user data only. r0_ratio is the R0 estimate over the
// nominal R0 at the measured battery temperature (the degradation monitor's input).
std::vector<uint8_t> encode_estimator(const Ekf& ekf, double predicted_soc_exit, double r0_ratio);

class FlightSoftware {
 public:
  // initial_soc seeds the EKF; by default it comes from the first voltage reading.
  explicit FlightSoftware(std::optional<double> initial_soc = std::nullopt)
      : initial_soc_(initial_soc) {}

  // One control cycle: telecommands, thermostat, mode manager, telemetry.
  msg::ActuatorPacket cycle(const msg::SensorPacket& sensors);
  void queue_command(const uint8_t* packet, size_t size);
  std::vector<std::vector<uint8_t>> take_telemetry();  // CCSDS packets for the ground

  msg::Mode mode() const { return modes_.mode; }
  const std::optional<Ekf>& ekf() const { return ekf_; }
  double predicted_soc_exit() const { return predicted_soc_exit_; }

 private:
  double run_estimator(const msg::SensorPacket& s, double dt_s);  // returns SOC
  void handle_command(const std::vector<uint8_t>& packet);
  msg::NackReason execute(msg::Opcode op, ccsds::Reader& args);
  void report(const std::optional<ModeChange>& change);
  void emit_event(msg::EventType type, uint8_t a, uint8_t b, uint8_t reason, uint16_t cmd_seq);
  void emit(uint16_t apid, const std::vector<uint8_t>& data);

  Thermostat thermostat_;
  ModeManager modes_;
  std::optional<double> initial_soc_;
  std::optional<Ekf> ekf_;
  double last_current_A_ = 0.0;  // discharge-positive, held for the next predict
  double predicted_soc_exit_ = 0.0;
  EclipsePredictor eclipse_;
  DegradationMonitor degradation_;
  RadiatorMonitor radiator_;
  bool payload_enabled_ = true;
  double met_s_ = 0.0;
  uint16_t cmd_accepted_ = 0, cmd_rejected_ = 0;
  std::map<uint16_t, uint16_t> seq_counts_;  // per APID
  std::deque<std::vector<uint8_t>> commands_;
  std::vector<std::vector<uint8_t>> outbox_;
};

}  // namespace fsw
