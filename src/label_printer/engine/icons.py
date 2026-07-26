"""Icon loading and rendering for labels.

Icons are an optional feature. The base install ships a small curated set
of line-art icons from `Lucide <https://lucide.dev/>`_ bundled inside the
package under ``label_printer/icons/lucide/``. Heavier sets (full Lucide,
Material Design Icons) can be installed on demand into
``~/.config/label-printer/icons/`` via the ``lp icons install-*`` CLI commands.

Rendering requires ``cairosvg`` — install via ``pip install label-printer[icons]``.
Without that extra, icon lookups raise ``IconEngineUnavailable`` so templates
that reference icons fail loudly rather than silently emitting blank labels.

Lookup precedence (highest first):

1. Directories listed in ``LABEL_PRINTER_ICON_PATH`` (``:``-separated).
2. ``~/.config/label-printer/icons/<source>/`` for each known source.
3. Bundled ``label_printer/icons/<source>/`` inside the installed package.

Names can be bare (``wifi``) — first match across sources wins — or
namespaced (``lucide:wifi``, ``mdi:wifi``) — only that source is consulted.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

try:
    import cairosvg
    _CAIROSVG_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised in test via monkeypatch
    _CAIROSVG_AVAILABLE = False

# Bundled icons ship inside the package (src/label_printer/icons) so they
# resolve identically from a source checkout, an editable install, and an
# installed wheel (e.g. the Docker image). Declared as package-data.
_BUNDLED_ROOT = Path(__file__).resolve().parents[1] / "icons"
_USER_ROOT = Path(
    os.environ.get("LABEL_PRINTER_ICON_HOME")
    or (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "label-printer" / "icons")
)

# Known icon "sources" — each maps to a subdirectory under the bundled /
# user icon roots. Additional sources can be registered at runtime.
DEFAULT_SOURCES: tuple[str, ...] = ("lucide", "mdi")


class IconEngineUnavailable(RuntimeError):
    """Raised when an icon is requested but cairosvg is not installed."""


class IconNotFoundError(KeyError):
    """Raised when a named icon cannot be found in any registered source."""


@dataclass
class IconRegistry:
    """Resolves icon names to SVG paths across a searchable set of sources."""

    sources: tuple[str, ...] = DEFAULT_SOURCES
    extra_paths: tuple[Path, ...] = field(default_factory=tuple)

    def _env_paths(self) -> list[Path]:
        raw = os.environ.get("LABEL_PRINTER_ICON_PATH", "")
        return [Path(p).expanduser() for p in raw.split(":") if p.strip()]

    def _search_roots(self) -> list[Path]:
        return [*self.extra_paths, *self._env_paths(), _USER_ROOT, _BUNDLED_ROOT]

    def _iter_candidate_dirs(self, source_hint: str | None) -> list[Path]:
        sources = (source_hint,) if source_hint else self.sources
        dirs: list[Path] = []
        for root in self._search_roots():
            for src in sources:
                candidate = root / src
                if candidate.is_dir():
                    dirs.append(candidate)
        return dirs

    def find(self, name: str) -> Path:
        source_hint, _, bare_name = name.rpartition(":")
        source_hint = source_hint or None

        for d in self._iter_candidate_dirs(source_hint):
            svg = d / f"{bare_name}.svg"
            if svg.is_file():
                return svg
        raise IconNotFoundError(
            f"icon {name!r} not found in any of: "
            f"{[str(p) for p in self._search_roots()]}"
        )

    def available(self, source_hint: str | None = None) -> list[str]:
        """List icon names found across the registered sources.

        Names are returned unique, sorted, with their source prefix (e.g.
        ``lucide:wifi``) so ambiguous names can be disambiguated by callers.
        """
        seen: set[str] = set()
        results: list[str] = []
        for root in self._search_roots():
            sources = (source_hint,) if source_hint else self.sources
            for src in sources:
                d = root / src
                if not d.is_dir():
                    continue
                for svg in sorted(d.glob("*.svg")):
                    qualified = f"{src}:{svg.stem}"
                    if qualified not in seen:
                        seen.add(qualified)
                        results.append(qualified)
        return results


_DEFAULT_REGISTRY = IconRegistry()


def registry() -> IconRegistry:
    return _DEFAULT_REGISTRY


def load_icon(name: str, size_dots: int, *, threshold: int = 128) -> Image.Image:
    """Render an icon SVG to a monochrome PIL image.

    ``size_dots`` is the square pixel size. Lucide icons look sharpest when
    ``size_dots`` is a multiple of 24 (their native viewBox), but any size
    works.
    """
    if not _CAIROSVG_AVAILABLE:
        raise IconEngineUnavailable(
            "cairosvg is not installed. Run: pip install 'label-printer[icons]'"
        )

    svg_path = _DEFAULT_REGISTRY.find(name)
    png_bytes = cairosvg.svg2png(
        url=str(svg_path),
        output_width=size_dots,
        output_height=size_dots,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    # Flatten alpha over white, then threshold to 1-bit.
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[-1])
    gray = bg.convert("L")
    return gray.point(lambda v: 0 if v < threshold else 255, mode="1").convert("RGB")


def has_engine() -> bool:
    """True when icon rendering is available (cairosvg importable)."""
    return _CAIROSVG_AVAILABLE


USER_ROOT = _USER_ROOT  # re-exported for CLI install commands
BUNDLED_ROOT = _BUNDLED_ROOT
