# Tarang BLE Connection and Bonding Root Cause Report

**Project:** Tarang Integration firmware  
**Target:** EFR32MG26B510F3200IM48  
**Project type:** Silicon Labs Platform project  
**SDK:** Simplicity SDK 2026.6.1  
**Investigation date:** 2026-08-19  
**Status:** GATT discovery fixed; bonding-enabled firmware built and awaiting final phone/Raspberry Pi validation

## 1. Executive Summary

The final bonding blocker was not the antenna, signal strength, Raspberry Pi, phone, BLE address, or custom GATT UUIDs.

The firmware had a valid BLE controller and could advertise and accept a connection, but its generated build linked placeholder security libraries instead of the real Security Manager implementation. At the same time, the application explicitly told the stack not to accept new bonds:

```c
sl_bt_sm_set_bondable_mode(0);
```

Therefore, ordinary unpaired BLE connections could work, but every pairing or bonding attempt was guaranteed to fail.

There were three layers to the bonding failure:

1. The Platform project did not originally include the Bluetooth Security Manager component.
2. The generated binary linked security and bonding **stub libraries**.
3. The application explicitly set bondable mode to `0` and ignored the return status of the security calls.

After the Security Manager component was added in Simplicity Studio, Studio generated the correct component graph. However, the existing CMake/Ninja build directory was briefly stale and still referenced the old stub libraries. A fresh CMake configure was required before building the final image.

The earlier GATT discovery problem and the later bonding problem were related to the same integration project, but they were not the same failure:

- **GATT discovery failure:** the phone connected at the link layer but did not complete a reliable application/GATT session.
- **Bonding failure:** after GATT discovery was fixed, `CREATE BOND` still failed because security was disabled and backed by stubs.

The screenshots showing Generic Attribute, Generic Access, Device Information, all three custom Tarang services, and their CCCDs prove that the connection and GATT-discovery stage is now working.

## 2. User-Visible Symptoms

### 2.1 Raspberry Pi symptoms

BlueZ initially reported:

```text
Attempting to pair with 64:02:8F:64:26:14
[CHG] Device 64:02:8F:64:26:14 Connected: yes
Failed to pair: org.bluez.Error.ConnectionAttemptFailed
```

Direct connection attempts reported:

```text
Attempting to connect to 64:02:8F:64:26:14
[CHG] Device 64:02:8F:64:26:14 Connected: yes
Failed to connect: org.bluez.Error.Failed le-connection-abort-by-local
[CHG] Device 64:02:8F:64:26:14 Connected: no
```

The temporary `Connected: yes` line was important. It showed that the radio link could be established. The failure happened after initial connection establishment, during host/GATT/security processing.

### 2.2 Phone symptoms before the GATT fix

The phone reported a successful connection and continued reading RSSI:

```text
Connection state changed: Connected
onReadRemoteRssi, status: success
```

However, service loading did not finish and the application later exited with a GATT host configuration error.

This meant the physical BLE connection was alive, but the higher-level client workflow was not completing correctly.

### 2.3 Phone symptoms after the GATT fix

The phone successfully displayed:

- Generic Attribute service, UUID `0x1801`
- Service Changed, Database Hash, and Client Supported Features
- Generic Access service, UUID `0x1800`
- Device Name and Appearance
- Device Information service, UUID `0x180A`
- Tarang custom services beginning with `544E...`, `655F...`, and `7660...`
- Readable heart-rate and SpO2 values
- Client Characteristic Configuration descriptors, UUID `0x2902`
- Notify and indicate capabilities

This is decisive evidence that:

1. Advertising works.
2. Connection establishment works.
3. ATT/GATT requests and responses work.
4. The GATT database is discoverable.
5. Custom services and characteristics are registered.
6. The phone can read custom characteristic values.

The screen still showed `NOT BONDED`. Pressing `CREATE BOND` immediately caused the session to exit. That isolated the remaining failure to the Security Manager and bonding path.

## 3. BLE Layers and Where the Failure Occurred

BLE is not a single operation. The observed workflow crosses several layers:

1. **Advertising:** EFR32 broadcasts `TARANG-2614`.
2. **Scanning:** phone or Raspberry Pi discovers the advertisement.
3. **Link-layer connection:** central creates a BLE connection.
4. **ATT/GATT discovery:** central enumerates services, characteristics, and descriptors.
5. **CCCD subscription:** central enables notifications or indications.
6. **SMP pairing:** devices negotiate encryption keys.
7. **Bonding:** negotiated keys are stored for later reconnects.
8. **Application telemetry:** Tarang sends vitals and clinical events.

