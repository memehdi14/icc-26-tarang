####################################################################
# Automatically-generated file. Do not edit!                       #
####################################################################

set(SDK_PATH "/Users/kedarnayak/.silabs/slt/installs/conan/p/simpleca33d691c539/p")
set(COPIED_SDK_PATH "simplicity_sdk_2026.6.1")
set(PKG_PATH "/Users/kedarnayak/.silabs/slt/installs")

add_library(slc OBJECT
    "${SDK_PATH}/boards/hardware/board/src/sl_board_control_gpio.c"
    "${SDK_PATH}/boards/hardware/board/src/sl_board_init.c"
    "${SDK_PATH}/platform_core/hardware/driver/configuration_over_swo/src/sl_cos.c"
    "${SDK_PATH}/platform_core/platform/common/src/sl_assert.c"
    "${SDK_PATH}/platform_core/platform/common/src/sl_core_cortexm.c"
    "${SDK_PATH}/platform_core/platform/common/src/sl_slist.c"
    "${SDK_PATH}/platform_core/platform/common/src/sl_string.c"
    "${SDK_PATH}/platform_core/platform/common/src/sl_syscalls.c"
    "${SDK_PATH}/platform_core/platform/Device/SiliconLabs/EFR32MG26/Source/startup_efr32mg26.c"
    "${SDK_PATH}/platform_core/platform/Device/SiliconLabs/EFR32MG26/Source/system_efr32mg26.c"
    "${SDK_PATH}/platform_core/platform/driver/debug/src/sl_debug_swo.c"
    "${SDK_PATH}/platform_core/platform/driver/dma_channel/src/sl_dma_channel.c"
    "${SDK_PATH}/platform_core/platform/driver/dma_channel/src/sl_dma_descriptor_allocator.c"
    "${SDK_PATH}/platform_core/platform/driver/gpio/src/sl_gpio.c"
    "${SDK_PATH}/platform_core/platform/driver/i2c/src/sl_i2c.c"
    "${SDK_PATH}/platform_core/platform/driver/i2cspm/src/sl_i2cspm.c"
    "${SDK_PATH}/platform_core/platform/emdrv/gpiointerrupt/src/gpiointerrupt.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_burtc.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_cmu.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_emu.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_gpio.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_i2c.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_letimer.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_msc.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_prs.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_system.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_timer.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_usart.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_gpio.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_i2c.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_ldma.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_syscfg.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_sysrtc.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_sysrtc_subsystem.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_system.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager_hal_s2.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager_init.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager_init_hal_s2.c"
    "${SDK_PATH}/platform_core/platform/service/device_init/src/sl_device_init_dcdc_s2.c"
    "${SDK_PATH}/platform_core/platform/service/device_init/src/sl_device_init_emu_s2.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/clocks/sl_device_clock_efr32xg26.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/devices/sl_device_peripheral_hal_efr32xg26.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/dma/sl_device_dma_s2.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_clock.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_dma.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_gpio.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_peripheral.c"
    "${SDK_PATH}/platform_core/platform/service/dma_manager/src/sl_dma_manager.c"
    "${SDK_PATH}/platform_core/platform/service/dma_manager/src/sl_dma_manager_hal_ldma.c"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/src/sl_interrupt_manager_cortexm.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_debug.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_dmadrv.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_retarget_stdio.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_swo_itm_8.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_uart.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_usart.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_dynamic_reservation.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_pool.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_pool_common.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_region.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_retarget.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sli_memory_manager_common.c"
    "${SDK_PATH}/platform_core/platform/service/sl_main/src/sl_main_init.c"
    "${SDK_PATH}/platform_core/platform/service/sl_main/src/sl_main_init_memory.c"
    "${SDK_PATH}/platform_core/platform/service/sl_main/src/sl_main_process_action.c"
    "${SDK_PATH}/platform_core/platform/service/sleeptimer/src/sl_sleeptimer.c"
    "${SDK_PATH}/platform_core/platform/service/sleeptimer/src/sl_sleeptimer_hal_burtc.c"
    "${SDK_PATH}/platform_core/platform/service/sleeptimer/src/sl_sleeptimer_hal_sysrtc.c"
    "${SDK_PATH}/platform_core/platform/service/sleeptimer/src/sl_sleeptimer_hal_timer.c"
    "${SDK_PATH}/platform_core/platform/service/udelay/src/sl_udelay.c"
    "${SDK_PATH}/platform_core/platform/service/udelay/src/sl_udelay_armv6m_gcc.S"
    "../app.c"
    "../autogen/sl_board_default_init.c"
    "../autogen/sl_dma_manager_instances.c"
    "../autogen/sl_event_handler.c"
    "../autogen/sl_i2cspm_init.c"
    "../autogen/sl_iostream_handles.c"
    "../autogen/sl_iostream_init_usart_instances.c"
    "../main.c"
)

