"""Printer status-packet parsing.

The PT-P750W / P710BT / E550W reply to an ``ESC i S`` status request with a
fixed 32-byte packet. This module parses that packet into a structured
:class:`PrinterStatus` and exposes helpers for formatting errors, detecting
the loaded tape width, and verifying that a job's requested tape matches
what's physically loaded.

Designed to run without hardware present: the parser takes raw bytes, and
``build_mock_status()`` composes a valid packet for tests / dry-runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from label_printer.constants import (
    STATUS_PACKET_SIZE,
    ErrorInformation1,
    ErrorInformation2,
    MediaType,
    Mode,
    StatusOffset,
    StatusType,
)
from label_printer.tape import TapeWidth


class StatusPacketError(ValueError):
    """Raised when a status packet is malformed or the wrong size."""


class TapeMismatchError(RuntimeError):
    """Raised when the tape physically loaded doesn't match the job's requested tape."""


class TapeColor(IntEnum):
    """Subset of the colours reported at offset 24 — extend as needed."""

    WHITE = 0x01
    CLEAR = 0x03
    RED = 0x04
    BLUE = 0x05
    YELLOW = 0x06
    GREEN = 0x07
    BLACK = 0x08
    MATTE_WHITE = 0x20
    MATTE_CLEAR = 0x21
    UNKNOWN = 0xFF


class TextColor(IntEnum):
    WHITE = 0x01
    RED = 0x04
    BLUE = 0x05
    BLACK = 0x08
    UNKNOWN = 0xFF


@dataclass(frozen=True)
class PrinterStatus:
    """Decoded snapshot of the printer's current state."""

    raw: bytes
    error_info_1: int
    error_info_2: int
    media_width_mm: int
    media_type: int  # raw byte; use media_type_enum for the IntEnum if recognised
    mode: int
    status_type: int
    tape_color: int
    text_color: int
    # Pre-decoded alert names from out-of-band sources (currently SNMP's
    # hrPrinterDetectedErrorState). Empty for the in-band ESC i S path; the
    # bit fields above are decoded inside describe_errors() instead.
    alerts: tuple[str, ...] = ()

    @property
    def has_error(self) -> bool:
        return bool(self.error_info_1) or bool(self.error_info_2) or bool(self.alerts)

    @property
    def has_media(self) -> bool:
        return self.media_width_mm > 0 and self.media_type != MediaType.NO_MEDIA

    def tape_width(self) -> TapeWidth | None:
        """Map the reported media width to a known TapeWidth, or None if unknown."""
        try:
            return TapeWidth(self.media_width_mm)
        except ValueError:
            return None

    def describe_errors(self) -> list[str]:
        # Pre-decoded alerts (SNMP path) take precedence — they're the most
        # specific source. The bit-field fallback is for the ESC i S path,
        # which never sets `alerts`.
        if self.alerts:
            return list(self.alerts)
        parts: list[str] = []
        if self.error_info_1:
            if self.error_info_1 & ErrorInformation1.NO_MEDIA:
                parts.append("no media")
            if self.error_info_1 & ErrorInformation1.CUTTER_JAM:
                parts.append("cutter jam")
            if self.error_info_1 & ErrorInformation1.WEAK_BATTERIES:
                parts.append("weak batteries")
            if self.error_info_1 & ErrorInformation1.HIGH_VOLTAGE_ADAPTER:
                parts.append("high-voltage adapter")
        if self.error_info_2:
            if self.error_info_2 & ErrorInformation2.WRONG_MEDIA:
                parts.append("wrong media")
            if self.error_info_2 & ErrorInformation2.COVER_OPEN:
                parts.append("cover open")
            if self.error_info_2 & ErrorInformation2.OVERHEATING:
                parts.append("overheating")
        return parts


