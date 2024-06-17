cmake_minimum_required(VERSION 3.10)
project(pa_monitor)

set(Python_EXECUTABLE "/home/elijah/miniforge3/envs/audio/bin/python")
set(Python_INCLUDE_DIR "/home/elijah/miniforge3/envs/audio/include/python3.8")
set(Python_LIBRARY "/home/elijah/miniforge3/envs/audio/lib/libpython3.8.so")

set(pybind11_DIR "/home/elijah/miniforge3/envs/audio/lib/python3.8/site-packages/pybind11/share/cmake/pybind11")

# Find Python and pybind11 and libpulse/c++
find_package(Python REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(PULSE REQUIRED libpulse)

message(STATUS "Python version: ${Python_VERSION}")
message(STATUS "Python include dirs: ${Python_INCLUDE_DIRS}")
message(STATUS "Python libraries: ${Python_LIBRARIES}")
message(STATUS "PulseAudio include dirs: ${PULSE_INCLUDE_DIRS}")
message(STATUS "PulseAudio libraries: ${PULSE_LIBRARIES}")
message(STATUS "pybind11 include dirs: ${pybind11_INCLUDE_DIRS}")
message(STATUS "pybind11 libraries: ${pybind11_LIBRARIES}")

# Create the Python module
pybind11_add_module(pa_monitor src/ext.cpp)
target_include_directories(pa_monitor PRIVATE ${PULSE_INCLUDE_DIRS} ${pybind11_INCLUDE_DIRS} ${Python_INCLUDE_DIRS})
target_link_libraries(pa_monitor PRIVATE ${PULSE_LIBRARIES} ${pybind11_LIBRARIES} ${Python_LIBRARIES})