The project progressed through these failure boundaries:

| Stage | Earlier state | Current state |
|---|---|---|
| Advertising | Working | Working |
| Scanning | Working | Working |
| Link connection | Intermittent/aborted | Working |
| GATT discovery | Timed out on phone | Working |
| Reads and CCCDs | Not usable | Visible and usable |
| Pairing/bonding | Guaranteed to fail | Enabled in latest build |
| Persistent reconnect | Not possible | Ready for hardware validation |

## 4. Confirmed Root Cause 1: Security Manager Was Missing

The original Platform project component graph did not contain:

```text
bluetooth_feature_sm
```

The application still called Security Manager APIs:

```c
sl_bt_sm_configure(0, sl_bt_sm_io_capability_noinputnooutput);
sl_bt_sm_set_bondable_mode(0);
```

An API declaration being available does not prove that its implementation is linked. Silicon Labs Platform projects can compile against API headers while linking feature stubs for components that were not selected.

That is exactly what happened here.

### 4.1 Libraries linked before the fix

The generated link graph contained:

```text
libbondingdb_stub.a
libble_host_crypto_stub.a
libble_host_local_privacy_stub.a
libble_host_rpa_resolution_stub.a
```

These libraries satisfy linker symbols but do not provide the complete operational bonding implementation.

The result was deceptive:

- The code compiled.
- The firmware booted.
- Advertising worked.
- Connections could begin.
- Security API calls existed.
- Pairing could not complete.

This is the most important technical lesson from the failure: **successful compilation did not mean the requested Bluetooth feature existed in the binary.**

### 4.2 Components selected through Simplicity Studio

The manually selected component was:

```text
Bluetooth > Stack > Security Manager
Component ID: bluetooth_feature_sm
```

Simplicity Studio then auto-selected the required dependency graph:

```text
bluetooth_crypto
bluetooth_crypto_lib_psa
bluetooth_feature_builtin_bonding_database
bluetooth_feature_local_privacy
bluetooth_feature_rpa_resolution
nvm3_default
nvm3_default_config
nvm3_default_flash_backend
nvm3_source
psa_its
psa_its_source
```

No Central Role or Scanner component is required on the EFR32 for this use case. The EFR32 is the peripheral/GATT server. The phone or Raspberry Pi is the central/GATT client.

### 4.3 Libraries linked after the fix

After Studio generation and a fresh CMake configure, the link graph contained:

```text
libble_host_crypto.a
libble_host_crypto_lib_psa.a
libbondingdb.a
libble_host_local_privacy.a
libble_host_rpa_resolution.a
```

Verification counts after reconfiguration were:

```text
libble_host_crypto_stub.a=0
libbondingdb_stub.a=0
libble_host_local_privacy_stub.a=0
libble_host_rpa_resolution_stub.a=0
```

This is the definitive generated-build proof that the real security implementation is now linked.

## 5. Confirmed Root Cause 2: Bonding Was Explicitly Disabled

The old boot handler contained:

```c
sl_bt_sm_configure(0, sl_bt_sm_io_capability_noinputnooutput);
sl_bt_sm_set_bondable_mode(0);
```

For Silicon Labs Bluetooth APIs:

- `0` means new bondings are not accepted.
- `1` means new bondings are allowed.

Therefore, pressing `CREATE BOND` on the phone asked the peripheral to start SMP pairing while the peripheral was explicitly configured to reject new bonding.

The old code also did not check or print the return values from these calls. If the Security Manager stub returned an error, the firmware silently continued advertising. This made the problem appear to be an Android, BlueZ, or RF issue.

The new implementation checks every relevant status and enables bonding only when the Security Manager is present:

```c
#ifndef TARANG_BLE_ENABLE_BONDING
#define TARANG_BLE_ENABLE_BONDING 1
#endif

#if defined(SL_CATALOG_BLUETOOTH_FEATURE_SM_PRESENT)
sc = sl_bt_sm_configure(0, sl_bt_sm_io_capability_noinputnooutput);
sc = sl_bt_sm_store_bonding_configuration(8, 2);
sc = sl_bt_sm_set_bondable_mode(1);
#endif
```

The configuration means:

- Pairing method: Just Works
- Device I/O capability: no input, no output
- Maximum stored bonds: 8
- Full database policy: replace the least recently used bond
- Persistent storage: built-in bonding database using NVM3

## 6. Confirmed Root Cause 3: Generated Files and Build Graph Were Out of Sync

After components were added, `Integration.slcp`, the generated component catalog, and `Integration.cmake` were updated correctly.

