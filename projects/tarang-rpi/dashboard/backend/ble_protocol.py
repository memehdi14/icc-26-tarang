"""Tarang Mode A BLE UUIDs and binary packet decoders."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Final


VITALS_SERVICE_UUID: Final = "544e937a-82f3-4395-b62b-b72bdea94c75"
VITALS_HR_UUID: Final = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"
VITALS_SPO2_UUID: Final = "b4cf8877-ba1a-414c-a99d-de85a13fd66b"
VITALS_TIMESTAMP_UUID: Final = "b4cf8877-ba1a-414c-a99d-de85a13fd66c"

ANALYTICS_SERVICE_UUID: Final = "655f937a-82f3-4395-b62b-b72bdea94c75"
ANALYTICS_BURDEN_UUID: Final = "c5da9988-ca2b-425d-b00e-ef96b24ee77b"

EVENT_SERVICE_UUID: Final = "7660937a-82f3-4395-b62b-b72bdea94c75"
EVENT_RHYTHM_UUID: Final = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88a"
EVENT_META_UUID: Final = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88b"
EVENT_ECG_CHUNK_UUID: Final = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88c"
EVENT_ECG_CONTROL_UUID: Final = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88d"
EVENT_ANNOTATIONS_UUID: Final = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88e"
EVENT_TICKER_UUID: Final = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88f"

REQUIRED_SERVICE_UUIDS: Final = frozenset(
    {VITALS_SERVICE_UUID, ANALYTICS_SERVICE_UUID, EVENT_SERVICE_UUID}
)
REQUIRED_SUBSCRIPTION_UUIDS: Final = frozenset(
    {VITALS_HR_UUID, VITALS_SPO2_UUID, EVENT_META_UUID}
)

PATTERN_NAMES: Final = {
    1: "Couplet",
    2: "Triplet",
    3: "Bigeminy",
    4: "Trigeminy",
    5: "V-Run",
    6: "SVT-Run",
}

RHYTHM_NAMES: Final = {
    0: "NSR",
    1: "AFib",
    2: "VT",
    3: "Bradycardia",
    4: "Tachycardia",
}

_ANALYTICS = struct.Struct("<BBHHBBB")
_EVENT_META = struct.Struct("<HBBI")
_EVENT_TICKER = struct.Struct("<HI")
_ANNOTATION = struct.Struct("<HBB")
_CHUNK_HEADER = struct.Struct("<HH")

MAX_SNIPPET_CHUNKS: Final = 32
MAX_SNIPPET_SAMPLES: Final = 2000


class ProtocolError(ValueError):
    """Raised when a BLE payload violates the Tarang wire contract."""


@dataclass(frozen=True)
class EventMeta:
    event_id: int
    event_type: int
    confidence: int
    timestamp_ms: int


@dataclass(frozen=True)
class EventTicker:
    pattern_type: int
    timestamp_ms: int


def _require_size(data: bytes | bytearray, expected: int, packet_name: str) -> None:
    if len(data) < expected:
        raise ProtocolError(
            f"{packet_name} packet is {len(data)} bytes; expected at least {expected}"
        )


def decode_heart_rate(data: bytes | bytearray) -> int:
    _require_size(data, 2, "heart-rate")
    return struct.unpack_from("<H", data)[0]


def decode_spo2(data: bytes | bytearray) -> int:
    _require_size(data, 1, "SpO2")
    value = data[0]
    if value > 100:
        raise ProtocolError(f"SpO2 value {value} is outside 0..100")
    return value


def decode_analytics(data: bytes | bytearray) -> dict[str, float]:
    _require_size(data, _ANALYTICS.size, "analytics")
    pvc, pac, sdnn, rmssd, prr50, duty_cycle_x10, sleep_pct = (
        _ANALYTICS.unpack_from(data)
    )
    return {
        "pvc_burden_pct": float(pvc),
        "pac_burden_pct": float(pac),
        "sdnn": float(sdnn),
        "rmssd": float(rmssd),
        "prr50": float(prr50),
        "ai_duty_cycle_pct": duty_cycle_x10 / 10.0,
        "em2_sleep_pct": float(sleep_pct),
    }


def decode_event_meta(data: bytes | bytearray) -> EventMeta:
    _require_size(data, _EVENT_META.size, "event-meta")
    return EventMeta(*_EVENT_META.unpack_from(data))


def decode_event_ticker(data: bytes | bytearray) -> EventTicker:
    _require_size(data, _EVENT_TICKER.size, "event-ticker")
    return EventTicker(*_EVENT_TICKER.unpack_from(data))


def _decode_annotation_label(value: int) -> str:
    numeric_labels = {0: "N", 1: "S", 2: "V", 3: "Q"}
    if value in numeric_labels:
        return numeric_labels[value]
    if value in (ord("N"), ord("S"), ord("V"), ord("Q")):
        return chr(value)
    return "Q"


def decode_annotations(data: bytes | bytearray) -> list[dict[str, int | float | str]]:
    if len(data) % _ANNOTATION.size != 0:
        raise ProtocolError(
            f"annotations packet is {len(data)} bytes; expected a multiple of 4"
        )

    annotations: list[dict[str, int | float | str]] = []
    for offset in range(0, len(data), _ANNOTATION.size):
        offset_ms, label_code, confidence = _ANNOTATION.unpack_from(data, offset)
        annotations.append(
            {
                "offset_ms": offset_ms,
                "label": _decode_annotation_label(label_code),
                "confidence": confidence / 255.0,
            }
        )
    return annotations


class SnippetReassembler:
    """Reassembles out-of-order ECG indication chunks with strict bounds."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._chunks: dict[int, tuple[int, ...]] = {}
        self._total_chunks = 0

    @property
    def total_chunks(self) -> int:
        return self._total_chunks

    @property
    def received_chunks(self) -> int:
        return len(self._chunks)

    def add_chunk(self, data: bytes | bytearray) -> list[float] | None:
        _require_size(data, _CHUNK_HEADER.size + 2, "ECG chunk")
        if (len(data) - _CHUNK_HEADER.size) % 2:
            raise ProtocolError("ECG chunk contains an incomplete int16 sample")

        sequence_id, total_chunks = _CHUNK_HEADER.unpack_from(data)
        if not 1 <= total_chunks <= MAX_SNIPPET_CHUNKS:
            raise ProtocolError(f"invalid ECG total_chunks value {total_chunks}")
        if sequence_id >= total_chunks:
            raise ProtocolError(
                f"ECG sequence {sequence_id} is outside total {total_chunks}"
            )

        if self._total_chunks and total_chunks != self._total_chunks:
            self.reset()
        self._total_chunks = total_chunks

        sample_count = (len(data) - _CHUNK_HEADER.size) // 2
        samples = struct.unpack_from(
            f"<{sample_count}h", data, _CHUNK_HEADER.size
        )
        self._chunks[sequence_id] = samples

        received_samples = sum(len(chunk) for chunk in self._chunks.values())
        if received_samples > MAX_SNIPPET_SAMPLES:
            self.reset()
            raise ProtocolError("ECG snippet exceeds the configured sample limit")

        if len(self._chunks) != self._total_chunks:
            return None

        waveform: list[float] = []
        for index in range(self._total_chunks):
            if index not in self._chunks:
                return None
            waveform.extend(float(sample) for sample in self._chunks[index])
        self.reset()
        return waveform
