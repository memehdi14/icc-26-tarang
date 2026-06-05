# Tarang CI Pipeline and Branch Protection

This document details the Continuous Integration architecture and the branch protection requirements designed to ensure that `main` remains stable and that no broken firmware code is ever merged.

## Architecture & Workflow

1. **Triggering**: The pipeline runs automatically on:
   - Any pull request
   - Any push to `main`
   - Any push to branches matching `feature/*`

2. **Static Analysis (Cppcheck)**: 
   Before any firmware compilation occurs, the codebase undergoes static analysis using `cppcheck`. The CI pipeline will automatically fail if it detects:
   - Syntax errors
   - Memory leaks or memory allocation issues
   - Unused variables
   - Null pointer dereferencing issues
   
3. **Project Generation**:
   The workflow dynamically installs the **Silicon Labs SLC-CLI**. Instead of relying on pushed `config/` folders (which are now git-ignored), the pipeline runs `slc generate` against `Tarang_Core_Pipeline.slcp` to re-create the build files.

4. **Firmware Compilation**:
   The ARM GNU Toolchain runs `make` against the generated Makefile. The pipeline will strictly fail on:
   - Any compilation errors
   - Linker errors
   - Missing include errors

5. **Artifact Storage**:
   If the build is successful (or even if it fails and logs are generated), the following artifacts are uploaded to GitHub Actions for 90 days:
   - `firmware.bin`
   - `firmware.hex`
   - `firmware.elf`
   - `build.log`

## Developer Workflow

Developers **must** follow this workflow to merge code into `main`:

1. Check out a feature branch from main: `git checkout -b feature/my-new-feature`
2. Commit code. Note: generated `config/` and build directories are automatically ignored by `.gitignore`. Do not forcefully add them.
3. Push your branch to GitHub.
4. Open a Pull Request targeting `main`.
5. Wait for the `Firmware Build Pipeline` checks to pass. If they fail, fix the errors locally and push again.
6. Request a code review from at least one teammate.

## GitHub Branch Protection Setup

To enforce this pipeline, an administrator must navigate to **Settings > Branches** in GitHub and configure the following protection rules for the `main` branch:

- **Require a pull request before merging**: Check this box.
  - **Require approvals**: Set to `1`.
- **Require status checks to pass before merging**: Check this box.
  - Require branches to be up to date before merging.
  - Add `Firmware Compile Check` and `Cppcheck Static Analysis` as required status checks.
- **Do not allow bypassing the above settings**: Check this box.
- **Restrict who can push to matching branches**: Prevent direct pushes (only allow PR merges).
- **Allow force pushes**: Do NOT check (prevent force pushes).
