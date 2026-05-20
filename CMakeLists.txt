cmake_minimum_required(VERSION 3.20)
project(pymc_native_tools LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(terrain_gen native/terrain_gen.cpp)
add_executable(rootree_worldgen src/main.cpp)
