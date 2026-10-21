add_library(fsw_lib control.cpp ekf.cpp flight_software.cpp)
target_include_directories(fsw_lib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(fsw_lib PUBLIC common eigen)

add_executable(fsw main.cpp)
target_link_libraries(fsw PRIVATE fsw_lib)
