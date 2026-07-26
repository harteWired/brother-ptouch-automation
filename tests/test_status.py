"""Status-packet parsing + tape-match verification."""

from __future__ import annotations

import pytest

from label_printer.constants import (
    STATUS_PACKET_SIZE,
    ErrorInformation1,
    ErrorInformation2,
    MediaType,
    StatusType,
)
from label_printer.status import (
    StatusPacketError,
    StatusQueryError,
    TapeMismatchError,
    build_mock_status,
    check_tape_or_warn,
    ensure_tape_matches,
    parse_status,
)
from label_printer.tape import TapeWidth
from label_printer.transport import DryRunTransport, StatusUnavailable
from label_printer.transport.dryrun import mock_dryrun_with_tape


def test_parse_rejects_wrong_size():
    with pytest.raises(StatusPacketError):
        parse_status(b"\x00" * 10)


def test_parse_happy_path():
    packet = build_mock_status(media_width_mm=12, tape_color=0x01, text_color=0x08)
    s = parse_status(packet)
    assert len(s.raw) == STATUS_PACKET_SIZE
    assert s.media_width_mm == 12
    assert s.media_type == int(MediaType.LAMINATED_TAPE)
    assert s.has_media
    assert not s.has_error
    assert s.tape_width() == TapeWidth.MM_12


def test_parse_handles_all_tape_widths():
    for tape in TapeWidth:
        packet = build_mock_status(media_width_mm=int(tape))
        s = parse_status(packet)
        assert s.tape_width() == tape


def test_unknown_tape_width_returns_none():
    packet = build_mock_status(media_width_mm=7)  # 7mm isn't a real TZe width
    s = parse_status(packet)
    assert s.tape_width() is None


def test_describe_errors_covers_known_flags():
    packet = build_mock_status(
        error_info_1=int(ErrorInformation1.NO_MEDIA | ErrorInformation1.CUTTER_JAM),
        error_info_2=int(ErrorInformation2.COVER_OPEN),
    )
    s = parse_status(packet)
    msgs = s.describe_errors()
    assert "no media" in msgs
    assert "cutter jam" in msgs
    assert "cover open" in msgs


def test_ensure_tape_matches_accepts_matching_tape():
    s = parse_status(build_mock_status(media_width_mm=12))
    ensure_tape_matches(s, TapeWidth.MM_12)  # does not raise


def test_ensure_tape_matches_rejects_wrong_width():
    s = parse_status(build_mock_status(media_width_mm=24))
    with pytest.raises(TapeMismatchError, match="wrong tape"):
        ensure_tape_matches(s, TapeWidth.MM_12)


def test_ensure_tape_matches_rejects_no_media():
    s = parse_status(build_mock_status(
        media_width_mm=0, media_type=int(MediaType.NO_MEDIA),
    ))
    with pytest.raises(TapeMismatchError, match="no tape"):
        ensure_tape_matches(s, TapeWidth.MM_12)


def test_ensure_tape_matches_surfaces_printer_errors():
    s = parse_status(build_mock_status(
        media_width_mm=12,
        error_info_2=int(ErrorInformation2.OVERHEATING),
    ))
    with pytest.raises(TapeMismatchError, match="overheating"):
        ensure_tape_matches(s, TapeWidth.MM_12)


# --- Transport integration --------------------------------------------------

def test_dryrun_query_status_without_mock_raises(tmp_path):
    t = DryRunTransport(tmp_path / "x.bin")
    with pytest.raises(StatusUnavailable):
        t.query_status()


def test_dryrun_query_status_with_mock_returns_parsed(tmp_path):
    t = mock_dryrun_with_tape(tmp_path / "x.bin", tape_mm=24)
    s = t.query_status()
    assert s.tape_width() == TapeWidth.MM_24


def test_dryrun_is_not_recognised_as_status_aware_by_default(tmp_path):
    # Even though DryRunTransport defines query_status, consumers can check
    # whether it actually has a mock by calling it and catching StatusUnavailable.
    t = DryRunTransport(tmp_path / "x.bin")
    with pytest.raises(StatusUnavailable):
        t.query_status()


def test_mock_status_reports_reply_type_by_default():
    s = parse_status(build_mock_status())
    assert s.status_type == int(StatusType.REPLY_TO_REQUEST)


# --- check_tape_or_warn (shared CLI/service pre-print policy) ---------------

class _Transport:
    """Minimal status-aware transport stub."""
    def __init__(self, *, status=None, exc=None):
        self._status = status
        self._exc = exc

    def query_status(self):
        if self._exc is not None:
            raise self._exc
        return self._status


def test_check_tape_or_warn_returns_none_on_match():
    t = _Transport(status=parse_status(build_mock_status(media_width_mm=12)))
    assert check_tape_or_warn(t, TapeWidth.MM_12) is None


def test_check_tape_or_warn_returns_warning_when_status_unavailable():
    t = _Transport(exc=StatusUnavailable("SNMP disabled"))
    warning = check_tape_or_warn(t, TapeWidth.MM_12)
    assert warning is not None
    assert "12mm" in warning
    assert "SNMP disabled" in warning


def test_check_tape_or_warn_raises_mismatch_on_wrong_tape():
    t = _Transport(status=parse_status(build_mock_status(media_width_mm=24)))
    with pytest.raises(TapeMismatchError, match="wrong tape"):
        check_tape_or_warn(t, TapeWidth.MM_12)


def test_check_tape_or_warn_wraps_unexpected_query_errors():
    t = _Transport(exc=OSError("socket exploded"))
    with pytest.raises(StatusQueryError, match="socket exploded"):
        check_tape_or_warn(t, TapeWidth.MM_12)
