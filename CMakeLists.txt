cmake_minimum_required(VERSION 3.16)
project(gr-halow-mesh VERSION 0.3.0 LANGUAGES C CXX)

find_package(Gnuradio "3.10" REQUIRED)
find_package(Python3 COMPONENTS Interpreter Development.Module REQUIRED)
include(GrPython)
include(CTest)

add_library(halow_mesh_fec MODULE cpp/fec.c)
target_link_libraries(halow_mesh_fec PRIVATE Python3::Module)
set_target_properties(halow_mesh_fec PROPERTIES PREFIX "" OUTPUT_NAME "_fec")
install(TARGETS halow_mesh_fec LIBRARY DESTINATION ${GR_PYTHON_DIR}/gnuradio/halow_mesh)

gr_python_install(
  FILES
    python/halow_mesh/__init__.py
    python/halow_mesh/mesh_decode.py
    python/halow_mesh/protocol.py
    python/halow_mesh/pcap.py
    python/halow_mesh/pcap_source.py
    python/halow_mesh/iq_probe.py
    python/halow_mesh/phy.py
    python/halow_mesh/iq_decode.py
  DESTINATION ${GR_PYTHON_DIR}/gnuradio/halow_mesh
)
install(FILES grc/halow_mesh_decode.block.yml
              grc/halow_mesh_pcap_source.block.yml
              grc/halow_mesh_iq_decode.block.yml
              grc/halow_mesh_iq_stream_decode.block.yml
        DESTINATION share/gnuradio/grc/blocks)
install(PROGRAMS apps/halow_mesh_pcap.py DESTINATION bin)
install(PROGRAMS apps/halow_iq_probe.py DESTINATION bin)
install(PROGRAMS apps/halow_iq_decode.py DESTINATION bin)
install(FILES README.md LICENSE THIRD_PARTY_NOTICES.md PHY_STATUS.md FORMAT_GAP_RESEARCH.md DESTINATION share/doc/gr-halow-mesh)

if(BUILD_TESTING)
  add_test(NAME halow_mesh_qa
           COMMAND ${PYTHON_EXECUTABLE}
                   ${CMAKE_CURRENT_SOURCE_DIR}/python/halow_mesh/qa_mesh_decode.py)
  set_tests_properties(halow_mesh_qa PROPERTIES
      ENVIRONMENT "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/python")
  add_test(NAME halow_phy_qa
           COMMAND ${PYTHON_EXECUTABLE}
                   ${CMAKE_CURRENT_SOURCE_DIR}/python/halow_mesh/qa_phy.py)
  set_tests_properties(halow_phy_qa PROPERTIES
      ENVIRONMENT "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/python")
  add_test(NAME halow_8mhz_data_field
           COMMAND ${PYTHON_EXECUTABLE}
                   ${CMAKE_CURRENT_SOURCE_DIR}/tests/validate_8mhz_data_field.py)
endif()
