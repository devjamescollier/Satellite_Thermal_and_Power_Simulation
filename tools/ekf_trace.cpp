// Runs the C++ EKF on one simulated orbit and writes everything the Python
// reference (ground/ref/ekf_ref.py) needs to reproduce it:
//   <dir>/ekf_config.json   filter parameters and initial state
//   <dir>/ekf_trace.csv     per step: dt, current, voltage, and the C++ estimates
// The run includes a 10% initial SOC error, a degraded_cell fault and one
// voltage spike, so the gate and the fault path are cross-checked too.
//   ekf_trace [DIR]

#include <cstdio>
#include <string>

#include "battery_model.hpp"
#include "ekf.hpp"
#include "sensors.hpp"

namespace {

void write_config(const std::string& path, const fsw::Ekf& ekf) {
  FILE* f = std::fopen(path.c_str(), "w");
  std::fprintf(f, "{\n  \"initial_x\": [%.17g, %.17g, %.17g],\n", ekf.x(0), ekf.x(1), ekf.x(2));
  std::fprintf(f, "  \"sigma0\": [%.17g, %.17g, %.17g],\n", params::ekf_sigma0[0],
               params::ekf_sigma0[1], params::ekf_sigma0[2]);
  std::fprintf(f, "  \"q\": [%.17g, %.17g, %.17g],\n", params::ekf_q[0], params::ekf_q[1],
               params::ekf_q[2]);
  std::fprintf(f, "  \"r_V2\": %.17g,\n  \"nis_gate\": %.17g,\n", params::ekf_r_V2,
               params::ekf_nis_gate);
  std::fprintf(f, "  \"update_iterations\": %d,\n", params::ekf_update_iterations);
  std::fprintf(f, "  \"max_consecutive_rejections\": %d,\n  \"reopen_r0_sigma_ohm\": %.17g,\n",
               params::ekf_max_consecutive_rejections, params::ekf_reopen_r0_sigma_ohm);
  std::fprintf(f, "  \"r1_ohm\": %.17g,\n  \"c1_F\": %.17g,\n", params::ekf_r1_ohm,
               params::ekf_c1_F);
  std::fprintf(f, "  \"capacity_C\": %.17g,\n  \"cells_in_series\": %d,\n",
               params::battery_capacity_C, params::cells_in_series);
  std::fprintf(f, "  \"ocv_cell_V\": [");
  for (int i = 0; i < params::ocv_points; ++i) {
    std::fprintf(f, "%s%.17g", i ? ", " : "", params::ocv_cell_V[i]);
  }
  std::fprintf(f, "]\n}\n");
  std::fclose(f);
}

}  // namespace

int main(int argc, char** argv) {
  std::string dir = argc > 1 ? argv[1] : ".";
  sim::Spacecraft sc;
  sc.faults.push_back({"degraded_cell", 2000.0});
  sim::SensorModel sensors;
  fsw::Ekf ekf(sc.battery.soc - 0.10, battery::r0_nominal_ohm(sc.temps_K[params::kBattery]));
  write_config(dir + "/ekf_config.json", ekf);

  FILE* csv = std::fopen((dir + "/ekf_trace.csv").c_str(), "w");
  if (!csv) {
    std::perror(dir.c_str());
    return 1;
  }
  std::fprintf(csv, "dt_s,current_A,voltage_V,soc,v_rc_V,r0_ohm,nis,accepted\n");
  int steps = static_cast<int>(sc.orbit.period_s() / params::step_s);
  double last_current_A = 0.0;
  for (int k = 0; k < steps; ++k) {
    sim::Telemetry t = sc.step();
    msg::SensorPacket s = sensors.sample(sc, t, k);
    double current_A = -s.battery_A;
    double voltage_V = s.battery_V + (k == 1500 ? 0.5 : 0.0);  // injected spike
    double dt_s = k > 0 ? params::step_s : 0.0;
    if (k > 0) ekf.predict(last_current_A, dt_s);
    bool accepted = ekf.update(current_A, voltage_V);
    last_current_A = current_A;
    std::fprintf(csv, "%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%d\n", dt_s, current_A, voltage_V,
                 ekf.x(0), ekf.x(1), ekf.x(2), ekf.nis, accepted ? 1 : 0);
  }
  std::fclose(csv);
  std::printf("ekf_trace: %d steps, %u rejections -> %s\n", steps, ekf.rejections, dir.c_str());
  return 0;
}
