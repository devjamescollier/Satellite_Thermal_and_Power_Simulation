// One Monte Carlo or fault-campaign run: sim + FSW in one process (no UDP). The seed
// sets the sensor noise and an initial EKF SOC error drawn uniformly from +-15%.
//   mc_run --seed S [--orbits N] [--out FILE] [--packets FILE] [--fault NAME@TIME_S]...
// Writes one CSV row per step, with truth aligned to the state the EKF estimates
// (the battery at the start of the step that produced the measurement). --packets
// also writes every downlink packet (FSW telemetry, then sim truth), each preceded
// by its length as a big-endian u16.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>

#include "flight_software.hpp"
#include "sensors.hpp"

int main(int argc, char** argv) {
  unsigned seed = 1;
  double orbits = 10.0;
  std::string out_path = "mc.csv", packets_path;
  sim::Spacecraft sc;
  sim::Fault fault;
  for (int i = 1; i + 1 < argc; i += 2) {
    if (!std::strcmp(argv[i], "--seed")) seed = static_cast<unsigned>(std::atoi(argv[i + 1]));
    else if (!std::strcmp(argv[i], "--orbits")) orbits = std::atof(argv[i + 1]);
    else if (!std::strcmp(argv[i], "--out")) out_path = argv[i + 1];
    else if (!std::strcmp(argv[i], "--packets")) packets_path = argv[i + 1];
    else if (!std::strcmp(argv[i], "--fault") && sim::parse_fault(argv[i + 1], fault))
      sc.faults.push_back(fault);
  }

  std::mt19937 rng(seed);
  double soc_error = std::uniform_real_distribution<double>(-0.15, 0.15)(rng);
  sim::SensorModel sensors(seed);
  fsw::FlightSoftware fsw(sc.battery.soc + soc_error);

  FILE* csv = std::fopen(out_path.c_str(), "w");
  if (!csv) {
    std::perror(out_path.c_str());
    return 1;
  }
  FILE* packets = packets_path.empty() ? nullptr : std::fopen(packets_path.c_str(), "wb");
  if (!packets_path.empty() && !packets) {
    std::perror(packets_path.c_str());
    return 1;
  }
  auto write_packet = [packets](const std::vector<uint8_t>& p) {
    uint8_t len[2] = {static_cast<uint8_t>(p.size() >> 8), static_cast<uint8_t>(p.size())};
    std::fwrite(len, 1, 2, packets);
    std::fwrite(p.data(), 1, p.size(), packets);
  };
  std::fprintf(csv,
               "time_s,eclipse,soc_true,soc_est,soc_sigma,v_rc_true,v_rc_est,v_rc_sigma,"
               "r0_true,r0_est,r0_sigma,nees,nis,predicted_soc_exit\n");
  uint32_t seq = 0;
  while (sc.time_s < orbits * sc.orbit.period_s()) {
    sim::Battery before = sc.battery;
    sim::Telemetry t = sc.step();
    sim::apply_actuators(sc, fsw.cycle(sensors.sample(sc, t, ++seq)));
    auto telemetry = fsw.take_telemetry();  // drained every step even when not written
    if (packets) {
      for (const auto& p : telemetry) write_packet(p);
      write_packet(sim::encode_truth(sc, t, 0, static_cast<uint16_t>(seq)));
    }

    const fsw::Ekf& ekf = *fsw.ekf();
    fsw::Ekf::Vec3 truth(before.soc, -before.rc_V, t.battery_r0_ohm);
    fsw::Ekf::Vec3 error = truth - ekf.x;
    double nees = error.dot(ekf.P.ldlt().solve(error));
    fsw::Ekf::Vec3 sigma = ekf.sigma();
    std::fprintf(csv, "%.0f,%d", t.time_s, t.eclipse ? 1 : 0);
    for (int i = 0; i < 3; ++i) std::fprintf(csv, ",%.8g,%.8g,%.4g", truth(i), ekf.x(i), sigma(i));
    std::fprintf(csv, ",%.5g,%.5g,%.8g\n", nees, ekf.nis, fsw.predicted_soc_exit());
  }
  std::fclose(csv);
  if (packets) std::fclose(packets);
  return 0;
}