def parse_status(packet: bytes) -> PrinterStatus:
    if len(packet) != STATUS_PACKET_SIZE:
        raise StatusPacketError(
            f"status packet must be {STATUS_PACKET_SIZE} bytes, got {len(packet)}"
        )
    return PrinterStatus(
        raw=bytes(packet),
        error_info_1=packet[StatusOffset.ERROR_INFORMATION_1],
        error_info_2=packet[StatusOffset.ERROR_INFORMATION_2],
        media_width_mm=packet[StatusOffset.MEDIA_WIDTH],
        media_type=packet[StatusOffset.MEDIA_TYPE],
        mode=packet[StatusOffset.MODE],
        status_type=packet[StatusOffset.STATUS_TYPE],
        tape_color=packet[StatusOffset.TAPE_COLOR],
        text_color=packet[StatusOffset.TEXT_COLOR],
    )


def build_mock_status(
    *,
    media_width_mm: int = 12,
    media_type: int = int(MediaType.LAMINATED_TAPE),
    tape_color: int = int(TapeColor.WHITE),
    text_color: int = int(TextColor.BLACK),
    error_info_1: int = 0,
    error_info_2: int = 0,
    status_type: int = int(StatusType.REPLY_TO_REQUEST),
    mode: int = int(Mode.AUTO_CUT),
) -> bytes:
    """Build a 32-byte status packet with the given fields for tests / mocks."""
    packet = bytearray(STATUS_PACKET_SIZE)
    # Header — a plausible reply prefix; not parsed, but keep something sensible.
    packet[0] = 0x80
    packet[1] = 0x20
    packet[2] = 0x42
    packet[StatusOffset.ERROR_INFORMATION_1] = error_info_1
    packet[StatusOffset.ERROR_INFORMATION_2] = error_info_2
    packet[StatusOffset.MEDIA_WIDTH] = media_width_mm
    packet[StatusOffset.MEDIA_TYPE] = media_type
    packet[StatusOffset.MODE] = mode
    packet[StatusOffset.STATUS_TYPE] = status_type
    packet[StatusOffset.TAPE_COLOR] = tape_color
    packet[StatusOffset.TEXT_COLOR] = text_color
    return bytes(packet)


def ensure_tape_matches(status: PrinterStatus, requested: TapeWidth) -> None:
    """Raise if the physical tape doesn't match the job's requested width.

    Callers (CLI / service) should use this before a real ``--send`` to fail
    loudly rather than waste tape on a wrong-tape print.
    """
    if not status.has_media:
        raise TapeMismatchError("no tape loaded (or cover open)")
    if status.has_error:
        raise TapeMismatchError(f"printer reports errors: {', '.join(status.describe_errors())}")
    loaded = status.tape_width()
    if loaded is None:
        raise TapeMismatchError(
            f"loaded tape reports as {status.media_width_mm}mm — not a recognised width"
        )
    if loaded != requested:
        raise TapeMismatchError(
            f"wrong tape loaded: want {int(requested)}mm, printer has {int(loaded)}mm"
        )


def check_tape_or_warn(transport, requested: TapeWidth) -> str | None:
    """Shared pre-print tape check for CLI and service.

    Returns a warning string when the check had to be skipped (the transport
    can't report status — e.g. SNMP disabled on a network printer), or None
    when the loaded tape matches ``requested``.

    Raises:
        TapeMismatchError: the printer answered and the tape doesn't match
            (or it reports an error / no media).
        StatusQueryError: the transport claims to be status-aware but the
            query itself failed for an unexpected reason.
    """
    from label_printer.transport.base import StatusUnavailable

    try:
        status = transport.query_status()
    except StatusUnavailable as e:
        return (
            f"tape-width pre-check skipped ({e}); confirm "
            f"{int(requested)}mm tape is loaded"
        )
    except Exception as e:
        raise StatusQueryError(str(e)) from e
    ensure_tape_matches(status, requested)
    return None


class StatusQueryError(RuntimeError):
    """Raised when a status-aware transport fails to answer a status query."""
