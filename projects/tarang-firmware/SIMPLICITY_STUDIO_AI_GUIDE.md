# Tarang Firmware Build System Survival Guide

### For Humans, AI Agents, Sleep-Deprived Embedded Engineers, and Future Victims

---

# BASELINE RULES (READ FIRST)

## Rule #0: Assume Simplicity Studio Knows More Than You

Before changing anything, assume:

* The SDK is correct.
* The Silicon Labs components are correct.
* The generated files are correct.
* The toolchain is correct.

Until proven otherwise.

Most issues come from project configuration, not Silicon Labs.

---

## Rule #1: NEVER TOUCH SDK FILES

Do NOT modify anything inside:

```txt
.silabs/
Users/<user>/.silabs/
simplicity_sdk/
wiseconnect_sdk/
platform/
security/
rail_library/
bluetooth_stack/
```

If you modify SDK files:

* Updates will overwrite your changes.
* Other developers will not have your changes.
* Regeneration may break.
* Future debugging becomes impossible.

SDK code is read-only.

Treat it as vendor code.

---

## Rule #2: NEVER TOUCH GENERATED FILES

Do NOT modify:

```txt
autogen/
cmake_gcc/build/
```

Examples:

```txt
autogen/linkerfile.ld
autogen/gatt_db.c
autogen/gatt_db.h
autogen/sl_bluetooth.c
autogen/sl_event_handler.c
autogen/sl_power_manager_handler.c
```

Generated files are evidence.

Generated files are NOT source code.

If a generated file is wrong:

Fix what generated it.

Never patch the generated output.

---

## Rule #3: NEVER FIX A PROBLEM INSIDE A BUILD FOLDER

Do not edit:

```txt
cmake_gcc/build/
```

Ever.

Delete it.

Rebuild it.

Move on.

---

# SOURCE OWNERSHIP RULES

## Rule #4: One File = One Owner

Every source file should be registered exactly once.

Good:

```txt
tarang_nlms.c
    ↓
SLCP
```

Bad:

```txt
tarang_nlms.c
    ↓
SLCP

tarang_nlms.c
    ↓
Custom CMake
```

Duplicate ownership causes duplicate compilation.

---

## Rule #5: Do Not Manually Add Sources Already Managed By SLCP

If a file exists under:

```yaml
source:
```

inside:

```txt
Tarang_Core_Pipeline.slcp
```

then DO NOT manually add it to:

```cmake
target_sources(...)
```

or

```cmake
CMakeLists.txt
```

or

```cmake
Tarang_Core_Pipeline_project.cmake
```

SLCP already owns it.

---

## Rule #6: Verify Ownership Before Editing

Search first.

```powershell
Get-ChildItem -Recurse -File | Select-String "filename.c"
```

Know who owns a file before modifying build configuration.

---

# REGENERATION RULES

## Rule #7: Force Generate Is The Truth Test

A fix is not real until it survives:

```txt
Force Generate
↓
Clean Build
↓
Build
↓
Restart IDE
↓
Build Again
```

If it breaks after Force Generate:

You fixed the wrong file.

---

## Rule #8: Generated Files Are Disposable

If your fix disappears after regeneration:

You edited the wrong file.

Find the source of truth.

---

## Rule #9: Never Edit .slcp While Studio Has It Open

Simplicity Studio caches project configuration.

If Studio has the file open:

```txt
Your Manual Edit
↓
Force Generate
↓
Studio Cache Wins
↓
Edit Lost
```

Always modify project settings through Studio when possible.

---

# DEBUGGING RULES

## Rule #10: Read The First Error

Not the last error.

Not the biggest error.

The first meaningful error.

Everything after that may be collateral damage.

---

## Rule #11: Clean Before Investigating

Before spending more than 10 minutes debugging:

```powershell
Remove-Item -Recurse -Force .\cmake_gcc\build
```

Then:

```txt
Force Generate
↓
Rebuild
```

---

## Rule #12: Build Logs Are Evidence

Build logs tell you exactly what happened.

Example:

Bad:

```txt
I think tarang_nlms.c compiled once.
```

Good:

```txt
CMakeFiles/slc.dir/.../tarang_nlms.c.obj
CMakeFiles/Tarang_Core_Pipeline.dir/.../tarang_nlms.c.obj
```

Evidence beats assumptions.

---

## Rule #13: Don't Blame GCC First

Before blaming:

* GCC
* CMake
* Linker
* Silicon Labs
* Windows
* The Universe

Check:

* Duplicate files
* Wrong device
* Missing components
* Bad configuration
* Regeneration issues

First.

---

# MEMORY & LINKER RULES

## Rule #14: Verify Target Device First

Before debugging RAM or Flash:

Verify:

```txt
Configured MCU
==
Actual MCU
```

Wrong device selection causes:

* RAM issues
* Flash issues
* Peripheral issues
* Linker issues

---

## Rule #15: Linker Errors Usually Mean Configuration Errors

If you see:

```txt
cannot move location counter backwards
```

Think:

```txt
Memory configuration
Generated linker script
Device mismatch
Regeneration issue
```

Before:

```txt
Firmware bug
```

---

## Rule #16: Multiple Definition Errors Usually Mean Duplicate Ownership

If you see:

```txt
multiple definition of ...
```

Think:

```txt
Source file compiled twice
Duplicate registration
Duplicate ownership
```

Before:

```txt
Compiler bug
```

---

# AI AGENT RULES

## Rule #17: AI Must Search Before Changing

Before changing anything:

1. Search project.
2. Identify ownership.
3. Identify source of truth.
4. Check regeneration impact.
5. Make smallest possible change.

---

## Rule #18: AI Must Not Patch Generated Outputs

AI is forbidden from permanently modifying:

```txt
autogen/*
generated linker scripts
generated gatt files
generated cmake
build outputs
SDK files
```

Find the source configuration instead.

---

## Rule #19: AI Must Explain Root Cause

A successful build is not enough.

Every fix must answer:

```txt
What broke?
Why did it break?
Why does this fix work?
Why will it survive regeneration?
```

---

# TARANG PROJECT LESSON LEARNED

## The tarang_nlms.c Incident

Root Cause:

```txt
tarang_nlms.c
```

was registered twice:

1. SLCP source list
2. Tarang_Core_Pipeline_project.cmake

Result:

```txt
Compiled Twice
↓
Multiple Definitions
↓
Linker Failure
```

Permanent Fix:

```txt
One File
One Owner
```

SLCP owns the file.

Custom CMake does not.

---

# GOLDEN RULE

If Force Generate breaks your fix, YOU FIXED THE WRONG FILE.
