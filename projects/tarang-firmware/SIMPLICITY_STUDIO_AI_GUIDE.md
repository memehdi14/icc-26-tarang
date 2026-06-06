# Simplicity Studio & CMake AI Guide

This guide is for AI assistants and developers working on this Silicon Labs project. It documents critical rules to avoid the build system destroying itself during `slc generate`.

## 1. Source File Ownership (The "Multiple Definition" Error)

**Rule:** NEVER manually add source files (e.g., `tarang_nlms.c`) to `cmake_gcc/*_project.cmake` or `CMakeLists.txt` if they are already tracked by the Simplicity Studio Project Explorer or the `.slcp` file.

**Why:** 
When a file is listed under the `source:` block of the `.slcp` file, the `slc` generator automatically compiles it into the `slc.dir` core library. If an AI or developer *also* manually adds that file to the custom CMake user file (`Tarang_Core_Pipeline_project.cmake`), the top-level CMake target will compile it a second time.

**Symptoms:**
Linker crashes with `multiple definition of <function_name>`.

**The Fix:**
Ensure custom user `.cmake` files do not include sources managed by the SLCP. The file should be empty or only contain truly external, non-SLCP managed files.

---

## 2. `.slcp` Overwrites (The "Moving Backwards" Linker Error)

**Rule:** NEVER manually edit the `.slcp` file via a text editor while the Simplicity Studio GUI has the file open.

**Why:**
Simplicity Studio caches the state of the `.slcp` file in its UI. If you add a manual fix to the `.slcp` file on disk, and then the user clicks **"Force Generate"** in the Studio GUI, Studio will **overwrite the file on disk with its cached state**, instantly wiping out your manual fixes before generating.

**Symptoms:**
- Missing `memory_ram_size` and `memory_flash_size` values (defaulting to 0).
- The linker script (`autogen/linkerfile.ld`) thinks the chip has 0 bytes of memory.
- Linker crashes with `cannot move location counter backwards (from X to Y)` because it attempts to subtract sizes from a 0-byte boundary.

**The Fix:**
If memory configurations are lost during regeneration, they must be fixed via the **Memory Configuration** tab in the Simplicity Studio UI, or the `.slcp` file must be edited with the Studio GUI completely closed.
