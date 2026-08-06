# Tarang Firmware

> [!WARNING]
> **READ BEFORE TOUCHING ANY FILES**
> If you are working on this project, you **MUST** read the [Tarang Firmware Build System Survival Guide](SIMPLICITY_STUDIO_AI_GUIDE.md) first. Simplicity Studio will silently overwrite files and destroy your build if you do not follow the strict source ownership and regeneration rules outlined in the guide.

This project contains the embedded firmware for Tarang, Team Ocelleon's IoT Challenge 2026 wearable pipeline.

## Target

- Board family: Silicon Labs EFR32MG26
- Core: Cortex-M33
- SDK: Silicon Labs Simplicity SDK
- Project file: [Tarang_Core_Pipeline.slcp](Tarang_Core_Pipeline.slcp)

## Main files

- [app.c](app.c) contains the core application logic.
- [tarang_pipeline.h](tarang_pipeline.h) defines the physiological frame pipeline types and handoffs.
- [tarang_model.h](tarang_model.h) contains the embedded model interface/data used by the firmware.
- [config/](config/) contains Silicon Labs project configuration.

## Build

1. Open `Tarang_Core_Pipeline.slcp` in Simplicity Studio.
2. Install or select the matching Simplicity SDK locally.
3. Generate project files if Simplicity Studio prompts for regeneration.
4. Build the project from Simplicity Studio.
5. Flash the target board from Simplicity Studio.

The local SDK folder, project checksum files, and build outputs are ignored by Git.

## Notes

Keep generated SDK content and build products out of commits. Commit only source files, project configuration, and documentation needed for another developer to rebuild the project.

## Troubleshooting & Build Rules

If you are encountering linker errors (`cannot move location counter backwards`), multiple definitions, or strange CMake behavior after regenerating the project, **STOP** and read the [Tarang Firmware Build System Survival Guide](SIMPLICITY_STUDIO_AI_GUIDE.md). It contains critical rules for managing sources and the SDK to prevent project corruption.
