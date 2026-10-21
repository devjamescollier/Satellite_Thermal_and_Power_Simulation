#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <fstream>

#include "flight_software.hpp"
#include "sensors.hpp"

using msg::Mode;

namespace {

std::vector<uint8_t> command(msg::Opcode op, std::vector<uint8_t> args = {}, uint16_t seq = 1) {
  args.insert(args.begin(), static_cast<uint8_t>(op));
  return ccsds::encode({ccsds::kApidCommand, true, seq, 0.0}, args);
}

// Decodes every event packet in the FSW outbox as {type, a, b, reason}.
std::vector<std::array<uint8_t, 4>> events(fsw::FlightSoftware& fsw) {
  std::vector<std::array<uint8_t, 4>> out;
  for (const auto& packet : fsw.take_telemetry()) {
    ccsds::Header h;
    std::vector<uint8_t> data;
    if (ccsds::decode(packet.data(), packet.size(), h, data) && h.apid == ccsds::kApidEvents) {
      out.push_back({data[0], data[1], data[2], data[3]});
    }
  }
  return out;
}

msg::SensorPacket nominal_sensors() {
  msg::SensorPacket s{};
  s.battery_V = 16.4;  // ~85% SOC
  for (double& temp_K : s.thermistor_K) temp_K = 290.0;
  return s;
}

}  // namespace

TEST(Ccsds, RoundTrip) {
  ccsds::Header in{0x12, true, 0x3ABC, 1234.75};
  std::vector<uint8_t> data{1, 2, 3, 250};
  auto packet = ccsds::encode(in, data);
  ASSERT_EQ(packet.size(), ccsds::kHeaderBytes + data.size());
  EXPECT_EQ(packet[0], 0x18);  // version 0, TC, secondary header, APID high bits
  EXPECT_EQ(packet[5], ccsds::kHeaderBytes - 6 + data.size() - 1);

  ccsds::Header out;
  std::vector<uint8_t> decoded;
  ASSERT_TRUE(ccsds::decode(packet.data(), packet.size(), out, decoded));
  EXPECT_EQ(out.apid, in.apid);
  EXPECT_EQ(out.is_command, in.is_command);
  EXPECT_EQ(out.seq_count, in.seq_count);
  EXPECT_DOUBLE_EQ(out.met_s, in.met_s);
  EXPECT_EQ(decoded, data);
  EXPECT_FALSE(ccsds::decode(packet.data(), packet.size() - 1, out, decoded));
}

// Writes the fixture that tests/test_ground.py decodes. Values must match there.
TEST(Ccsds, WritesHousekeepingFixture) {
  fsw::Housekeeping hk{Mode::kLoadShed,
                       true,
                       false,
                       true,
                       15.5f,
                       -1.25f,
                       0.5f,
                       0.375f,
                       {280.5f, 290.25f, 275.0f, 300.0f, 260.5f},
                       278.0f,
                       283.0f,
                       3,
                       1};
  auto packet =
      ccsds::encode({ccsds::kApidHousekeeping, false, 7, 123.5}, fsw::encode_housekeeping(hk));
  EXPECT_EQ(packet.size(), ccsds::kHeaderBytes + 52);
  std::ofstream(FIXTURE_DIR "/housekeeping.bin", std::ios::binary)
      .write(reinterpret_cast<const char*>(packet.data()), packet.size());
}

TEST(Fsw, ThermostatHysteresis) {
  fsw::Thermostat t;  // on below 278.15 K, off above 283.15 K
  EXPECT_FALSE(t.update(280.0));
  EXPECT_TRUE(t.update(278.0));
  EXPECT_TRUE(t.update(280.0));  // inside the deadband: stays on
  EXPECT_TRUE(t.update(283.0));
  EXPECT_FALSE(t.update(283.3));
  EXPECT_FALSE(t.update(280.0));  // inside the deadband: stays off
}

TEST(Fsw, ModeTransitions) {
  fsw::ModeManager m;
  double temps_K[params::kNumNodes] = {290, 290, 290, 290, 290};
  EXPECT_FALSE(m.update(0.80, temps_K));
  EXPECT_EQ(m.update(0.35, temps_K)->to, Mode::kLoadShed);
  EXPECT_FALSE(m.update(0.45, temps_K));  // hysteresis
  EXPECT_EQ(m.update(0.55, temps_K)->to, Mode::kNominal);
  EXPECT_EQ(m.update(0.20, temps_K)->reason, msg::ModeReason::kSocCritical);
  EXPECT_FALSE(m.update(0.90, temps_K));  // SAFE is sticky
  EXPECT_EQ(m.mode, Mode::kSafe);

  fsw::ModeManager hot;
  temps_K[params::kBattery] = 320.0;
  auto change = hot.update(0.90, temps_K);
  ASSERT_TRUE(change);
  EXPECT_EQ(change->to, Mode::kSafe);
  EXPECT_EQ(change->reason, msg::ModeReason::kRedLimit);
}

