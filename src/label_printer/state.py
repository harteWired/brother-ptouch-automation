"""Persisted user state: last-selected tape, last transport."""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from label_printer.tape import TapeWidth

_CONFIG_DIR = Path(
    os.environ.get("LABEL_PRINTER_CONFIG_DIR")
    or (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "label-printer")
)
_STATE_FILE = _CONFIG_DIR / "state.toml"


@dataclass
class State:
    tape_mm: int = 12
    printer_host: str | None = None

    def tape(self) -> TapeWidth:
        return TapeWidth(self.tape_mm if self.tape_mm != 3 else 4)


def load() -> State:
    if not _STATE_FILE.exists():
        return State()
    with _STATE_FILE.open("rb") as f:
        data = tomllib.load(f)
    return State(**{k: v for k, v in data.items() if k in State.__dataclass_fields__})


def resolve_printer_host() -> str | None:
    """Resolve the configured printer host: LABEL_PRINTER_HOST env → saved state.

    Returns None when nothing is configured. A corrupt or unreadable state
    file is treated as "no saved host" rather than raising, so callers
    (liveness probes, host resolution) stay robust in the face of a bad
    ``state.toml``.
    """
    env_host = os.environ.get("LABEL_PRINTER_HOST")
    if env_host:
        return env_host
    try:
        return load().printer_host
    except Exception:
        return None


def save(state: State) -> Path:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # TOML has no null — omit None fields so the file stays parseable.
    lines = [f"{k} = {v!r}" for k, v in asdict(state).items() if v is not None]
    _STATE_FILE.write_text("\n".join(lines) + "\n")
    return _STATE_FILE
