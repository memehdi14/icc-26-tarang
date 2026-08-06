# Define minimal required version of CMake.
cmake_minimum_required(VERSION "3.25")

# Project definition
project(
	Tarang_Core_Pipeline
	VERSION 1.0
	LANGUAGES C CXX ASM
)

# Include the definition of the slc_Tarang_Core_Pipeline target,
# which contains the content of the SLC project
include(Tarang_Core_Pipeline.cmake)

add_executable(Tarang_Core_Pipeline
    # Add additional sources here
)

target_include_directories(Tarang_Core_Pipeline PUBLIC
    # Add additional include paths here
)

target_compile_definitions(Tarang_Core_Pipeline PUBLIC
    # Add additional macros here
)

target_compile_options(Tarang_Core_Pipeline PUBLIC
    # Set additional compiler flags here
)

target_link_options(Tarang_Core_Pipeline PUBLIC
    # Set additional linker flags here
)

# ==============================================
# SDK Configuration
# ==============================================

set(GSDK_ROOT "C:/Users/namda/.silabs/slt/installs/conan/p/simpl35774a752829c/p")

# Define PLATFORM_HEADER for Legacy HAL components
target_compile_definitions(slc PUBLIC
    PLATFORM_HEADER="hal/hal.h"
)

# Add include paths - platform_core ONLY (no zigbee dependency)
target_include_directories(slc PUBLIC
    # Platform Core HAL (no Zigbee dependency)
    ${GSDK_ROOT}/platform_core/platform/service/legacy_hal/inc
    
    # Platform common includes
    ${GSDK_ROOT}/platform/common/inc
    
    # EMLIB includes (for peripherals: I2C, LETIMER, IADC, USART, WDOG)
    ${GSDK_ROOT}/platform_core/platform/emlib/inc
    ${GSDK_ROOT}/platform/emlib/inc
    
    # Driver includes
    ${GSDK_ROOT}/platform/driver/inc
)

# ==============================================
# Add missing EMLIB source files for linking
# ==============================================
target_sources(slc PRIVATE
    # Watchdog functions (WDOGn_Init, WDOGn_Feed)
    ${GSDK_ROOT}/platform_core/platform/emlib/src/em_wdog.c
    
    # USART/SPI functions (USART_InitSync, USART_SpiTransfer)
    ${GSDK_ROOT}/platform_core/platform/emlib/src/em_usart.c
)

# Link with the content defined in the SLC project
target_link_libraries(Tarang_Core_Pipeline PRIVATE
    slc
)

# Include managed project content if available
include(Tarang_Core_Pipeline_project.cmake OPTIONAL RESULT_VARIABLE managed_project)
if(managed_project)
    message(STATUS "Using managed project content from ${managed_project}")
endif()

# Force the gcc linker command
set_target_properties(Tarang_Core_Pipeline PROPERTIES LINKER_LANGUAGE C)

# Create .bin, .hex and .s37 artifacts after building the project
add_custom_command(TARGET Tarang_Core_Pipeline
    POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} ${OBJCOPY_SREC_CMD} "$<TARGET_FILE:Tarang_Core_Pipeline>" "$<TARGET_FILE_DIR:Tarang_Core_Pipeline>/$<TARGET_FILE_BASE_NAME:Tarang_Core_Pipeline>.s37"
    COMMAND ${CMAKE_OBJCOPY} ${OBJCOPY_IHEX_CMD} "$<TARGET_FILE:Tarang_Core_Pipeline>" "$<TARGET_FILE_DIR:Tarang_Core_Pipeline>/$<TARGET_FILE_BASE_NAME:Tarang_Core_Pipeline>.hex"
    COMMAND ${CMAKE_OBJCOPY} ${OBJCOPY_BIN_CMD}  "$<TARGET_FILE:Tarang_Core_Pipeline>" "$<TARGET_FILE_DIR:Tarang_Core_Pipeline>/$<TARGET_FILE_BASE_NAME:Tarang_Core_Pipeline>.bin" 
)

# Run post-build pipeline to perform additional post-processing
if(post_build_command)
add_custom_command(TARGET Tarang_Core_Pipeline
    POST_BUILD
    WORKING_DIRECTORY ${CMAKE_CURRENT_LIST_DIR}/..
    COMMAND ${post_build_command}
)
endif()