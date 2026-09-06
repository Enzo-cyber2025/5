cmake_minimum_required(VERSION 3.22.1)
project("vulcanmind")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_BUILD_TYPE Release)

# GGML Vulkan flag - se NDK não tiver Vulkan, faz fallback para CPU
option(GGML_VULKAN "Enable Vulkan" ON)

# Llama.cpp integration - se submodule existir, compila, senão usa stub
if(EXISTS ${CMAKE_SOURCE_DIR}/llama.cpp/CMakeLists.txt)
    message(STATUS "llama.cpp submodule found - building with Vulkan")
    set(LLAMA_VULKAN ON)
    set(GGML_VULKAN ON)
    add_subdirectory(llama.cpp)
else()
    message(STATUS "llama.cpp not found - building stub Vulkan backend")
endif()

add_library(vulcanmind SHARED
    native-lib.cpp
    gguf_memory_loader.cpp
    vulkan_backend.cpp
    inference_bridge.cpp
)

# Include dirs
target_include_directories(vulcanmind PRIVATE
    ${CMAKE_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/llama.cpp/include
    ${CMAKE_SOURCE_DIR}/llama.cpp/ggml/include
    ${CMAKE_SOURCE_DIR}/llama.cpp/common
)

find_library(log-lib log)
find_library(android-lib android)
find_library(vulkan-lib vulkan)

if(vulkan-lib)
    message(STATUS "Vulkan library found: ${vulkan-lib}")
    target_link_libraries(vulcanmind ${log-lib} ${android-lib} ${vulkan-lib})
    target_compile_definitions(vulcanmind PRIVATE HAS_VULKAN=1)
else()
    message(WARNING "Vulkan library not found - linking without Vulkan, runtime will detect")
    target_link_libraries(vulcanmind ${log-lib} ${android-lib})
    target_compile_definitions(vulcanmind PRIVATE HAS_VULKAN=0)
endif()

# Link llama if available
if(TARGET llama)
    target_link_libraries(vulcanmind llama ggml ggml-base)
    target_compile_definitions(vulcanmind PRIVATE HAS_LLAMA=1)
else()
    target_compile_definitions(vulcanmind PRIVATE HAS_LLAMA=0)
endif()

# Optimizations for GGUF direct memory
target_compile_options(vulcanmind PRIVATE
    -O3
    -march=armv8.2-a+fp16+dotprod
    -ffast-math
    -funroll-loops
)

# Hide symbols
set_target_properties(vulcanmind PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)