However, the existing Ninja build graph had been created just before the final generated CMake file changed:

```text
impl-base.ninja timestamp: 03:23:51
Integration.cmake timestamp: 03:24:05
```

At that point:

- `Integration.cmake` requested the real security libraries.
- `impl-base.ninja` still linked the old stub libraries.

Running only a build against the stale Ninja graph could therefore produce another non-bonding image even though Simplicity Studio showed the correct installed components.

The required sequence was:

```powershell
cd C:\MMDPublic\Hackathons\TeamOcelleon\projects\tarang-firmware\Integration\cmake_gcc
cmake --preset project
cmake --build --preset default_config
```

The first command regenerates the native build graph from the latest Studio-generated `Integration.cmake`. The second command compiles and links the firmware.

The final incremental verification returned:

```text
ninja: no work to do.
```

This confirmed a complete and internally consistent build.

## 7. Why the Working Empty Project Was Misleading

The `bt_soc_empty` project was extremely useful, but it proved only part of the system.

It proved that the following baseline was healthy:

- EFR32 radio hardware
- Board target and device selection
- Silicon Labs SDK installation
- BLE controller libraries
- Advertising
- Basic phone connectivity
- Clock and platform initialization

It did not prove that the Tarang Integration binary had the same generated component graph.

The important distinction is:

- Source code can look nearly identical.
- SDK versions can be identical.
- Board and device settings can be identical.
- Generated Platform component selections can still produce different linked libraries.

The reference project's own source also used `sl_bt_sm_set_bondable_mode(0)`. Therefore, its successful normal connection was not evidence that bond creation was enabled. It was evidence that unpaired BLE connectivity worked.

The correct migration strategy was consequently not to convert Tarang into a Bluetooth SoC project. Tarang remains a Platform project. The correct fix was to reproduce the necessary BLE feature components and runtime behavior inside the Platform project.

## 8. Earlier GATT Discovery Failure

The earlier phone timeout was a separate stage from bonding. Several integration risks were corrected together, so it would be inaccurate to claim that one single change alone fixed it without a controlled firmware-by-firmware hardware bisect.

The following changes collectively stabilized the GATT path.

### 8.1 Explicit application event forwarding

The strong Silicon Labs event entry point now lives in `app.c`:

```c
void sl_bt_on_event(sl_bt_msg_t *evt)
{
  tarang_ble_on_event(evt);
}
```

The BLE implementation uses its own handler:

```c
void tarang_ble_on_event(sl_bt_msg_t *evt)
```

This makes ownership explicit and avoids ambiguity with the weak default event callback generated by the Platform project.

### 8.2 Subscription-aware notifications

The old implementation attempted periodic notifications whenever a connection existed, including before the phone had written the characteristic's CCCD.

The new implementation:

1. Tracks `sl_bt_evt_gatt_server_characteristic_status_id`.
2. Records which characteristics are subscribed.
3. Updates readable GATT values independently.
4. Sends notifications only when the corresponding CCCD is enabled.

This prevents application traffic from racing the client's service discovery and subscription process.

### 8.3 Readable vitals

Heart rate and SpO2 now support both read and notify behavior. Their values are written into the GATT database before optional notifications are sent.

The phone screenshots confirmed that the values could be read successfully.

### 8.4 BLE processing no longer depends on sensor sample counters

Diagnostics and application scheduling now use a millisecond timebase. BLE telemetry processing remains active even when ECG, PPG, and IMU are disabled or physically absent.

This matters because the test hardware logs showed all sensors missing or disabled. BLE must remain independently operational in that state.

### 8.5 Connection and failure logging

The firmware now logs:

- Advertising setup failures
- Device-name write failures
- Connection parameter request status
- Connection close reason
- CCCD changes
- Notification failures
- Bond success
- Bond failure reason

This turns previously silent failures into diagnosable events.

## 9. Why BlueZ Produced Confusing Errors

`bluetoothctl pair` performs more than one operation:

1. Locate the device.
2. Establish a BLE connection.
3. Start SMP pairing.
4. Exchange keys.
5. Store the bond.

When step 2 succeeded but the peripheral could not perform steps 3 through 5, BlueZ reported a general connection-attempt failure. This made the failure look like the radio could not connect, even though the temporary `Connected: yes` event proved otherwise.

The old gateway also removed the device from BlueZ immediately after a failed pairing attempt:

```text
bluetoothctl remove 64:02:8F:64:26:14
```

The next retry then failed with:

```text
Device 64:02:8F:64:26:14 not available
```

