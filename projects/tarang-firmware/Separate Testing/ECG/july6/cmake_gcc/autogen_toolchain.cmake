####################################################################
# Automatically-generated file. Do not edit!                       #
####################################################################

# OS Specific auto-generated file with default tools installs. This
# file must be re-generated when switching systems and should not
# be tracked in source control. 

# Use the SLT tooling to find the install paths so the tools are
# found across multiple machines. This requires placing the 'slt'
# tool on PATH
execute_process(COMMAND slt where gcc-arm-none-eabi/14.2.rel1
                OUTPUT_VARIABLE "TOOLCHAIN_SLT_PATH"
                OUTPUT_STRIP_TRAILING_WHITESPACE)

execute_process(COMMAND slt where commander
                OUTPUT_VARIABLE "COMMANDER_SLT_PATH"
                OUTPUT_STRIP_TRAILING_WHITESPACE)

execute_process(COMMAND slt where ninja
                OUTPUT_VARIABLE "NINJA_SLT_PATH"
                OUTPUT_STRIP_TRAILING_WHITESPACE)


if (TOOLCHAIN_SLT_PATH)
  set(DEFAULT_TOOLCHAIN_DIR "${TOOLCHAIN_SLT_PATH}/bin/")
else()
  set(DEFAULT_TOOLCHAIN_DIR "${USER_DIR}/.silabs/slt/installs/conan/p/gcc-a92619eca33962/p/bin/")
endif ()

if (COMMANDER_SLT_PATH)
  if (WIN32)
    set(DEFAULT_POST_BUILD_EXE "${COMMANDER_SLT_PATH}/commander.exe")
  elseif (APPLE)
    set(DEFAULT_POST_BUILD_EXE "${COMMANDER_SLT_PATH}/Contents/MacOS/commander")
  else()
    set(DEFAULT_POST_BUILD_EXE "${COMMANDER_SLT_PATH}/commander")
  endif ()
else()
  set(DEFAULT_POST_BUILD_EXE "${USER_DIR}/.silabs/slt/installs/archive/Commander.app/Contents/MacOS/commander")
endif ()

if (NINJA_SLT_PATH)
  set(DEFAULT_NINJA_RUNTIME_PATH "${NINJA_SLT_PATH}/ninja")
else()
  set(DEFAULT_NINJA_RUNTIME_PATH "${USER_DIR}/.silabs/slt/installs/conan/p/ninja48deaaf744f20/p/ninja")
endif ()