target_include_directories(slc PUBLIC
   "../config"
   "../autogen"
   "../."
    "${SDK_PATH}/platform_core/platform/Device/SiliconLabs/EFR32MG26/Include"
    "${SDK_PATH}/platform_core/platform/common/inc"
    "${SDK_PATH}/boards/hardware/board/inc"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src"
    "${SDK_PATH}/cmsis/Core/Include"
    "${SDK_PATH}/cmsis/Core/Include/m-profile"
    "${SDK_PATH}/cmsis/Core/Include/a-profile"
    "${SDK_PATH}/platform_core/hardware/driver/configuration_over_swo/inc"
    "${SDK_PATH}/platform_core/platform/driver/debug/inc"
    "${SDK_PATH}/platform_core/platform/service/device_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/device_init/inc"
    "${SDK_PATH}/platform_core/platform/driver/dma_channel/inc"
    "${SDK_PATH}/platform_core/platform/service/dma_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/dma_manager/src"
    "${SDK_PATH}/platform_core/platform/emdrv/common/inc"
    "${SDK_PATH}/platform_core/platform/emlib/inc"
    "${SDK_PATH}/platform_core/platform/common/errno_error_codes/inc"
    "${SDK_PATH}/platform_core/platform/driver/gpio/inc"
    "${SDK_PATH}/platform_core/platform/emdrv/gpiointerrupt/inc"
    "${SDK_PATH}/platform_core/platform/peripheral/inc"
    "${SDK_PATH}/platform_core/platform/driver/i2c/inc"
    "${SDK_PATH}/platform_core/platform/driver/i2c/src"
    "${SDK_PATH}/platform_core/platform/driver/i2cspm/inc"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/src"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/inc/arm"
    "${SDK_PATH}/platform_core/platform/service/iostream/inc"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src"
    "${SDK_PATH}/platform_core/platform/service/sl_main/inc"
    "${SDK_PATH}/platform_core/platform/service/sl_main/src"
    "${SDK_PATH}/platform_core/platform/service/sleeptimer/inc"
    "${SDK_PATH}/platform_core/platform/service/sleeptimer/src"
    "${SDK_PATH}/platform_core/platform/service/udelay/inc"
)

target_compile_definitions(slc PUBLIC
    "DEBUG_EFM=1"
    "EFR32MG26B510F3200IM48=1"
    "SL_CODE_COMPONENT_SYSTEM=system"
    "HARDWARE_BOARD_DEFAULT_RF_BAND_2400=1"
    "HARDWARE_BOARD_SUPPORTS_1_RF_BAND=1"
    "HARDWARE_BOARD_SUPPORTS_RF_BAND_2400=1"
    "HFXO_FREQ=39000000"
    "SL_BOARD_NAME=\"BRD2709A\""
    "SL_BOARD_REV=\"A03\""
    "SL_CODE_COMPONENT_CLOCK_MANAGER=clock_manager"
    "SL_COMPONENT_CATALOG_PRESENT=1"
    "SL_CODE_COMPONENT_DEVICE_PERIPHERAL=device_peripheral"
    "SL_CODE_COMPONENT_DMA_CHANNEL=dma_channel"
    "SL_CODE_COMPONENT_DMA_MANAGER=dma_manager"
    "SL_CODE_COMPONENT_GPIO=gpio"
    "SL_CODE_COMPONENT_HAL_COMMON=hal_common"
    "SL_CODE_COMPONENT_HAL_GPIO=hal_gpio"
    "SL_CODE_COMPONENT_HAL_LDMA=hal_ldma"
    "SL_CODE_COMPONENT_HAL_SYSRTC=hal_sysrtc"
    "SL_CODE_COMPONENT_INTERRUPT_MANAGER=interrupt_manager"
    "CMSIS_NVIC_VIRTUAL=1"
    "CMSIS_NVIC_VIRTUAL_HEADER_FILE=\"cmsis_nvic_virtual.h\""
    "SL_CODE_COMPONENT_MEMORY_MANAGER=memory_manager"
    "SL_CODE_COMPONENT_CORE=core"
    "SL_CODE_COMPONENT_SLEEPTIMER=sleeptimer"
)