That second error was self-inflicted: removing the BlueZ device object meant it had to be rediscovered before another operation by address could work.

The retry loop therefore amplified the firmware issue:

1. Pairing failed because firmware bonding was unavailable.
2. Gateway deleted the BlueZ device.
3. Immediate retry could not find the deleted device object.
4. Backoff increased while the actual firmware root cause remained unchanged.

The current gateway resolves the device through active scanning and does not repeatedly force pairing and cache deletion.

## 10. Fixes Applied

### 10.1 Simplicity Studio managed changes

The following were generated through Studio, not manually edited:

- Security Manager component selection
- Crypto dependencies
- Built-in bonding database
- Local privacy and RPA resolution
- NVM3 default instance
- PSA Internal Trusted Storage dependencies
- Component catalog
- CMake source/library graph

The rule remains:

> Do not manually edit `autogen/` or generated configuration files. Change components through Simplicity Studio and regenerate the project.

### 10.2 Handwritten source changes

The BLE application source now:

- Enables bonding with `TARANG_BLE_ENABLE_BONDING=1`.
- Configures no-input/no-output Just Works pairing.
- Stores up to eight persistent bonds.
- Replaces the least recently used bond when full.
- Logs successful bonds.
- Logs exact failure reason codes.
- Auto-confirms a bonding request if a confirmation event is emitted.
- Sends notifications only after subscription.
- Preserves direct unpaired connection support before bonding.

### 10.3 Raspberry Pi gateway changes

The gateway now:

- Resolves the configured address through BLE scanning.
- Avoids destructive remove-and-immediate-retry behavior.
- Reports GATT subscription success or failure per characteristic.
- Fails clearly if no required Mode A notification subscription succeeds.

## 11. Current Firmware Image

The latest bonding-enabled image is:

```text
C:\MMDPublic\Hackathons\TeamOcelleon\projects\tarang-firmware\Integration\cmake_gcc\build\base\Integration.hex
```

Build output was generated successfully with the real security libraries.

Do not test bonding with an older `.hex`; older images may still contain the stub libraries and `bondable_mode(0)` behavior.

## 12. Phone Validation Procedure

### 12.1 Clean test preparation

1. Flash the latest `Integration.hex`.
2. Reset or power-cycle the EFR32.
3. Disconnect any existing phone session.
4. If Android lists TARANG as previously paired, forget it once.
5. Do not repeatedly clear it after every attempt.
6. Open Silicon Labs Simplicity Connect.
7. Scan for `TARANG-2614`.
8. Connect and wait for complete service discovery.

### 12.2 Bond creation

Press `CREATE BOND` once.

Expected firmware logs include successful Security Manager configuration followed by:

```text
[BLE][SM] Bonded: conn=0x00 handle=0x00 security=1
```

The exact connection and bonding handles may differ.

Expected phone state:

```text
BONDED
```

### 12.3 Persistence test

1. Disconnect from the phone.
2. Reset the EFR32.
3. Reconnect from the same phone.
4. Verify that the bond is reused.
5. Verify that service discovery and reads still work.
6. Subscribe to heart rate and SpO2.
7. Verify that notifications arrive.

This confirms both SMP success and NVM3 persistence.

## 13. Raspberry Pi Validation Procedure

Use a single manual pairing attempt before running the automated gateway:

```bash
bluetoothctl
power on
agent NoInputNoOutput
default-agent
scan on
pair 64:02:8F:64:26:14
trust 64:02:8F:64:26:14
info 64:02:8F:64:26:14
```

Expected `info` state after successful pairing:

```text
Paired: yes
Bonded: yes
Trusted: yes
```

Then exit `bluetoothctl`, start the API backend first, and start the gateway second.

Do not run multiple BLE clients simultaneously. Disconnect the phone before testing the Raspberry Pi because the firmware currently uses one application connection handle.

## 14. Expected Diagnostic Logs

### Successful boot and bonding

```text
[BLE] create advertising set: OK
[BLE] configure security manager: OK
[BLE] configure persistent bonding store: OK
[BLE] enable bonding: OK
[BLE] Connectable advertising started
[BLE] Connection opened
[BLE][SM] Bonded: conn=0x00 handle=0x00 security=1
```

### Bonding failure

```text
[BLE][SM] Bonding failed: conn=0x00 reason=0xXXXX
```

### Connection closure

```text
[BLE] Connection closed: reason=0xXXXX. Restarting advertising...
```

If bonding still fails, the two hexadecimal reason values are the most important evidence. They should be captured before changing any more project components.

