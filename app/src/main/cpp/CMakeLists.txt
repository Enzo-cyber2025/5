cmake_minimum_required(VERSION 3.31.6)

project("llmcore" VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED true)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED true)

set(CMAKE_C_FLAGS   "${CMAKE_C_FLAGS}"   CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}" CACHE STRING "" FORCE)

if(DEFINED ANDROID_ABI)
    message(STATUS "Detected Android ABI: ${ANDROID_ABI}")
    if(ANDROID_ABI STREQUAL "arm64-v8a")
        set(GGML_SYSTEM_ARCH "ARM")
        set(GGML_CPU_KLEIDIAI OFF)
    else()
        message(FATAL_ERROR "Unsupported ABI: ${ANDROID_ABI}")
    endif()
endif()

# llama.cpp is vendored into <repo>/third_party/llama.cpp by the build
# pipeline (see .github/workflows/android.yml). Point the symlink there for
# local builds.
set(LLAMA_SRC ${CMAKE_CURRENT_LIST_DIR}/../../../../third_party/llama.cpp)
if(NOT EXISTS ${LLAMA_SRC}/CMakeLists.txt)
    message(FATAL_ERROR "llama.cpp not found at ${LLAMA_SRC} - clone it there first")
endif()

add_subdirectory(${LLAMA_SRC} build-llama)

add_library(llmcore SHARED
        llmcore.cpp)

target_compile_definitions(llmcore PRIVATE
        GGML_SYSTEM_ARCH=${GGML_SYSTEM_ARCH}
        GGML_CPU_KLEIDIAI=$<BOOL:${GGML_CPU_KLEIDIAI}>
        GGML_OPENMP=$<BOOL:${GGML_OPENMP}>
)

# libllama exposes the C API; libmtmd adds multimodal support; common brings
# chat templates + samplers; ggml-cpu/vulkan are linked through libllama.
target_link_libraries(llmcore
        PRIVATE
        llama
        ggml
        common
        mtmd
        android
        log
        vulkan)

target_include_directories(llmcore PRIVATE
        ${LLAMA_SRC}
        ${LLAMA_SRC}/common
        ${LLAMA_SRC}/include
        ${LLAMA_SRC}/ggml/include
        ${LLAMA_SRC}/tools/mtmd
        ${LLAMA_SRC}/vendor/nlohmann)
