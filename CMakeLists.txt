cmake_minimum_required(VERSION 3.20)
project(pymc_native_tools LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ===========================================================
# Compiler flags
# ===========================================================
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-O2 -Wall -Wextra -fvisibility=hidden)
    # Position-independent code for shared libraries
    add_compile_options(-fPIC)
    # Threading support
    find_package(Threads REQUIRED)
endif()

if(MSVC)
    add_compile_options(/O2 /W3 /EHsc)
    # Use static C runtime (/MT) so the resulting .exe files have no
    # external DLL dependencies. This applies to Debug builds too;
    # Debug will use /MTd instead via CMAKE_MSVC_RUNTIME_LIBRARY.
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    # Export all symbols for DLL
    set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)
endif()

# ===========================================================
# Legacy targets (original subprocess-based tools)
# ===========================================================
add_executable(terrain_gen native/terrain_gen.cpp)
add_executable(mob_ai native/mob_ai.cpp)

# rootree_worldgen uses C++20 features (std::rotl)
add_executable(rootree_worldgen src/main.cpp)
set_target_properties(rootree_worldgen PROPERTIES CXX_STANDARD 20)

# ===========================================================
# Core IPC shared memory library
# ===========================================================
add_library(ipc_shm STATIC
    native/core/ipc_shm.cpp
)
target_include_directories(ipc_shm PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
)
if(APPLE)
    target_link_libraries(ipc_shm PUBLIC Threads::Threads)
elseif(UNIX)
    target_link_libraries(ipc_shm PUBLIC Threads::Threads rt)
endif()

# ===========================================================
# Redstone Engine
# ===========================================================
add_library(redstone_engine STATIC
    native/redstone/redstone_engine.cpp
)
target_include_directories(redstone_engine PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/native/redstone
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
)
target_link_libraries(redstone_engine PUBLIC ipc_shm)

# ===========================================================
# Light Engine
# ===========================================================
add_library(light_engine STATIC
    native/lighting/light_engine.cpp
)
target_include_directories(light_engine PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/native/lighting
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
)
target_link_libraries(light_engine PUBLIC ipc_shm)

# ===========================================================
# Physics Engine
# ===========================================================
add_library(physics_engine STATIC
    native/physics/physics_engine.cpp
)
target_include_directories(physics_engine PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/native/physics
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
)
target_link_libraries(physics_engine PUBLIC ipc_shm)

# ===========================================================
# Native server process (uses shared memory IPC)
# ===========================================================
add_executable(pymc_native_server
    native/pymc_native_server.cpp
)
target_include_directories(pymc_native_server PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/native
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
    ${CMAKE_CURRENT_SOURCE_DIR}/native/redstone
    ${CMAKE_CURRENT_SOURCE_DIR}/native/lighting
    ${CMAKE_CURRENT_SOURCE_DIR}/native/physics
)
target_link_libraries(pymc_native_server PRIVATE
    ipc_shm
    redstone_engine
    light_engine
    physics_engine
)

# ===========================================================
# Combined shared library for in-process Python bindings
# (can be loaded via ctypes/cffi)
# ===========================================================
add_library(pymc_native SHARED
    native/bindings/pymc_native_api.cpp
    native/core/ipc_shm.cpp
    native/redstone/redstone_engine.cpp
    native/lighting/light_engine.cpp
    native/physics/physics_engine.cpp
)
target_include_directories(pymc_native PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/native
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
    ${CMAKE_CURRENT_SOURCE_DIR}/native/redstone
    ${CMAKE_CURRENT_SOURCE_DIR}/native/lighting
    ${CMAKE_CURRENT_SOURCE_DIR}/native/physics
    ${CMAKE_CURRENT_SOURCE_DIR}/native/bindings
)
if(APPLE)
    target_link_libraries(pymc_native PUBLIC Threads::Threads)
elseif(UNIX)
    target_link_libraries(pymc_native PUBLIC Threads::Threads rt)
endif()

