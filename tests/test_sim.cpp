#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <vector>

#include "sensors.hpp"

using namespace params;

TEST(Thermal, FlatPlateReachesAnalyticEquilibrium) {
  const double alpha = 0.9, eps = 0.8;
  sim::ThermalNetwork net{{{"plate", 1000.0, 1.0, alpha, 1.0, eps}}, {}};
  std::vector<double> temps_K{200.0};
  for (int i = 0; i < 5000; ++i) sim::thermal_step(net, temps_K, {0.0}, true, 1.0);

  double expected_K = std::pow(alpha * solar_flux_W_m2 / (eps * stefan_boltzmann), 0.25);
  EXPECT_NEAR(temps_K[0], expected_K, 0.5);
}

TEST(Orbit, EclipseFractionMatchesAnalytic) {
  for (double beta_deg : {0.0, 30.0, 60.0}) {
    sim::Orbit orbit;
    orbit.beta_rad = beta_deg * pi / 180.0;
    const double h = orbit.altitude_m, R = earth_radius_m;
    double expected =
        std::acos(std::sqrt(h * h + 2 * R * h) / ((R + h) * std::cos(orbit.beta_rad))) / pi;

    int steps = static_cast<int>(orbit.period_s());
    int dark = 0;
    for (int i = 0; i < steps; ++i) dark += orbit.in_eclipse(i + 0.5);
    double simulated = static_cast<double>(dark) / steps;
    EXPECT_NEAR(simulated, expected, 0.01 * expected) << "beta = " << beta_deg;
  }
}

TEST(Spacecraft, EnergyIsConservedOverFiveOrbits) {
  sim::Spacecraft sc;
  double stored0_J = sc.stored_energy_J();
  while (sc.time_s < 5 * sc.orbit.period_s()) sc.step();

  double net_in_J = sc.absorbed_J - sc.radiated_J;
  double stored_change_J = sc.stored_energy_J() - stored0_J;
  // Tolerance is 0.5% of the absorbed solar energy (the dominant flow).
  EXPECT_NEAR(net_in_J, stored_change_J, 0.005 * sc.absorbed_J);
}

// Runs one orbit and returns its telemetry.
static std::vector<sim::Telemetry> run_orbit(sim::Spacecraft& sc) {
  std::vector<sim::Telemetry> out;
  int steps = static_cast<int>(std::lround(sc.orbit.period_s() / step_s));
  for (int i = 0; i < steps; ++i) out.push_back(sc.step());
  return out;
}

TEST(Spacecraft, DefaultConfigIsPowerPositiveAndPeriodic) {
  sim::Spacecraft sc;
  for (int orbit = 0; orbit < 18; ++orbit) run_orbit(sc);
  auto prev = run_orbit(sc);
  auto last = run_orbit(sc);

  double max_dT_K = 0.0, max_dsoc = 0.0, max_soc = 0.0;
  for (size_t i = 0; i < last.size(); ++i) {
    for (int n = 0; n < kNumNodes; ++n) {
      max_dT_K = std::max(max_dT_K, std::abs(last[i].temps_K[n] - prev[i].temps_K[n]));
    }
    max_dsoc = std::max(max_dsoc, std::abs(last[i].soc - prev[i].soc));
    max_soc = std::max(max_soc, last[i].soc);
  }
  EXPECT_LT(max_dT_K, 1.0);
  EXPECT_LT(max_dsoc, 0.01);
  EXPECT_GE(max_soc, soc_max);  // battery refills every orbit
}

TEST(Faults, ParsesEveryKnownFaultAndRejectsOthers) {
  sim::Fault f;
  for (const char* name : sim::kFaultNames) {
    EXPECT_TRUE(sim::parse_fault(std::string(name) + "@120", f)) << name;
    EXPECT_EQ(f.time_s, 120.0);
  }
  EXPECT_FALSE(sim::parse_fault("melted_array@10", f));
  EXPECT_FALSE(sim::parse_fault("degraded_cell", f));
}

TEST(Faults, StuckHeaterDrawsPowerDespiteOffCommand) {
  sim::Spacecraft healthy, faulty;
  faulty.faults.push_back({"stuck_on_heater", 0.0});
  sim::Telemetry th = healthy.step(), tf = faulty.step();
  // Battery terminal power is solar minus load (battery not full yet).
  EXPECT_NEAR(th.battery_V * th.battery_A - tf.battery_V * tf.battery_A, heater_W, 1e-6);
  sim::apply_actuators(faulty, {1, false, true, {}});  // FSW commands the heater off
  EXPECT_TRUE(faulty.loads.heater_on);
}

TEST(Faults, BiasedThermistorReadsHighOnlyOnBattery) {
  sim::Spacecraft healthy, faulty;
  faulty.faults.push_back({"biased_battery_thermistor", 0.0});
  sim::Telemetry th = healthy.step(), tf = faulty.step();
  sim::SensorModel a(7), b(7);  // same seed: same noise
  msg::SensorPacket sh = a.sample(healthy, th, 1), sf = b.sample(faulty, tf, 1);
  EXPECT_NEAR(sf.thermistor_K[kBattery] - sh.thermistor_K[kBattery], biased_thermistor_offset_K,
              1e-9);
  EXPECT_EQ(sf.thermistor_K[kAvionics], sh.thermistor_K[kAvionics]);
  EXPECT_EQ(faulty.temps_K, healthy.temps_K);  // the battery itself is unchanged
}

TEST(Faults, RadiatorDegradationWarmsRadiatorAndConservesEnergy) {
  sim::Spacecraft healthy, faulty;
  faulty.faults.push_back({"radiator_degradation", 0.0});
  double start_J = faulty.stored_energy_J();
  while (faulty.time_s < 2 * faulty.orbit.period_s()) {
    healthy.step();
    faulty.step();
  }
  EXPECT_DOUBLE_EQ(faulty.thermal.nodes[kRadiator].emissivity,
                   thermal_nodes[kRadiator].emissivity * radiator_degraded_emissivity_factor);
  EXPECT_GT(faulty.temps_K[kRadiator], healthy.temps_K[kRadiator] + 5.0);
  double error_J = faulty.absorbed_J - faulty.radiated_J - (faulty.stored_energy_J() - start_J);
  EXPECT_LT(std::abs(error_J), 0.005 * faulty.absorbed_J);
}
