cmake_minimum_required(VERSION 3.22.1)
project(ggufbridge)
add_library(ggufbridge SHARED ggufbridge.cpp)
target_link_libraries(ggufbridge android log dl)
