cmake_minimum_required(VERSION 3.21)
project(antlr_pyfacade LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# The ANTLR4 C++ runtime sources are vendored into the repo (see
# vendor/antlr4-cpp/UPDATING.md). Self-contained so the sdist builds with no
# external checkout. Override with -DANTLR4_CPP_SRC=... only for development.
set(ANTLR4_CPP_SRC "${CMAKE_CURRENT_SOURCE_DIR}/vendor/antlr4-cpp/src"
    CACHE PATH "Path to ANTLR4 C++ runtime src directory")

if (NOT EXISTS "${ANTLR4_CPP_SRC}/ParserInterpreter.cpp")
  message(FATAL_ERROR "ANTLR4_CPP_SRC does not point at the C++ runtime src: ${ANTLR4_CPP_SRC}")
endif()

file(GLOB antlr4_runtime_SRC
  "${ANTLR4_CPP_SRC}/*.cpp"
  "${ANTLR4_CPP_SRC}/atn/*.cpp"
  "${ANTLR4_CPP_SRC}/dfa/*.cpp"
  "${ANTLR4_CPP_SRC}/internal/*.cpp"
  "${ANTLR4_CPP_SRC}/misc/*.cpp"
  "${ANTLR4_CPP_SRC}/support/*.cpp"
  "${ANTLR4_CPP_SRC}/tree/*.cpp"
  "${ANTLR4_CPP_SRC}/tree/pattern/*.cpp"
  "${ANTLR4_CPP_SRC}/tree/xpath/*.cpp"
)

find_package(Python 3.10 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(nanobind CONFIG REQUIRED)
find_package(Threads REQUIRED)

nanobind_add_module(_native STABLE_ABI
  cpp/binding.cpp
  ${antlr4_runtime_SRC}
)

target_compile_definitions(_native PRIVATE ANTLR4CPP_STATIC)
target_include_directories(_native PRIVATE
  "${ANTLR4_CPP_SRC}"
  "${ANTLR4_CPP_SRC}/tree/pattern"
  "${ANTLR4_CPP_SRC}/tree/xpath"
)
target_link_libraries(_native PRIVATE Threads::Threads)

install(TARGETS _native LIBRARY DESTINATION antlr_pyfacade)