TEST(Fsw, SafeExitsOnlyByGroundCommand) {
  fsw::FlightSoftware fsw;
  msg::SensorPacket s = nominal_sensors();
  s.thermistor_K[params::kBattery] = 320.0;  // above the battery red limit
  fsw.cycle(s);
  EXPECT_EQ(fsw.mode(), Mode::kSafe);

  s = nominal_sensors();
  s.time_s = 1.0;
  EXPECT_FALSE(fsw.cycle(s).payload_on);
  EXPECT_EQ(fsw.mode(), Mode::kSafe);
  events(fsw);

  auto cmd = command(msg::Opcode::kSetMode, {0});
  fsw.queue_command(cmd.data(), cmd.size());
  s.time_s = 2.0;
  EXPECT_TRUE(fsw.cycle(s).payload_on);
  EXPECT_EQ(fsw.mode(), Mode::kNominal);
}

TEST(Fsw, EveryCommandIsAckedOrNacked) {
  fsw::FlightSoftware fsw;
  std::vector<std::vector<uint8_t>> cmds = {
      command(msg::Opcode::kNoop),
      command(msg::Opcode::kNoop, {1}),       // bad length
      command(static_cast<msg::Opcode>(99)),  // unknown opcode
      command(msg::Opcode::kSetMode, {7}),    // bad argument
      {0x00, 0x01, 0x02},                     // malformed
  };
  for (const auto& c : cmds) fsw.queue_command(c.data(), c.size());
  fsw.cycle(nominal_sensors());

  auto ev = events(fsw);
  ASSERT_EQ(ev.size(), cmds.size());
  using msg::NackReason;
  EXPECT_EQ(ev[0][0], uint8_t(msg::EventType::kCmdAck));
  EXPECT_EQ(ev[1][3], uint8_t(NackReason::kBadLength));
  EXPECT_EQ(ev[2][3], uint8_t(NackReason::kUnknownOpcode));
  EXPECT_EQ(ev[3][3], uint8_t(NackReason::kBadArgument));
  EXPECT_EQ(ev[4][3], uint8_t(NackReason::kMalformed));
  for (size_t i = 1; i < ev.size(); ++i) EXPECT_EQ(ev[i][0], uint8_t(msg::EventType::kCmdNack));
}

TEST(Integration, SimAndFswKeepBatteryAboveFreezingForThreeOrbits) {
  sim::Spacecraft sc;
  sim::SensorModel sensors;
  fsw::FlightSoftware fsw;
  double min_battery_K = 1e9;
  uint32_t seq = 0;
  while (sc.time_s < 3 * sc.orbit.period_s()) {
    sim::Telemetry t = sc.step();
    sim::apply_actuators(sc, fsw.cycle(sensors.sample(sc, t, ++seq)));
    min_battery_K = std::min(min_battery_K, sc.temps_K[params::kBattery]);
  }
  EXPECT_GT(min_battery_K, 273.15);
  EXPECT_EQ(fsw.mode(), Mode::kNominal);
}

TEST(Fsw, RadiatorMonitorComparesOrbitMeansFromEclipseEntry) {
  fsw::RadiatorMonitor m;
  double hot_K = params::radiator_expected_orbit_mean_K + params::radiator_orbit_margin_K + 1.0;
  auto orbit = [&](double temp_K) {  // 60 samples of sunlight, then 40 of eclipse
    bool raised = false;
    for (int i = 0; i < 100; ++i) raised = m.update(i < 60, temp_K) || raised;
    return raised;
  };
  EXPECT_FALSE(orbit(hot_K));  // the first eclipse entry only starts an orbit
  EXPECT_TRUE(orbit(hot_K));   // the next entry closes a full orbit above the margin
  EXPECT_NEAR(m.last_excess_K, hot_K - params::radiator_expected_orbit_mean_K, 1e-9);
  EXPECT_FALSE(orbit(hot_K));                                   // once per excursion
  EXPECT_FALSE(orbit(params::radiator_expected_orbit_mean_K));  // mostly nominal: re-arms
  EXPECT_FALSE(m.raised);
  EXPECT_TRUE(orbit(hot_K) || orbit(hot_K));  // hot again: raises again
}

// Counts RADIATOR_DEGRADED events over 12 orbits, with or without the radiator fault.
static int radiator_events(bool fault) {
  sim::Spacecraft sc;
  sim::SensorModel sensors;
  fsw::FlightSoftware fsw;
  if (fault) sc.faults.push_back({"radiator_degradation", sc.orbit.period_s()});
  int count = 0;
  uint32_t seq = 0;
  while (sc.time_s < 12 * sc.orbit.period_s()) {
    sim::Telemetry t = sc.step();
    sim::apply_actuators(sc, fsw.cycle(sensors.sample(sc, t, ++seq)));
    for (const auto& e : events(fsw)) {
      count += e[0] == static_cast<uint8_t>(msg::EventType::kRadiatorDegraded);
    }
  }
  return count;
}

TEST(Integration, RadiatorDegradedOnlyWithTheFault) {
  EXPECT_EQ(radiator_events(false), 0);
  EXPECT_EQ(radiator_events(true), 1);  // raised once, then stays above the margin
}
