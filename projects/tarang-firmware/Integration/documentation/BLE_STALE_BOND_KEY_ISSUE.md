# TARANG BLE Stale Bond Key Incident Report

## Executive Summary

TARANG connected and bonded successfully from a second phone, while the original phone disconnected when bonding was attempted. This proves that the EFR32 Bluetooth radio, GATT server, Security Manager, persistent bonding database, and Just Works pairing flow are operational.

The original phone contains a stale Bluetooth bond. It expects encryption to resume using keys generated during an earlier pairing, while the EFR32 no longer has the matching keys and generates a new set during a fresh pairing attempt. The phone and peripheral therefore disagree about the security state of the same Bluetooth identity address.

This is an asymmetric or half-deleted bond, not a BLE transport failure.

## Confirmed Evidence

1. The original phone can establish an unencrypted BLE connection and discover the TARANG GATT database.
2. The connection fails specifically when encryption or bonding begins.
3. A different phone connects and bonds successfully with the same firmware and hardware.
4. Therefore, the failure follows the original phone's stored Bluetooth state rather than the EFR32 hardware or firmware image.

## How BLE Bonding Works

During pairing, the phone and EFR32 negotiate encryption and may store a persistent bond. The stored information can include:

- Long Term Key (LTK) used to encrypt later connections.
- Encryption diversifier and random values used by legacy pairing.
- Identity Resolving Key (IRK) used with private addresses.
- Connection Signature Resolving Key (CSRK), where applicable.
- Peer identity address and security metadata.

Both devices must retain matching records. A bond is valid only while the phone's record and the EFR32 bonding-database record describe the same keys.

## Failure Sequence

The observed failure is consistent with this sequence:

1. TARANG and the original phone bond successfully.
2. The EFR32 is erased, its NVM3 bonding data is cleared, or firmware changes recreate the bonding database.
3. The phone retains its old TARANG bond because Android was not told to forget it.
4. TARANG continues advertising with the same Bluetooth identity address.
5. Android recognizes that address as an already-bonded device and attempts to use the old LTK.
6. The EFR32 has no matching LTK and treats the connection as new.
7. The two sides cannot authenticate or resume encryption.
8. SMP reports a missing or invalid key and the connection is terminated.

A typical Silicon Labs status for this condition is:

```text
SL_STATUS_BT_CTRL_PIN_OR_KEY_MISSING = 0x1006
```

Other layers may expose the same condition as authentication failure, insufficient authentication, encryption failure, GATT host configuration error, or an abrupt disconnect.

## Why the Other Phone Works

The second phone had no stored bond for TARANG's identity address. It therefore performed a completely fresh pairing:

```text
New phone has no TARANG key
        -> starts fresh SMP pairing
        -> EFR32 generates and stores a matching bond
        -> phone stores the same bond
        -> encryption succeeds
```

This is decisive evidence that the current peripheral security implementation works.

## Why Clearing Only the EFR32 Is Insufficient

Erasing the EFR32 removes only one side of the bond. The phone is not automatically informed that the peripheral keys were erased. Because TARANG continues using the same identity address, Android can continue treating it as the previously bonded device.

For a clean recovery, one of the following must happen:

1. Delete the bond from both devices.
2. Delete the phone's bond and allow the EFR32 to replace its record.
3. Clear the EFR32 bond and change the peripheral identity address so the phone sees a new device.

Changing only the advertised device name is insufficient. Bonds are associated with Bluetooth identity, not the display name.

## Recovery Options for the Original Phone

### Option A: Forget TARANG Normally

Use Android Bluetooth settings to forget or unpair TARANG, then reconnect and create a new bond. This is preferred because it removes only the affected bond.

### Option B: Reset Android Bluetooth State

If Android does not expose a working Forget action:

1. Open the Android network reset settings.
2. Select **Reset Wi-Fi, mobile network, and Bluetooth** or the vendor-equivalent option.
3. Reboot the phone.
4. Pair TARANG again.

This removes all Bluetooth pairings, not only TARANG.

Some phones permit clearing storage for the system Bluetooth application under **Settings > Apps > Show system apps > Bluetooth > Storage**. This is vendor-dependent and also removes other pairings.

### Option C: Use a New TARANG Identity Address

