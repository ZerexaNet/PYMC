cmake_minimum_required(VERSION 3.20)
project(pymc_native_tools LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ===========================================================
# Compiler flags
# ===========================================================
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-O2 -Wall -Wextra -fvisibility=hidden -fPIC)
    find_package(Threads REQUIRED)
endif()

if(MSVC)
    add_compile_options(/O2 /W3 /EHsc)
    # Static C runtime (/MT): the .exe / .dll files have no external DLL dependencies.
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)
endif()

# ===========================================================
# Terrain generator (vanilla worldgen, must match Java bit for bit: no FMA, no fast-math)
# ===========================================================
add_executable(terrain_gen native/terrain_gen.cpp)
target_compile_features(terrain_gen PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(terrain_gen PRIVATE /fp:precise /DNOMINMAX)
else()
    target_compile_options(terrain_gen PRIVATE -ffp-contract=off -fno-fast-math)
    target_link_libraries(terrain_gen PRIVATE Threads::Threads)
endif()

# ===========================================================
# Mob AI helper process (talks to the server over stdin/stdout)
# ===========================================================
add_executable(mob_ai native/mob_ai.cpp)

# ===========================================================
# Vanilla engine library: redstone / block updates, hoppers, explosions
# (loaded in-process by world/rs/native.py through ctypes)
# ===========================================================
add_library(pymc_vanilla SHARED native/vanilla/api.cpp)
target_compile_features(pymc_vanilla PRIVATE cxx_std_17)
if(MSVC)
    target_compile_options(pymc_vanilla PRIVATE /DNOMINMAX)
endif()

install(TARGETS
    terrain_gen
    mob_ai
    pymc_vanilla
    RUNTIME DESTINATION native
    LIBRARY DESTINATION native
)

# Windows + MinGW: statically link the C++ runtime so the binaries run without MinGW DLLs.
if(MINGW)
    set(MINGW_STATIC_LINK_FLAGS -static-libgcc -static-libstdc++ -static)
    target_link_options(terrain_gen PRIVATE ${MINGW_STATIC_LINK_FLAGS})
    target_link_options(mob_ai PRIVATE ${MINGW_STATIC_LINK_FLAGS})
    target_link_options(pymc_vanilla PRIVATE ${MINGW_STATIC_LINK_FLAGS})
endif()
