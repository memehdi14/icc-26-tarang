# Define minimal required version of CMake.
cmake_minimum_required(VERSION "3.25")

# Project definition
project(
	Integration
	VERSION 1.0
	LANGUAGES C CXX ASM
)

# Include the definition of the slc_Integration target,
# which contains the content of the SLC project
include(Integration.cmake)

add_executable(Integration
    # Add additional sources here
    "${CMAKE_CURRENT_LIST_DIR}/../tarang_ble.c"
)

target_include_directories(Integration PUBLIC
    # Add additional include paths here
)

target_compile_definitions(Integration PUBLIC
    # Add additional macros here
)

target_compile_options(Integration PUBLIC
    # Set additional compiler flags here
)

target_link_options(Integration PUBLIC
    # Set additional linker flags here
)

# Link with the content defined in the SLC project
target_link_libraries(Integration PRIVATE
    slc
)

# Include managed project content if available
include(Integration_project.cmake OPTIONAL RESULT_VARIABLE managed_project)
if(managed_project)
    message(STATUS "Using managed project content from ${managed_project}")
endif()

# Force the gcc linker command
set_target_properties(Integration PROPERTIES LINKER_LANGUAGE C)

# Create .bin, .hex and .s37 artifacts after building the project
add_custom_command(TARGET Integration
    POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} ${OBJCOPY_SREC_CMD} "$<TARGET_FILE:Integration>" "$<TARGET_FILE_DIR:Integration>/$<TARGET_FILE_BASE_NAME:Integration>.s37"
    COMMAND ${CMAKE_OBJCOPY} ${OBJCOPY_IHEX_CMD} "$<TARGET_FILE:Integration>" "$<TARGET_FILE_DIR:Integration>/$<TARGET_FILE_BASE_NAME:Integration>.hex"
    COMMAND ${CMAKE_OBJCOPY} ${OBJCOPY_BIN_CMD}  "$<TARGET_FILE:Integration>" "$<TARGET_FILE_DIR:Integration>/$<TARGET_FILE_BASE_NAME:Integration>.bin" 
)

# Run post-build pipeline to perform additional post-processing
if(post_build_command)
add_custom_command(TARGET Integration
    POST_BUILD
    WORKING_DIRECTORY ${CMAKE_CURRENT_LIST_DIR}/..
    COMMAND ${post_build_command}
)
endif()