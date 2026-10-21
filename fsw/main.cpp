// Flight software process. Answers every sensor packet with actuators, sends
// CCSDS telemetry to the ground, and queues telecommands from the ground.

#include <cstdio>

#include "flight_software.hpp"
#include "udp.hpp"

int main() {
  UdpSocket sensor_sock(params::port_sensors), command_sock(params::port_telecommands), out;
  fsw::FlightSoftware fsw;
  std::printf("fsw: sensors on %d, telecommands on %d\n", params::port_sensors,
              params::port_telecommands);
  std::fflush(stdout);

  uint8_t buf[2048];
  for (;;) {
    long n;
    while ((n = command_sock.receive(buf, sizeof buf, 0.0)) > 0) fsw.queue_command(buf, n);

    msg::SensorPacket sensors;
    if (sensor_sock.receive(&sensors, sizeof sensors, 0.05) != sizeof sensors) continue;
    msg::ActuatorPacket actuators = fsw.cycle(sensors);
    out.send_to(params::port_actuators, &actuators, sizeof actuators);
    for (const auto& packet : fsw.take_telemetry()) {
      out.send_to(params::port_telemetry, packet.data(), packet.size());
    }
  }
}
