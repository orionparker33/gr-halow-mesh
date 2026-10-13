cmake_minimum_required(VERSION 3.16)
project(gr-halow-mesh VERSION 0.1.0 LANGUAGES C CXX)

find_package(Gnuradio "3.10" REQUIRED)
include(GrPython)
include(CTest)

gr_python_install(
  FILES
    python/halow_mesh/__init__.py
    python/halow_mesh/mesh_decode.py
    python/halow_mesh/protocol.py
    python/halow_mesh/pcap.py
    python/halow_mesh/pcap_source.py
    python/halow_mesh/iq_probe.py
  DESTINATION ${GR_PYTHON_DIR}/gnuradio/halow_mesh
)
install(FILES grc/halow_mesh_decode.block.yml
              grc/halow_mesh_pcap_source.block.yml
        DESTINATION share/gnuradio/grc/blocks)
install(PROGRAMS apps/halow_mesh_pcap.py DESTINATION bin)
install(PROGRAMS apps/halow_iq_probe.py DESTINATION bin)
install(FILES README.md LICENSE DESTINATION share/doc/gr-halow-mesh)

if(BUILD_TESTING)
  add_test(NAME halow_mesh_qa
           COMMAND ${PYTHON_EXECUTABLE}
                   ${CMAKE_CURRENT_SOURCE_DIR}/python/halow_mesh/qa_mesh_decode.py)
  set_tests_properties(halow_mesh_qa PROPERTIES
      ENVIRONMENT "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/python")
endif()
