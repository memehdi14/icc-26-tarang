# TARANG Integration Documentation

Use this directory as the engineering source of truth for the Integration
platform project. The root `readme.md` remains the short project entry point
because Simplicity Studio references it directly.

## System and Validation

- [End-to-end architecture](TARANG_END_TO_END_ARCHITECTURE.md): sensor DAQ,
  DSP, AI, BLE contracts, Raspberry Pi ingestion, limitations, and gates.
- [Testing guide](TESTING_GUIDE.md): model, firmware, live-signal, and energy
  verification status.
- [Flow and NLMS status](FLOW_AND_NLMS_STATUS.md): current synchronized IMU/ECG
  cancellation path and remaining validation work.
- [Power optimization decision](WHY_POWER_OPTIMIZATION_IS_DEFERRED.md): why
  sample-rate and wakeup reductions remain deferred until signal validation.
- [Hackathon demo readiness gate](HACKATHON_DEMO_READINESS.md): full list of
  required BLE, sensor, UI, backend, and validation gates before final judging.

## BLE Incident Records

- [BLE root-cause report](BLE_BLOCKER_ROOT_CAUSE.md): the original GATT host
  configuration failure and recovery.
- [Stale bond-key incident](BLE_STALE_BOND_KEY_ISSUE.md): peer-key mismatch,
  symptoms, and controlled recovery procedure.

## Ownership

- Firmware and validation stream: this `Integration` project.
- Production Raspberry Pi BLE ingestion: `projects/tarang-rpi/dashboard/backend/ble_gateway.py`.
- Volunteer recorder: `log_vcom.py` in the Integration project root.
- Validation plots: `projects/tarang-dsp/integration_validation/plot_tarang.py`.
- Simplicity Studio generated files: `autogen/` and `config/`; manage these
  only through Studio components/configurators.