# ===========================================================
# PYMC Plugin API
# ===========================================================

# Event System (header-only, always built)
add_library(plugin_event_system INTERFACE)
target_include_directories(plugin_event_system INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/native/plugins
)

# PYMC Plugin API types (header-only, renamed from bukkit_api)
add_library(plugin_pymc_api INTERFACE)
target_include_directories(plugin_pymc_api INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/native/plugins
)

# Plugin Loader (header-only, orchestrates the other components)
add_library(plugin_loader INTERFACE)
target_include_directories(plugin_loader INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/native/plugins
)
target_link_libraries(plugin_loader INTERFACE
    plugin_event_system
    plugin_pymc_api
)

# Combined plugin shared library for Python ctypes bindings
# This will include C API bridge functions when implementation files are added
add_library(pymc_plugin_loader SHARED
    native/plugins/plugin_loader_api.cpp
)
target_include_directories(pymc_plugin_loader PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/native
    ${CMAKE_CURRENT_SOURCE_DIR}/native/plugins
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
)
target_link_libraries(pymc_plugin_loader PUBLIC
    plugin_loader
    ipc_shm
)
if(APPLE)
    target_link_libraries(pymc_plugin_loader PUBLIC Threads::Threads)
elseif(UNIX)
    target_link_libraries(pymc_plugin_loader PUBLIC Threads::Threads rt dl)
endif()

# ===========================================================
# PYMC Native Mod API
# ===========================================================

# Mod Loader (header-only, core mod discovery & lifecycle management)
add_library(mod_loader INTERFACE)
target_include_directories(mod_loader INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/native/mods
    ${CMAKE_CURRENT_SOURCE_DIR}/native/plugins
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
)

# PYMC Mod C API (header-only, C API bridge for ctypes)
add_library(mod_pymc_api INTERFACE)
target_include_directories(mod_pymc_api INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/native/mods
)
target_link_libraries(mod_pymc_api INTERFACE
    mod_loader
)

# Combined mod shared library for Python ctypes bindings
add_library(pymc_mod_loader SHARED
    native/plugins/plugin_loader_api.cpp
)
target_include_directories(pymc_mod_loader PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/native
    ${CMAKE_CURRENT_SOURCE_DIR}/native/mods
    ${CMAKE_CURRENT_SOURCE_DIR}/native/plugins
    ${CMAKE_CURRENT_SOURCE_DIR}/native/core
)
target_link_libraries(pymc_mod_loader PUBLIC
    mod_loader
    mod_pymc_api
    ipc_shm
)
if(APPLE)
    target_link_libraries(pymc_mod_loader PUBLIC Threads::Threads)
elseif(UNIX)
    target_link_libraries(pymc_mod_loader PUBLIC Threads::Threads rt dl)
endif()

# ===========================================================
# Install targets
# ===========================================================
install(TARGETS
    terrain_gen
    mob_ai
    pymc_native_server
    pymc_native
    pymc_plugin_loader
    pymc_mod_loader
    RUNTIME DESTINATION native
    LIBRARY DESTINATION native
)

# ===========================================================
# Windows + MinGW: statically link the C++ runtime libraries
# (libgcc, libstdc++, libwinpthread) so the resulting .exe files
# can run on user machines without requiring MSYS2/MinGW DLLs
# in PATH. Without this, terrain_gen.exe / mob_ai.exe crash
# immediately on machines that don't have MinGW installed.
#
# This must come AFTER all add_executable() calls because
# target_link_options requires the target to already exist.
# ===========================================================
if(MINGW)
    set(MINGW_STATIC_LINK_FLAGS
        -static-libgcc
        -static-libstdc++
        -static
    )
    target_link_options(terrain_gen        PRIVATE ${MINGW_STATIC_LINK_FLAGS})
    target_link_options(mob_ai             PRIVATE ${MINGW_STATIC_LINK_FLAGS})
    target_link_options(pymc_native_server PRIVATE ${MINGW_STATIC_LINK_FLAGS})
endif()
