cmake_minimum_required(VERSION 3.22)
project(nova_runtime LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The build workflow checks out llama.cpp into this path and removes it from the
# public APK repository after creating the release asset.
set(LLAMA_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../third_party/llama.cpp" CACHE PATH "llama.cpp checkout")
if (NOT EXISTS "${LLAMA_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR "llama.cpp was not fetched at ${LLAMA_ROOT}")
endif()

option(NOVA_ENABLE_VULKAN "Compile ggml's Vulkan backend" ON)

set(BUILD_SHARED_LIBS ON CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_APP OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_MTMD ON CACHE BOOL "" FORCE)
set(LLAMA_OPENSSL OFF CACHE BOOL "" FORCE)
set(LLAMA_SUBPROCESS OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_LLAMAFILE OFF CACHE BOOL "" FORCE)
set(GGML_CPU_ALL_VARIANTS OFF CACHE BOOL "" FORCE)
set(GGML_VULKAN ${NOVA_ENABLE_VULKAN} CACHE BOOL "" FORCE)
set(MTMD_VIDEO OFF CACHE BOOL "" FORCE)

add_subdirectory("${LLAMA_ROOT}" "llama-build")

add_library(nova_runtime SHARED nova_runtime.cpp)
target_include_directories(nova_runtime PRIVATE
        "${LLAMA_ROOT}/include"
        "${LLAMA_ROOT}/ggml/include"
        "${LLAMA_ROOT}/tools/mtmd")
target_compile_options(nova_runtime PRIVATE -fvisibility=hidden -fno-exceptions)
target_compile_definitions(nova_runtime PRIVATE NOVA_HAS_MTMD=1)
target_link_libraries(nova_runtime PRIVATE llama mtmd log android dl)

if (ANDROID)
    target_link_libraries(nova_runtime PRIVATE vulkan)
endif()
