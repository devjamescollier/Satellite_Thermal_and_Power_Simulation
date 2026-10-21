include(GoogleTest)

add_executable(test_sim test_sim.cpp)
target_link_libraries(test_sim PRIVATE sim_lib GTest::gtest_main)
gtest_discover_tests(test_sim PROPERTIES TIMEOUT 300)

add_executable(test_fsw test_fsw.cpp)
target_link_libraries(test_fsw PRIVATE fsw_lib sim_lib GTest::gtest_main)
target_compile_definitions(test_fsw PRIVATE FIXTURE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
gtest_discover_tests(test_fsw PROPERTIES TIMEOUT 300)

add_executable(test_ekf test_ekf.cpp)
target_link_libraries(test_ekf PRIVATE fsw_lib sim_lib GTest::gtest_main)
gtest_discover_tests(test_ekf PROPERTIES TIMEOUT 300)

# Python tests decode the fixture written by test_fsw, so run them after it.
find_program(UV_EXECUTABLE uv)
if(UV_EXECUTABLE)
  add_test(NAME pytest COMMAND ${UV_EXECUTABLE} run pytest -q WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
  set_tests_properties(pytest PROPERTIES ENVIRONMENT EKF_TRACE_BIN=$<TARGET_FILE:ekf_trace>)
  set_tests_properties(pytest PROPERTIES DEPENDS Ccsds.WritesHousekeepingFixture TIMEOUT 300)
endif()