## 15. Fast Failure Decision Tree

### Device does not advertise

Check:

- Correct image was flashed.
- Boot reached `TARANG BLE BOOT OK`.
- Advertising creation and start returned success.
- No assert or reset occurred after boot.

### Device connects but services do not appear

Check:

- Strong `sl_bt_on_event` forwarding is present.
- Generated GATT database matches `gatt_db.h` handles.
- Client is not using a stale Android GATT cache.
- Application is not sending notification traffic before CCCD subscription.
- Connection close reason from UART.

### Services appear but CREATE BOND exits

Check:

- Latest bonding-enabled image is flashed.
- Boot log says `enable bonding: OK`.
- Link graph does not contain `libbondingdb_stub.a`.
- Link graph does not contain `libble_host_crypto_stub.a`.
- UART contains a `Bonding failed` reason.
- Phone does not have a conflicting stale bond.

### Bond succeeds but is lost after reset

Check:

- Built-in bonding database is selected.
- NVM3 default instance is selected.
- NVM3 storage has sufficient space.
- Flashing procedure is not erasing NVM3 on every update.
- Phone and device both retain matching keys.

### Pi says device is not available

Check:

- Scan is active long enough to rediscover the device.
- A previous script did not remove the BlueZ device object.
- Phone is disconnected.
- Configured address matches the current identity address.

## 16. Regression Prevention

### 16.1 Verify linked libraries, not only component names

Every release build should verify that bonding-enabled firmware contains the real libraries and no security stubs.

Required:

```text
libble_host_crypto.a
libbondingdb.a
libble_host_local_privacy.a
libble_host_rpa_resolution.a
```

Forbidden in a bonding-enabled release:

```text
libble_host_crypto_stub.a
libbondingdb_stub.a
libble_host_local_privacy_stub.a
libble_host_rpa_resolution_stub.a
```

### 16.2 Always configure after Studio regeneration

When Studio changes `Integration.cmake`, regenerate the CMake build graph before compiling:

```powershell
cmake --preset project
cmake --build --preset default_config
```

Alternatively, use the workflow preset if supported by the local CMake setup:

```powershell
cmake --workflow --preset project
```

### 16.3 Preserve event diagnostics

Do not remove the Security Manager or connection-close logs after the demo. They are low-frequency and provide the exact boundary of future failures.

### 16.4 Keep BLE independent of sensors

The device must advertise, connect, bond, and expose diagnostic values even when ECG, PPG, or IMU hardware is missing. Sensor failure must not block the BLE host event loop.

### 16.5 Do not use repeated bond deletion as normal recovery

Deleting bonds is appropriate when keys are genuinely mismatched. It should not be the first action for every failed connection because it destroys useful state and can hide the original reason.

## 17. Security Scope

Bonding provides encrypted BLE transport and peer key persistence. It does not by itself make the entire medical platform HIPAA compliant.

Future production controls still include:

- Explicit device-to-patient assignment
- Authorized hub enrollment
- Secure API authentication
- Encryption at rest and in transit beyond BLE
- Audit logging
- Key rotation and device revocation
- Secure firmware update and signed images
- Debug interface lockdown
- Manufacturing identity provisioning

For the hackathon, Just Works bonding is a reasonable integration checkpoint. For production medical use, enrollment and authorization must prevent an arbitrary nearby central from becoming a trusted peer.

## 18. Final Root Cause Statement

The Tarang radio and basic BLE connection were functional. The bonding path failed because the Platform project compiled against Security Manager APIs while linking stub security and bonding libraries, and the application explicitly configured the device as non-bondable. Simplicity Studio component generation corrected the dependency graph, but a stale native build graph initially continued to reference the stubs. After adding Security Manager through Studio, regenerating, reconfiguring CMake, linking the real crypto/bonding/privacy libraries, enabling bondable mode, and adding persistent NVM3-backed Just Works bonding, the firmware built successfully and is ready for final phone and Raspberry Pi bond validation.

## 19. Files Relevant to This Fix

```text
projects/tarang-firmware/Integration/Integration.slcp
projects/tarang-firmware/Integration/app.c
projects/tarang-firmware/Integration/tarang_ble.c
projects/tarang-firmware/Integration/tarang_ble.h
projects/tarang-firmware/Integration/config/btconf/gatt_configuration.btconf
projects/tarang-firmware/Integration/cmake_gcc/Integration.cmake
projects/tarang-rpi/dashboard/backend/ble_gateway.py
```

Generated files under `autogen/` and Studio-managed configuration should continue to be changed only through Simplicity Studio.
