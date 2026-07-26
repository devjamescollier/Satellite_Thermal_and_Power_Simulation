#include "flight_software.hpp"

#include <algorithm>

#include "battery_model.hpp"

namespace fsw {

using msg::Mode;
using msg::NackReason;
using msg::Opcode;

std::vector<uint8_t> encode_housekeeping(const Housekeeping& hk) {
  ccsds::Writer w;
  w.u8(static_cast<uint8_t>(hk.mode));
  w.u8(hk.heater_on);
  w.u8(hk.payload_on);
  w.u8(hk.sun_present);
  for (float v : {hk.battery_V, hk.battery_A, hk.array_A, hk.soc_est}) w.f32(v);
  for (float temp_K : hk.thermistor_K) w.f32(temp_K);
  w.f32(hk.heater_on_below_K);
  w.f32(hk.heater_off_above_K);
  w.u16(hk.cmd_accepted);
  w.u16(hk.cmd_rejected);
  return w.bytes;
}

std::vector<uint8_t> encode_estimator(const Ekf& ekf, double predicted_soc_exit, double r0_ratio) {
  ccsds::Writer w;
  for (int i = 0; i < 3; ++i) w.f32(static_cast<float>(ekf.x(i)));
  for (int i = 0; i < 3; ++i) w.f32(static_cast<float>(ekf.sigma()(i)));
  w.f32(static_cast<float>(ekf.innovation_V));
  w.f32(static_cast<float>(ekf.nis));
  w.u32(ekf.rejections);
  w.f32(static_cast<float>(predicted_soc_exit));
  w.f32(static_cast<float>(r0_ratio));
  return w.bytes;
}

msg::ActuatorPacket FlightSoftware::cycle(const msg::SensorPacket& s) {
  double dt_s = ekf_ ? s.time_s - met_s_ : 0.0;
  met_s_ = s.time_s;
  while (!commands_.empty()) {
    handle_command(commands_.front());
    commands_.pop_front();
  }
  bool heater_on = thermostat_.update(s.thermistor_K[params::kBattery]);
  double soc = run_estimator(s, dt_s);
  report(modes_.update(soc, s.thermistor_K));
  if (radiator_.update(s.sun_present, s.thermistor_K[params::kRadiator])) {
    auto tenths = static_cast<uint8_t>(std::min(radiator_.last_excess_K * 10.0, 255.0));
    emit_event(msg::EventType::kRadiatorDegraded, tenths, 0, 0, 0);
  }
  bool payload_on = payload_enabled_ && modes_.mode == Mode::kNominal;

  Housekeeping hk{modes_.mode,
                  heater_on,
                  payload_on,
                  s.sun_present != 0,
                  float(s.battery_V),
                  float(s.battery_A),
                  float(s.array_A),
                  float(soc),
                  {},
                  float(thermostat_.on_below_K),
                  float(thermostat_.off_above_K),
                  cmd_accepted_,
                  cmd_rejected_};
  for (int i = 0; i < params::kNumNodes; ++i) hk.thermistor_K[i] = float(s.thermistor_K[i]);
  emit(ccsds::kApidHousekeeping, encode_housekeeping(hk));
  return {s.seq, heater_on, payload_on, {0, 0}};
}

double FlightSoftware::run_estimator(const msg::SensorPacket& s, double dt_s) {
  double current_A = -s.battery_A;  // the EKF uses discharge-positive current
  double battery_K = s.thermistor_K[params::kBattery];
  if (!ekf_) {
    ekf_.emplace(initial_soc_.value_or(estimate_soc(s.battery_V)),
                 battery::r0_nominal_ohm(battery_K));
  } else {
    ekf_->predict(last_current_A_, dt_s);
  }
  ekf_->update(current_A, s.battery_V);
  last_current_A_ = current_A;

  double r0_ratio = ekf_->x(2) / battery::r0_nominal_ohm(battery_K);
  if (degradation_.update(ekf_->x(2), battery_K, dt_s)) {
    auto tenths = static_cast<uint8_t>(std::min(r0_ratio * 10.0, 255.0));
    emit_event(msg::EventType::kBatteryDegraded, tenths, 0, 0, 0);
  }
  predicted_soc_exit_ = eclipse_.update(s.sun_present, current_A, ekf_->x(0), dt_s);
  emit(ccsds::kApidEstimator, encode_estimator(*ekf_, predicted_soc_exit_, r0_ratio));
  return ekf_->x(0);
}

void FlightSoftware::queue_command(const uint8_t* packet, size_t size) {
  commands_.emplace_back(packet, packet + size);
}

std::vector<std::vector<uint8_t>> FlightSoftware::take_telemetry() {
  return std::exchange(outbox_, {});
}

void FlightSoftware::handle_command(const std::vector<uint8_t>& packet) {
  ccsds::Header h;
  std::vector<uint8_t> data;
  bool valid = ccsds::decode(packet.data(), packet.size(), h, data) && h.is_command &&
               h.apid == ccsds::kApidCommand && !data.empty();
  uint8_t opcode = valid ? data[0] : 0xFF;
  ccsds::Reader args{data.data(), data.size(), 1};
  NackReason result = valid ? execute(static_cast<Opcode>(opcode), args) : NackReason::kMalformed;

  bool accepted = result == NackReason::kNone;
  ++(accepted ? cmd_accepted_ : cmd_rejected_);
  emit_event(accepted ? msg::EventType::kCmdAck : msg::EventType::kCmdNack, opcode, 0,
             static_cast<uint8_t>(result), h.seq_count);
}

NackReason FlightSoftware::execute(Opcode op, ccsds::Reader& args) {
  switch (op) {
    case Opcode::kNoop:
      return args.done() ? NackReason::kNone : NackReason::kBadLength;
    case Opcode::kSetMode: {
      uint8_t mode = args.u8();
      if (!args.done()) return NackReason::kBadLength;
      if (mode > static_cast<uint8_t>(Mode::kSafe)) return NackReason::kBadArgument;
      report(modes_.set(static_cast<Mode>(mode), msg::ModeReason::kGroundCommand));
      return NackReason::kNone;
    }
    case Opcode::kPayloadOn:
    case Opcode::kPayloadOff:
      if (!args.done()) return NackReason::kBadLength;
      if (op == Opcode::kPayloadOn && modes_.mode != Mode::kNominal) return NackReason::kWrongMode;
      payload_enabled_ = op == Opcode::kPayloadOn;
      return NackReason::kNone;
    case Opcode::kSetHeaterSetpoints: {
      double on_below_K = args.f32(), off_above_K = args.f32();
      if (!args.done()) return NackReason::kBadLength;
      if (!(on_below_K < off_above_K) || on_below_K < params::setpoint_min_K ||
          off_above_K > params::setpoint_max_K) {
        return NackReason::kBadArgument;
      }
      thermostat_.on_below_K = on_below_K;
      thermostat_.off_above_K = off_above_K;
      return NackReason::kNone;
    }
  }
  return NackReason::kUnknownOpcode;
}

void FlightSoftware::report(const std::optional<ModeChange>& change) {
  if (!change) return;
  emit_event(msg::EventType::kModeChange, static_cast<uint8_t>(change->from),
             static_cast<uint8_t>(change->to), static_cast<uint8_t>(change->reason), 0);
}

void FlightSoftware::emit_event(msg::EventType type, uint8_t a, uint8_t b, uint8_t reason,
                                uint16_t cmd_seq) {
  ccsds::Writer w;
  for (uint8_t v : {static_cast<uint8_t>(type), a, b, reason}) w.u8(v);
  w.u16(cmd_seq);
  emit(ccsds::kApidEvents, w.bytes);
}

void FlightSoftware::emit(uint16_t apid, const std::vector<uint8_t>& data) {
  uint16_t& seq = seq_counts_[apid];
  outbox_.push_back(ccsds::encode({apid, false, seq, met_s_}, data));
  seq = (seq + 1) & 0x3FFF;
}

}  // namespace fsw
