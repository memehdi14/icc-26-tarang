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
    "${SDK_PATH}/platform_core/platform/emlib/src/em_burtc.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_cmu.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_emu.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_eusart.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_gpio.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_iadc.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_ldma.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_letimer.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_msc.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_prs.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_system.c"
    "${SDK_PATH}/platform_core/platform/emlib/src/em_timer.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_eusart.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_gpio.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_ldma.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_prs.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_syscfg.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_sysrtc.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_sysrtc_subsystem.c"
    "${SDK_PATH}/platform_core/platform/peripheral/src/sl_hal_system.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager_hal_s2.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager_init.c"
    "${SDK_PATH}/platform_core/platform/service/clock_manager/src/sl_clock_manager_init_hal_s2.c"
    "${SDK_PATH}/platform_core/platform/service/device_init/src/sl_device_init_dcdc_s2.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/clocks/sl_device_clock_efr32xg26.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/devices/sl_device_peripheral_hal_efr32xg26.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/dma/sl_device_dma_s2.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_clock.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_dma.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_gpio.c"
    "${SDK_PATH}/platform_core/platform/service/device_manager/src/sl_device_peripheral.c"
    "${SDK_PATH}/platform_core/platform/service/dma_manager/src/sl_dma_manager.c"
    "${SDK_PATH}/platform_core/platform/service/dma_manager/src/sl_dma_manager_hal_ldma.c"
    "${SDK_PATH}/platform_core/platform/service/hfxo_manager/src/sl_hfxo_manager.c"
    "${SDK_PATH}/platform_core/platform/service/hfxo_manager/src/sl_hfxo_manager_hal_s2.c"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/src/sl_interrupt_manager_cortexm.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_debug.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_dmadrv.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_eusart.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_swo_itm_8.c"
    "${SDK_PATH}/platform_core/platform/service/iostream/src/sl_iostream_uart.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_dynamic_reservation.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_pool.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_pool_common.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_region.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sl_memory_manager_retarget.c"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src/sli_memory_manager_common.c"
    "${SDK_PATH}/platform_core/platform/service/power_manager/src/common/sl_power_manager_common.c"
    "${SDK_PATH}/platform_core/platform/service/power_manager/src/common/sl_power_manager_em4.c"
    "${SDK_PATH}/platform_core/platform/service/power_manager/src/sleep_loop/sl_power_manager.c"
    "${SDK_PATH}/platform_core/platform/service/power_manager/src/sleep_loop/sl_power_manager_debug.c"
    "${SDK_PATH}/platform_core/platform/service/power_manager/src/sleep_loop/sl_power_manager_hal_s2.c"
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
    "../autogen/sl_iostream_handles.c"
    "../autogen/sl_iostream_init_eusart_instances.c"
    "../autogen/sl_power_manager_handler.c"
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
    "${SDK_PATH}/platform_core/platform/emlib/inc"
    "${SDK_PATH}/platform_core/platform/common/errno_error_codes/inc"
    "${SDK_PATH}/platform_core/platform/driver/gpio/inc"
    "${SDK_PATH}/platform_core/platform/peripheral/inc"
    "${SDK_PATH}/platform_core/platform/service/hfxo_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/hfxo_manager/src"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/src"
    "${SDK_PATH}/platform_core/platform/service/interrupt_manager/inc/arm"
    "${SDK_PATH}/platform_core/platform/service/iostream/inc"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/memory_manager/src"
    "${SDK_PATH}/platform_core/platform/service/power_manager/inc"
    "${SDK_PATH}/platform_core/platform/service/power_manager/src/common"
    "${SDK_PATH}/platform_core/platform/service/power_manager/src/sleep_loop"
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
    "SL_CODE_COMPONENT_POWER_MANAGER=power_manager"
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
    -Wl,-Map=$<TARGET_FILE_DIR:july6>/july6.map
    "SHELL:-Wl,--wrap=_free_r -Wl,--wrap=_malloc_r -Wl,--wrap=_calloc_r -Wl,--wrap=_realloc_r"
    -fno-lto
    -Wl,--gc-sections
)

# BEGIN_SIMPLICITY_STUDIO_METADATA=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END_SIMPLICITY_STUDIO_METADATA