The firmware can temporarily call `sl_bt_gap_set_identity_address()` with a valid random static address before advertising. Android will see a new peripheral and will not associate it with the stale bond.

Consequences:

- The Raspberry Pi must use the new MAC address.
- The address should be unique per physical device.
- A stable production identity must be chosen deliberately.
- Repeatedly changing identity addresses should not become the normal recovery mechanism.

### Option D: Continue with the Second Phone

The second phone already has a valid synchronized bond and can be used immediately for testing.

## Correct TARANG Pairing Ownership

Only one side should initiate SMP for a connection.

The restored TARANG design uses central-initiated bonding:

```text
Phone or Raspberry Pi connects
        -> central initiates bonding
        -> TARANG accepts Just Works pairing
        -> both sides store the bond
        -> protected GATT subscriptions begin
```

TARANG remains bondable and its GATT telemetry remains marked `bonded=true` and `encrypted=true`. The peripheral does not simultaneously call `sl_bt_sm_increase_security()` while the phone or BlueZ is already initiating pairing. This avoids a dual-initiator SMP race.

## Raspberry Pi Equivalent

BlueZ can suffer the same stale-bond condition. Clear the Raspberry Pi side before recreating a bond:

```bash
bluetoothctl remove 64:02:8F:64:26:14
sudo systemctl restart bluetooth
```

Then ensure TARANG is advertising and pair again:

```bash
bluetoothctl
power on
agent NoInputNoOutput
default-agent
scan on
pair 64:02:8F:64:26:14
trust 64:02:8F:64:26:14
connect 64:02:8F:64:26:14
```

Do not repeatedly delete the BlueZ device immediately after a failed attempt while TARANG is no longer advertising. Wait for TARANG to reappear in a fresh scan first.

## Firmware Logging Required During Pairing

The following events should remain logged:

```text
[BLE] Connection opened
[BLE][SM] Bonded: conn=... handle=... security=...
[BLE][SM] Bonding failed: conn=... reason=0x....
[BLE] Connection closed: reason=0x....
```

These messages distinguish stale keys from radio loss, supervision timeout, GATT permission failure, and bonding-database exhaustion.

## Prevention During Development

1. Avoid erasing NVM3 during ordinary firmware updates when existing bonds must survive.
2. Use a flash operation that preserves the bonding region when the Bluetooth identity and security configuration are unchanged.
3. When intentionally clearing the EFR32 bonding database, also remove the corresponding phone and BlueZ bonds.
4. Keep a single SMP initiator. For TARANG, the central phone or Raspberry Pi owns pairing initiation.
5. Do not call `sl_bt_sm_delete_bondings()` on every boot; this guarantees asymmetric bonds after every restart.
6. Do not change the Bluetooth identity address after deployment unless performing an explicit recovery or provisioning operation.
7. Store and display bonding failure and disconnect reason codes in diagnostics.
8. Consider a physical recovery action, such as holding a button during boot to clear bonds and enter provisioning mode.
9. Keep normal firmware upgrades and factory resets separate. A factory reset may clear bonds; a firmware upgrade normally should not.

## Production Recovery Design

A robust patient-device workflow should provide an explicit bond-reset mode:

1. User holds a hardware button for a defined duration.
2. TARANG calls `sl_bt_sm_delete_bondings()` once.
3. TARANG enters a clearly indicated provisioning mode.
4. The app instructs the user to remove the old Android bond.
5. A new central-initiated bond is created.
6. TARANG exits provisioning mode and retains the new bond across reboots.

For managed hospital deployments, the device record should also track its Bluetooth identity, bonding epoch, firmware version, and last successful security level.

## Final Diagnosis

The original phone expected the old TARANG encryption key. The EFR32 no longer possessed that key and attempted to establish a new bond under the same identity address. This key mismatch caused encryption or authentication to fail and the connection to close.

The successful bond from another phone proves that TARANG's current BLE radio, Security Manager, GATT permissions, and bonding implementation are functional.

## References

- [Silicon Labs Bluetooth Security Manager API](https://docs.silabs.com/bluetooth/7.1.2/bluetooth-stack-api/sl-bt-sm)
- [Silicon Labs Bluetooth Application Security Design Considerations](https://docs.silabs.com/bluetooth/latest/bluetooth-application-security-design-considerations/02-working-with-stack-security-features)
