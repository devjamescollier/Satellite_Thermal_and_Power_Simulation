add_executable(ekf_trace ekf_trace.cpp)
target_link_libraries(ekf_trace PRIVATE sim_lib fsw_lib)

add_executable(mc_run mc_run.cpp)
target_link_libraries(mc_run PRIVATE sim_lib fsw_lib)
