// Spacecraft simulator. Each step: advance physics, send sensors to FSW, wait for
// the actuator reply (on timeout keep the last actuators and count a missed cycle).
//   sim [--orbits N] [--speed X] [--beta DEG] [--out FILE] [--fault NAME@TIME_S]...
// --speed 1 is real time, 60 is 60x, 0 runs as fast as FSW answers.
// Faults: degraded_cell, stuck_on_heater, biased_battery_thermistor, radiator_degradation
// (see params.hpp).

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>

#include "sensors.hpp"
#include "udp.hpp"

namespace {

using Clock = std::chrono::steady_clock;
using Seconds = std::chrono::duration<double>;

// Waits for the reply matching seq, dropping stale ones. False on timeout.
bool wait_for_actuators(const UdpSocket& sock, uint32_t seq, msg::ActuatorPacket& out) {
  auto deadline = Clock::now() + Seconds(params::actuator_timeout_s);
  msg::ActuatorPacket reply;
  for (;;) {
    double left_s = Seconds(deadline - Clock::now()).count();
    if (left_s <= 0.0) return false;
    if (sock.receive(&reply, sizeof reply, left_s) != sizeof reply) continue;
    if (reply.seq == seq) return out = reply, true;
  }
}

void write_csv_header(FILE* csv, const sim::Spacecraft& sc) {
  std::fprintf(csv, "time_s,eclipse");
  for (const auto& node : sc.thermal.nodes) std::fprintf(csv, ",T_%s_K", node.name);
  std::fprintf(csv, ",soc,battery_V,battery_A,solar_W\n");
}

void write_csv_row(FILE* csv, const sim::Telemetry& t) {
  std::fprintf(csv, "%.0f,%d", t.time_s, t.eclipse ? 1 : 0);
  for (double temp_K : t.temps_K) std::fprintf(csv, ",%.3f", temp_K);
  std::fprintf(csv, ",%.5f,%.4f,%.4f,%.3f\n", t.soc, t.battery_V, t.battery_A, t.solar_W);
}

constexpr const char* kUsage =
    "usage: sim [--orbits N] [--speed X] [--beta DEG] [--out FILE] [--fault NAME@TIME_S]\n"
    "faults: degraded_cell, stuck_on_heater, biased_battery_thermistor, radiator_degradation\n";

}  // namespace

int main(int argc, char** argv) {
  double orbits = 3.0, speed = 0.0;
  std::string csv_path;
  sim::Spacecraft sc;
  sim::Fault fault;
  for (int i = 1; i + 1 < argc; i += 2) {
    if (!std::strcmp(argv[i], "--orbits")) orbits = std::atof(argv[i + 1]);
    else if (!std::strcmp(argv[i], "--speed")) speed = std::atof(argv[i + 1]);
    else if (!std::strcmp(argv[i], "--beta"))
      sc.orbit.beta_rad = std::atof(argv[i + 1]) * params::pi / 180.0;
    else if (!std::strcmp(argv[i], "--out")) csv_path = argv[i + 1];
    else if (!std::strcmp(argv[i], "--fault") && sim::parse_fault(argv[i + 1], fault))
      sc.faults.push_back(fault);
    else {
      std::fprintf(stderr, "%s", kUsage);
      return 1;
    }
  }

  FILE* csv = csv_path.empty() ? nullptr : std::fopen(csv_path.c_str(), "w");
  if (!csv_path.empty() && !csv) {
    std::perror(csv_path.c_str());
    return 1;
  }
  if (csv) write_csv_header(csv, sc);

  UdpSocket actuator_sock(params::port_actuators), out;
  sim::SensorModel sensors;
  msg::ActuatorPacket actuators{0, sc.loads.heater_on, sc.loads.payload_on, {}};
  uint32_t seq = 0, missed = 0;
  auto start = Clock::now();

  while (sc.time_s < orbits * sc.orbit.period_s()) {
    sim::Telemetry t = sc.step();
    if (csv) write_csv_row(csv, t);
    msg::SensorPacket s = sensors.sample(sc, t, ++seq);
    out.send_to(params::port_sensors, &s, sizeof s);
    auto truth = sim::encode_truth(sc, t, missed, static_cast<uint16_t>(seq));
    out.send_to(params::port_sim_truth, truth.data(), truth.size());

    if (!wait_for_actuators(actuator_sock, seq, actuators)) ++missed;
    sim::apply_actuators(sc, actuators);
    if (speed > 0.0) {
      auto due = start + std::chrono::duration_cast<Clock::duration>(Seconds(sc.time_s / speed));
      std::this_thread::sleep_until(due);
    }
  }
  if (csv) std::fclose(csv);
  std::printf("sim: %.1f orbits, %u steps, %u missed actuator cycles\n", orbits, seq, missed);
  return 0;
}