target_link_libraries(slc PUBLIC
    "-Wl,--start-group"
    "gcc"
    "c"
    "m"
    "nosys"
    "-Wl,--end-group"
)
target_compile_options(slc PUBLIC
    $<$<COMPILE_LANGUAGE:C>:-mcpu=cortex-m33>
    $<$<COMPILE_LANGUAGE:C>:-mthumb>
    $<$<COMPILE_LANGUAGE:C>:-mfpu=fpv5-sp-d16>
    $<$<COMPILE_LANGUAGE:C>:-mfloat-abi=hard>
    $<$<COMPILE_LANGUAGE:C>:-mcmse>
    $<$<COMPILE_LANGUAGE:C>:-Wall>
    $<$<COMPILE_LANGUAGE:C>:-Wextra>
    $<$<COMPILE_LANGUAGE:C>:-Os>
    $<$<COMPILE_LANGUAGE:C>:-fdata-sections>
    $<$<COMPILE_LANGUAGE:C>:-ffunction-sections>
    $<$<COMPILE_LANGUAGE:C>:-fomit-frame-pointer>
    $<$<COMPILE_LANGUAGE:C>:-g>
    $<$<COMPILE_LANGUAGE:C>:--specs=nano.specs>
    $<$<COMPILE_LANGUAGE:C>:-fno-lto>
    $<$<COMPILE_LANGUAGE:CXX>:-mcpu=cortex-m33>
    $<$<COMPILE_LANGUAGE:CXX>:-mthumb>
    $<$<COMPILE_LANGUAGE:CXX>:-mfpu=fpv5-sp-d16>
    $<$<COMPILE_LANGUAGE:CXX>:-mfloat-abi=hard>
    $<$<COMPILE_LANGUAGE:CXX>:-fno-rtti>
    $<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions>
    $<$<COMPILE_LANGUAGE:CXX>:-mcmse>
    $<$<COMPILE_LANGUAGE:CXX>:-Wall>
    $<$<COMPILE_LANGUAGE:CXX>:-Wextra>
    $<$<COMPILE_LANGUAGE:CXX>:-Os>
    $<$<COMPILE_LANGUAGE:CXX>:-fdata-sections>
    $<$<COMPILE_LANGUAGE:CXX>:-ffunction-sections>
    $<$<COMPILE_LANGUAGE:CXX>:-fomit-frame-pointer>
    $<$<COMPILE_LANGUAGE:CXX>:-g>
    $<$<COMPILE_LANGUAGE:CXX>:--specs=nano.specs>
    $<$<COMPILE_LANGUAGE:CXX>:-fno-lto>
    $<$<COMPILE_LANGUAGE:ASM>:-mcpu=cortex-m33>
    $<$<COMPILE_LANGUAGE:ASM>:-mthumb>
    $<$<COMPILE_LANGUAGE:ASM>:-mfpu=fpv5-sp-d16>
    $<$<COMPILE_LANGUAGE:ASM>:-mfloat-abi=hard>
    "$<$<COMPILE_LANGUAGE:ASM>:SHELL:-x assembler-with-cpp>"
)

set(post_build_command )
set_property(TARGET slc PROPERTY C_STANDARD 17)
set_property(TARGET slc PROPERTY CXX_STANDARD 17)
set_property(TARGET slc PROPERTY CXX_EXTENSIONS OFF)

target_link_options(slc INTERFACE
    -mcpu=cortex-m33
    -mthumb
    -mfpu=fpv5-sp-d16
    -mfloat-abi=hard
    "-T${CMAKE_CURRENT_LIST_DIR}/../autogen/linkerfile.ld"
    --specs=nano.specs
    -Wl,-Map=$<TARGET_FILE_DIR:ppg>/ppg.map
    "SHELL:-Wl,--wrap=_free_r -Wl,--wrap=_malloc_r -Wl,--wrap=_calloc_r -Wl,--wrap=_realloc_r"
    -fno-lto
    -Wl,--gc-sections
)

# BEGIN_SIMPLICITY_STUDIO_METADATA=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=END_SIMPLICITY_STUDIO_METADATA