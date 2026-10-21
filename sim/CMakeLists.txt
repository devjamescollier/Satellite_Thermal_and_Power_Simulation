add_library(sim_lib orbit.cpp thermal.cpp power.cpp spacecraft.cpp sensors.cpp)
target_include_directories(sim_lib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(sim_lib PUBLIC common)

add_executable(sim main.cpp)
target_link_libraries(sim PRIVATE sim_lib)
