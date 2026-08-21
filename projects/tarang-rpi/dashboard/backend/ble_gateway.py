#!/usr/bin/env python3
"""Tarang BLE-to-HTTP gateway for Raspberry Pi and BlueZ."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
import random
import subprocess
import time
from typing import Any, Callable

import httpx
from bleak import BleakClient, BleakScanner

from ble_protocol import (
    ANALYTICS_CHARACTERISTIC_UUIDS,
    EVENT_ANNOTATIONS_UUID,
    EVENT_ECG_CHUNK_UUID,
    EVENT_META_UUID,
    EVENT_RHYTHM_UUID,
    EVENT_TICKER_UUID,
    PATTERN_NAMES,
    ProtocolError,
    REQUIRED_SERVICE_UUIDS,
    REQUIRED_SUBSCRIPTION_UUIDS,
    SnippetReassembler,
    VITALS_HR_UUID,
    VITALS_SPO2_UUID,
    decode_analytics,
    decode_analytics_characteristic,
    decode_annotations,
    decode_event_meta,
    decode_event_ticker,
    decode_heart_rate,
    decode_spo2,
)


LOG = logging.getLogger("tarang.ble_gateway")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true/false, yes/no, on/off, or 1/0")


def _env_float(name: str, default: float, minimum: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class GatewayConfig:
    backend_url: str
    ble_address: str | None
    name_prefix: str
    device_id: str | None
    session_id: str | None
    pair: bool
    scan_timeout_s: float
    connect_timeout_s: float
    reconnect_delay_s: float
    diagnostics_interval_s: float

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        address = os.getenv("TARANG_BLE_ADDRESS")
        return cls(
            backend_url=os.getenv(
                "TARANG_BACKEND_URL", "http://localhost:8000"
            ).rstrip("/"),
            ble_address=address.strip().upper() if address else None,
            name_prefix=os.getenv("TARANG_BLE_NAME_PREFIX", "TARANG").strip().upper(),
            device_id=os.getenv("TARANG_DEVICE_ID") or None,
            session_id=os.getenv("TARANG_SESSION_ID") or None,
            pair=_env_bool("TARANG_BLE_PAIR", True),
            scan_timeout_s=_env_float("TARANG_BLE_SCAN_TIMEOUT", 10.0, 1.0),
            connect_timeout_s=_env_float(
                "TARANG_BLE_CONNECT_TIMEOUT", 35.0, 5.0
            ),
            reconnect_delay_s=_env_float(
                "TARANG_BLE_RECONNECT_DELAY", 5.0, 1.0
            ),
            diagnostics_interval_s=_env_float(
                "TARANG_DIAGNOSTICS_INTERVAL", 10.0, 2.0
            ),
        )


@dataclass
class GatewayMetrics:
    packets_forwarded: int = 0
    packets_dropped: int = 0
    last_ingest_latency_ms: float = 0.0


class BackendPublisher:
    """Bounded, ordered HTTP publisher with retry and delivery metrics."""

    def __init__(self, backend_url: str, max_queue_size: int = 256) -> None:
        self.backend_url = backend_url
        self.metrics = GatewayMetrics()
        self._http = httpx.AsyncClient(base_url=backend_url, timeout=4.0)
        self._queue: asyncio.Queue[tuple[str, dict[str, Any], str]] = (
            asyncio.Queue(maxsize=max_queue_size)
        )
        self._worker_task: asyncio.Task[None] | None = None

    async def wait_until_ready(self) -> None:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._http.get("/api/health")
                response.raise_for_status()
                LOG.info("Backend ready at %s", self.backend_url)
                return
            except (httpx.HTTPError, OSError) as exc:
                delay = min(15.0, 1.5 * attempt)
                LOG.warning(
                    "Backend unavailable at %s (%s); retrying in %.1fs",
                    self.backend_url,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._worker(), name="backend-publisher"
            )

    async def synchronize_device(
        self, device_id: str, name: str, mac_address: str
    ) -> None:
        payload = {
            "name": name,
            "mac_address": mac_address,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            response = await self._http.get(f"/api/devices/{device_id}")
            if response.status_code == 404:
                create_response = await self._http.post(
                    "/api/devices",
                    json={
                        "device_id": device_id,
                        "name": name,
                        "mac_address": mac_address,
                        "status": "available",
                    },
                )
                create_response.raise_for_status()
                LOG.info("Registered device %s with backend", device_id)
                return
            response.raise_for_status()
            update_response = await self._http.patch(
                f"/api/devices/{device_id}", json=payload
            )
            update_response.raise_for_status()
        except httpx.HTTPError as exc:
            LOG.warning("Could not synchronize device inventory: %s", exc)

    async def resolve_active_session(self, device_id: str) -> str | None:
        try:
            response = await self._http.get(
                "/api/sessions", params={"status": "active"}
            )
            response.raise_for_status()
            for session in response.json():
                if session.get("device_id") == device_id:
                    return session.get("session_id")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            LOG.warning("Could not resolve active monitoring session: %s", exc)
        return None

    def enqueue(self, path: str, payload: dict[str, Any], packet_type: str) -> None:
        try:
            self._queue.put_nowait((path, payload, packet_type))
        except asyncio.QueueFull:
            self.metrics.packets_dropped += 1
            LOG.error("Backend queue full; dropped %s packet", packet_type)

    async def _worker(self) -> None:
        while True:
            path, payload, packet_type = await self._queue.get()
            try:
                delivered = False
                for attempt in range(1, 4):
                    started = time.monotonic()
                    try:
                        response = await self._http.post(path, json=payload)
                        response.raise_for_status()
                        self.metrics.last_ingest_latency_ms = round(
                            (time.monotonic() - started) * 1000.0, 1
                        )
                        self.metrics.packets_forwarded += 1
                        delivered = True
                        break
                    except (httpx.HTTPError, OSError) as exc:
                        if attempt == 3:
                            LOG.error(
                                "Failed to deliver %s packet to %s: %s",
                                packet_type,
                                path,
                                exc,
                            )
                        else:
                            await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                if not delivered:
                    self.metrics.packets_dropped += 1
            finally:
                self._queue.task_done()

    async def close(self) -> None:
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=5.0)
            except asyncio.TimeoutError:
                LOG.warning("Timed out draining backend queue during shutdown")
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
        await self._http.aclose()


@dataclass
class ClinicalEventBuffer:
    event_id: int | None = None
    rhythm_status: int | None = None
    pattern_type: int | None = None
    confidence: float = 1.0
    timestamp_ms: int | None = None
    waveform: list[float] | None = None
    annotations: list[dict[str, Any]] | None = None
    snippet_started: bool = False
    snippet_ended: bool = False
    posted: bool = False

    def reset(self, preserve_rhythm: int | None = None) -> None:
        self.event_id = None
        self.rhythm_status = preserve_rhythm
        self.pattern_type = None
        self.confidence = 1.0
        self.timestamp_ms = None
        self.waveform = None
        self.annotations = None
        self.snippet_started = False
        self.snippet_ended = False
        self.posted = False


class GatewaySession:
    """Owns callbacks and state for one BLE connection."""

    def __init__(
        self,
        config: GatewayConfig,
        publisher: BackendPublisher,
        device: Any,
        session_id: str | None,
    ) -> None:
        self.config = config
        self.publisher = publisher
        self.device = device
        self.address = str(device.address).upper()
        self.device_id = config.device_id or self.address
        self.session_id = session_id
        self.last_hr: int | None = None
        self.last_spo2: int | None = None
        self._loop = asyncio.get_running_loop()
        self._vitals_timer: asyncio.TimerHandle | None = None
        self._analytics_timer: asyncio.TimerHandle | None = None
        self._event_timer: asyncio.TimerHandle | None = None
        self._analytics_values: dict[str, float] = {
            "pvc_burden_pct": 0.0,
            "pac_burden_pct": 0.0,
            "sdnn": 0.0,
            "rmssd": 0.0,
            "prr50": 0.0,
            "ai_duty_cycle_pct": 0.0,
            "em2_sleep_pct": 0.0,
        }
        self._diagnostics_task: asyncio.Task[None] | None = None
        self._event = ClinicalEventBuffer()
        self._snippet = SnippetReassembler()

    def _base_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"device_id": self.device_id}
        if self.session_id:
            payload["session_id"] = self.session_id
        return payload

    def _decode(self, packet_name: str, decoder: Callable, data: bytearray):
        try:
            return decoder(data)
        except (ProtocolError, ValueError, TypeError) as exc:
            self.publisher.metrics.packets_dropped += 1
            LOG.warning("Discarded malformed %s packet: %s", packet_name, exc)
            return None

    def on_heart_rate(self, _sender: Any, data: bytearray) -> None:
        value = self._decode("heart-rate", decode_heart_rate, data)
        if value is not None:
            self.last_hr = value
            self._schedule_vitals()

    def on_spo2(self, _sender: Any, data: bytearray) -> None:
        value = self._decode("SpO2", decode_spo2, data)
        if value is not None:
            self.last_spo2 = value
            self._schedule_vitals()

    def _schedule_vitals(self) -> None:
        if self._vitals_timer is not None:
            self._vitals_timer.cancel()
        self._vitals_timer = self._loop.call_later(0.15, self._flush_vitals)

    def _flush_vitals(self) -> None:
        self._vitals_timer = None
        payload: dict[str, Any] = self._base_payload()
        payload["heart_rate_bpm"] = self.last_hr if (self.last_hr is not None and self.last_hr > 0) else None
        payload["spo2_pct"] = self.last_spo2 if (self.last_spo2 is not None and self.last_spo2 > 0) else None
        self.publisher.enqueue("/api/vitals", payload, "vitals")
        
        hr_str = f"{self.last_hr} BPM" if (self.last_hr is not None and self.last_hr > 0) else "Searching (0)"
        spo2_str = f"{self.last_spo2}%" if (self.last_spo2 is not None and self.last_spo2 > 0) else "No finger (0%)"
        LOG.info("[BLE][VITALS 2.5s] Periodic Packet Received -> HR: %s | SpO2: %s", hr_str, spo2_str)

    def on_analytics(self, _sender: Any, data: bytearray) -> None:
        """Compatibility callback for the retired nine-byte rollup."""
        decoded = self._decode("analytics", decode_analytics, data)
        if decoded is None:
            return
        self._analytics_values.update(decoded)
        self._schedule_analytics()

    def on_analytics_scalar(
        self, characteristic_uuid: str, _sender: Any, data: bytearray
    ) -> None:
        decoded = self._decode(
            "analytics scalar",
            lambda payload: decode_analytics_characteristic(
                characteristic_uuid, payload
            ),
            data,
        )
        if decoded is None:
            return
        field, value = decoded
        self._analytics_values[field] = value
        self._schedule_analytics()

    def _schedule_analytics(self) -> None:
        if self._analytics_timer is not None:
            self._analytics_timer.cancel()
        self._analytics_timer = self._loop.call_later(
            0.25, self._flush_analytics
        )

    def _flush_analytics(self) -> None:
        self._analytics_timer = None
        payload = self._base_payload()
        payload.update(self._analytics_values)
        self.publisher.enqueue("/api/analytics", payload, "analytics")
        LOG.info(
            "Analytics: PVC=%.1f%% PAC=%.1f%% SDNN=%.0fms",
            self._analytics_values["pvc_burden_pct"],
            self._analytics_values["pac_burden_pct"],
            self._analytics_values["sdnn"],
        )

    def on_rhythm(self, _sender: Any, data: bytearray) -> None:
        if not data:
            self.publisher.metrics.packets_dropped += 1
            LOG.warning("Discarded empty rhythm packet")
            return
        if self._event.posted:
            self._event.reset()
        self._event.rhythm_status = data[0]
        self._schedule_event_flush(2.0)

    def on_event_meta(self, _sender: Any, data: bytearray) -> None:
        meta = self._decode("event-meta", decode_event_meta, data)
        if meta is None:
            return
        if self._event.event_id not in (None, meta.event_id):
            self._flush_event()
            self._event.reset(preserve_rhythm=self._event.rhythm_status)
        self._event.event_id = meta.event_id
        self._event.rhythm_status = meta.event_type
        self._event.confidence = meta.confidence / 255.0
        self._event.timestamp_ms = meta.timestamp_ms
        self._snippet.reset()
        self._event.waveform = None
        self._event.annotations = None
        self._event.snippet_started = True
        self._event.snippet_ended = False
        self._schedule_event_flush(2.0)
        LOG.info(
            "Clinical event %d: rhythm=%d confidence=%.1f%%",
            meta.event_id,
            meta.event_type,
            self._event.confidence * 100.0,
        )

    def on_event_ticker(self, _sender: Any, data: bytearray) -> None:
        ticker = self._decode("event-ticker", decode_event_ticker, data)
        if ticker is None:
            return
        self._event.pattern_type = ticker.pattern_type
        self._schedule_event_flush(2.0)

    def on_event_control(self, _sender: Any, data: bytearray) -> None:
        if not data:
            return
        marker = data[0]
        if marker == 1:
            self._snippet.reset()
            self._event.waveform = None
            self._event.annotations = None
            self._event.snippet_started = True
            self._event.snippet_ended = False
            self._cancel_event_timer()
        elif marker == 3:
            self._event.snippet_ended = True
            self._schedule_event_flush(1.0)

    def on_ecg_chunk(self, _sender: Any, data: bytearray) -> None:
        try:
            waveform = self._snippet.add_chunk(data)
        except ProtocolError as exc:
            self.publisher.metrics.packets_dropped += 1
            LOG.warning("Discarded malformed ECG chunk: %s", exc)
            return
        if waveform is not None:
            self._event.waveform = waveform
            LOG.info("Reassembled ECG snippet with %d samples", len(waveform))
            self._schedule_event_flush(0.75)
        else:
            self._schedule_event_flush(3.0)

    def on_annotations(self, _sender: Any, data: bytearray) -> None:
        annotations = self._decode("annotations", decode_annotations, data)
        if annotations is not None:
            if self._event.annotations is None:
                self._event.annotations = []
            self._event.annotations.extend(annotations)
            self._schedule_event_flush(0.5)

    def _cancel_event_timer(self) -> None:
        if self._event_timer is not None:
            self._event_timer.cancel()
            self._event_timer = None

    def _schedule_event_flush(self, delay_s: float) -> None:
        self._cancel_event_timer()
        self._event_timer = self._loop.call_later(delay_s, self._flush_event)

    def _flush_event(self) -> None:
        self._event_timer = None
        if self._event.posted or self._event.rhythm_status is None:
            return

        if self._event.snippet_started and self._event.waveform is None:
            LOG.warning(
                "Posting event %s without waveform; received %d/%d ECG chunks",
                self._event.event_id,
                self._snippet.received_chunks,
                self._snippet.total_chunks,
            )

        pattern = None
        if self._event.pattern_type is not None:
            pattern = PATTERN_NAMES.get(
                self._event.pattern_type,
                f"Pattern-{self._event.pattern_type}",
            )

        payload: dict[str, Any] = self._base_payload()
        payload.update(
            {
                "rhythm_status": self._event.rhythm_status,
                "pattern_type": pattern,
                "confidence": self._event.confidence,
                "sample_rate_hz": 250,
                "waveform": self._event.waveform,
                "annotations": self._event.annotations,
            }
        )
        self.publisher.enqueue("/api/events", payload, "clinical-event")
        self._event.posted = True

    async def subscribe(self, client: BleakClient) -> None:
        subscriptions: list[tuple[str, Callable]] = [
            (VITALS_HR_UUID, self.on_heart_rate),
            (VITALS_SPO2_UUID, self.on_spo2),
            (EVENT_RHYTHM_UUID, self.on_rhythm),
            (EVENT_META_UUID, self.on_event_meta),
            (EVENT_ECG_CHUNK_UUID, self.on_ecg_chunk),
            (EVENT_ANNOTATIONS_UUID, self.on_annotations),
            (EVENT_TICKER_UUID, self.on_event_ticker),
        ]
        for analytics_uuid in ANALYTICS_CHARACTERISTIC_UUIDS:
            subscriptions.append(
                (
                    analytics_uuid,
                    lambda sender, data, uuid=analytics_uuid:
                        self.on_analytics_scalar(uuid, sender, data),
                )
            )

        LOG.info("Activating %d GATT notifications on TARANG pod...", len(subscriptions))
        active: set[str] = set()
        for uuid, handler in subscriptions:
            for attempt in range(2):
                try:
                    await asyncio.wait_for(client.start_notify(uuid, handler), timeout=2.0)
                    active.add(uuid)
                    LOG.info("Subscribed to %s", uuid)
                    await asyncio.sleep(0.04)  # Pacing delay to prevent link layer congestion
                    break
                except Exception as exc:
                    if attempt == 0:
                        await asyncio.sleep(0.2)
                    else:
                        LOG.warning("Subscription note for %s: %s", uuid, exc)

        missing_required = REQUIRED_SUBSCRIPTION_UUIDS - active
        if missing_required:
            LOG.warning(
                "Some GATT subscriptions could not be activated: %s",
                ", ".join(sorted(missing_required)),
            )
        LOG.info("All %d Mode A GATT subscriptions active — streaming live telemetry", len(active))

    def publish_diagnostics(self, connected: bool) -> None:
        metrics = self.publisher.metrics
        self.publisher.enqueue(
            "/api/diagnostics/update",
            {
                "ble_connected": connected,
                "device_name": self.device.name or "TARANG",
                "device_mac": self.address,
                "packets_received": metrics.packets_forwarded,
                "packets_dropped": metrics.packets_dropped,
                "latency_ms": metrics.last_ingest_latency_ms,
            },
            "diagnostics",
        )

    def start_diagnostics(self) -> None:
        self._diagnostics_task = asyncio.create_task(
            self._diagnostics_loop(), name="ble-diagnostics"
        )

    async def _diagnostics_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.diagnostics_interval_s)
            if self.config.session_id is None:
                resolved = await self.publisher.resolve_active_session(self.device_id)
                if resolved != self.session_id:
                    LOG.info("Active monitoring session changed to %s", resolved)
                    self.session_id = resolved
            self.publish_diagnostics(True)

    async def close(self) -> None:
        if self._vitals_timer is not None:
            self._vitals_timer.cancel()
        if self._analytics_timer is not None:
            self._analytics_timer.cancel()
        self._cancel_event_timer()
        if self._diagnostics_task is not None:
            self._diagnostics_task.cancel()
            await asyncio.gather(self._diagnostics_task, return_exceptions=True)


class BleGateway:
    def __init__(self, config: GatewayConfig, publisher: BackendPublisher) -> None:
        self.config = config
        self.publisher = publisher
        if config.session_id is None:
            LOG.warning(
                "TARANG_SESSION_ID is unset; active sessions will be resolved from the backend"
            )

    async def start_discovery(self) -> tuple[BleakScanner | None, Any | None]:
        """Find TARANG while leaving discovery active for the initial connect."""
        loop = asyncio.get_running_loop()
        found: asyncio.Future[Any] = loop.create_future()
        address = self.config.ble_address
        prefix = self.config.name_prefix

        if address:
            LOG.info("Scanning for configured device %s", address)
        else:
            LOG.info("Scanning for a device named %s*", prefix)

        def on_advertisement(device: Any, advertisement_data: Any) -> None:
            if found.done():
                return
            device_address = str(device.address).upper()
            name = advertisement_data.local_name or device.name or ""
            if (address and device_address == address) or (
                not address and name.upper().startswith(prefix)
            ):
                found.set_result(device)

        scanner = BleakScanner(detection_callback=on_advertisement)
        await scanner.start()
        try:
            device = await asyncio.wait_for(found, timeout=self.config.scan_timeout_s)
            return scanner, device
        except asyncio.TimeoutError:
            await scanner.stop()
            return None, None
        except BaseException:
            await scanner.stop()
            raise

    async def run_forever(self) -> None:
        reconnect_delay = self.config.reconnect_delay_s
        while True:
            scanner, device = await self.start_discovery()
            if device is None:
                LOG.warning("Tarang device not found; retrying in %.1fs", reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(30.0, reconnect_delay * 1.5)
                continue

            disconnected = asyncio.Event()
            loop = asyncio.get_running_loop()

            def on_disconnect(_client: BleakClient) -> None:
                loop.call_soon_threadsafe(disconnected.set)

            session = GatewaySession(
                self.config, self.publisher, device, self.config.session_id
            )
            LOG.info(
                "Connecting to %s (%s) before pairing; discovery remains active",
                device.name or "TARANG",
                device.address,
            )

            client = BleakClient(
                device,
                disconnected_callback=on_disconnect,
                timeout=self.config.connect_timeout_s,
                pair=False,
            )
            try:
                await client.connect()
                if not client.is_connected:
                    raise RuntimeError("Bleak returned without an active connection")

                if self.config.pair:
                    try:
                        LOG.info("GATT resolved; requesting bond on the connected link")
                        await client.pair()
                        LOG.info("BLE pairing complete (Bonded & Encrypted)")
                        await asyncio.sleep(0.5)
                    except Exception as pair_exc:
                        exc_msg = str(pair_exc)
                        if "AlreadyExists" in exc_msg or "already" in exc_msg.lower():
                            LOG.info("Device already paired in BlueZ: %s", exc_msg)
                        else:
                            LOG.warning("Pairing request note: %s", exc_msg)
                            try:
                                subprocess.run(
                                    ["bluetoothctl", "remove", str(device.address)],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    timeout=1.5,
                                )
                            except Exception:
                                pass

                # Once connected and paired, BlueZ retains the device object and
                # discovery can stop without invalidating the connection.
                if scanner is not None:
                    await scanner.stop()
                    scanner = None

                service_uuids = {service.uuid.lower() for service in client.services}
                missing_services = REQUIRED_SERVICE_UUIDS - service_uuids
                if missing_services:
                    raise RuntimeError(
                        "Tarang GATT services missing: "
                        + ", ".join(sorted(missing_services))
                    )

                await self.publisher.synchronize_device(
                    session.device_id,
                    device.name or "Tarang Wearable",
                    session.address,
                )
                if self.config.session_id is None:
                    session.session_id = (
                        await self.publisher.resolve_active_session(
                            session.device_id
                        )
                    )

                LOG.info(
                    "Connected and GATT verified (MTU=%s, session=%s)",
                    client.mtu_size,
                    session.session_id or "unassigned",
                )
                reconnect_delay = self.config.reconnect_delay_s
                await session.subscribe(client)
                session.publish_diagnostics(True)
                session.start_diagnostics()
                await disconnected.wait()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.error("BLE session failed: %s", exc, exc_info=True)
            finally:
                if scanner is not None:
                    await scanner.stop()
                if client.is_connected:
                    await client.disconnect()
                await session.close()
                session.publish_diagnostics(False)

            jitter = random.uniform(0.0, 0.75)
            LOG.info("Reconnecting in %.1fs", reconnect_delay + jitter)
            await asyncio.sleep(reconnect_delay + jitter)


async def async_main() -> None:
    config = GatewayConfig.from_env()
    publisher = BackendPublisher(config.backend_url)
    try:
        await publisher.wait_until_ready()
        publisher.start()
        await BleGateway(config, publisher).run_forever()
    finally:
        await publisher.close()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("TARANG_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        LOG.info("Gateway stopped")


if __name__ == "__main__":
    main()
