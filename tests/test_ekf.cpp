#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>

#include "battery_model.hpp"
#include "flight_software.hpp"
#include "sensors.hpp"

namespace {

// Sim + sensors driving a bare EKF. Truth is the battery at the start of each step,
// which is the state the measurement depends on.
struct EkfHarness {
  sim::Spacecraft sc;
  sim::SensorModel sensors;
  fsw::Ekf ekf;
  sim::Battery truth;
  msg::SensorPacket last{};
  double last_current_A = 0.0;
  bool started = false;

  explicit EkfHarness(double soc_error)
      : ekf(params::initial_soc + soc_error, battery::r0_nominal_ohm(params::initial_temp_K)) {}

  void step() {
    truth = sc.battery;
    last = sensors.sample(sc, sc.step(), 0);
    if (started) ekf.predict(last_current_A, params::step_s);
    ekf.update(-last.battery_A, last.battery_V);
    last_current_A = -last.battery_A;
    started = true;
  }
};

bool has_battery_degraded_event(fsw::FlightSoftware& fsw) {
  for (const auto& packet : fsw.take_telemetry()) {
    ccsds::Header h;
    std::vector<uint8_t> data;
    if (ccsds::decode(packet.data(), packet.size(), h, data) && h.apid == ccsds::kApidEvents &&
        data[0] == static_cast<uint8_t>(msg::EventType::kBatteryDegraded)) {
      return true;
    }
  }
  return false;
}

}  // namespace

TEST(Ekf, ConvergesFromTwentyPercentSocErrorWithinOneOrbit) {
  EkfHarness h(-0.20);
  double period_s = h.sc.orbit.period_s();
  double max_error_after_one_orbit = 0.0;
  while (h.sc.time_s < 2 * period_s) {
    h.step();
    if (h.sc.time_s > period_s) {
      max_error_after_one_orbit =
          std::max(max_error_after_one_orbit, std::abs(h.ekf.x(0) - h.truth.soc));
    }
  }
  EXPECT_LT(max_error_after_one_orbit, 0.02);
}

TEST(Ekf, DegradedCellR0ConvergesAndRaisesEvent) {
  sim::Spacecraft sc;
  sim::SensorModel sensors;
  fsw::FlightSoftware fsw;
  double period_s = sc.orbit.period_s();
  sc.faults.push_back({"degraded_cell", period_s});

  bool event = false;
  double r0_true = 0.0;
  uint32_t seq = 0;
  while (sc.time_s < 3 * period_s) {
    sim::Telemetry t = sc.step();
    sim::apply_actuators(sc, fsw.cycle(sensors.sample(sc, t, ++seq)));
    event = has_battery_degraded_event(fsw) || event;
    r0_true = t.battery_r0_ohm;
  }
  EXPECT_DOUBLE_EQ(sc.battery.r0_scale, params::degraded_cell_r0_factor);
  EXPECT_NEAR(fsw.ekf()->x(2), r0_true, 0.05 * r0_true);
  EXPECT_TRUE(event);
}

TEST(Ekf, NisGateRejectsVoltageSpike) {
  EkfHarness h(0.0);
  while (h.sc.time_s < 1000.0) h.step();

  fsw::Ekf::Vec3 before = h.ekf.x;
  uint32_t rejections = h.ekf.rejections;
  h.ekf.predict(-h.last.battery_A, params::step_s);
  fsw::Ekf::Vec3 predicted = h.ekf.x;
  EXPECT_FALSE(h.ekf.update(-h.last.battery_A, h.last.battery_V + 0.5));
  EXPECT_GT(h.ekf.nis, params::ekf_nis_gate);
  EXPECT_EQ(h.ekf.rejections, rejections + 1);
  EXPECT_EQ(h.ekf.x, predicted);  // a rejected measurement leaves the state alone
  EXPECT_NEAR(h.ekf.x(0), before(0), 1e-4);
}
