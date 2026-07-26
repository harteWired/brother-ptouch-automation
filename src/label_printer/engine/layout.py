"""Layout helpers for composing labels at 180 DPI.

All geometry is in dots (@180 DPI). Callers can use ``mm_to_dots()`` at the
boundary if they want to think in millimetres.

Sizing uses ``font.getmetrics()`` (ascent + descent) rather than the tight
glyph bbox, so reserving N dots for a line actually gives N dots including
descender space. Drawing uses explicit anchors so positions line up with
the reserved box instead of drifting by the font's internal em padding.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from PIL import Image, ImageDraw, ImageFont

from label_printer.constants import DPI
from label_printer.tape import TapeWidth, geometry_for

# Fonts ship inside the package (src/label_printer/fonts) so they resolve
# identically from a source checkout, an editable install, and an installed
# wheel (e.g. the Docker image). Declared as package-data in pyproject.toml.
FONTS_DIR = Path(__file__).resolve().parents[1] / "fonts"
DEFAULT_FONT = FONTS_DIR / "DejaVuSans.ttf"
DEFAULT_BOLD = FONTS_DIR / "DejaVuSans-Bold.ttf"
DEFAULT_MONO = FONTS_DIR / "DejaVuSansMono.ttf"


def mm_to_dots(mm: float) -> int:
    return int(round(mm * DPI / 25.4))


def dots_to_mm(dots: int) -> float:
    return dots * 25.4 / DPI


@dataclass
class LabelCanvas:
    """A blank label image sized for a given tape width and length.

    Coordinates are dots @180 DPI. Origin is top-left; tape feeds left-to-right
    through the printer, so ``width`` is the label's long axis.
    """

    tape: TapeWidth
    length_dots: int
    image: Image.Image
    draw: ImageDraw.ImageDraw

    @classmethod
    def create(cls, tape: TapeWidth, length_mm: float) -> LabelCanvas:
        geom = geometry_for(tape)
        length_dots = mm_to_dots(length_mm)
        image = Image.new("RGB", (length_dots, geom.print_pins), "white")
        draw = ImageDraw.Draw(image)
        # NOTE: fontmode is no longer pinned globally here. ``draw_text`` sets
        # it per-call based on the chosen font: bitmap (Spleen) and small
        # outline glyphs render aliased ('1'); larger outline glyphs keep
        # antialiasing on ('L'). A blanket fontmode='1' would stairstep big
        # headline text that has plenty of pixels per stem.
        return cls(tape=tape, length_dots=length_dots, image=image, draw=draw)

    @property
    def height_dots(self) -> int:
        return self.image.height


def load_font(path: str | Path | None, size_dots: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path or DEFAULT_FONT), size=size_dots)


def font_line_height(font: ImageFont.FreeTypeFont) -> int:
    """Total vertical space a line of this font occupies (ascent + descent)."""
    ascent, descent = font.getmetrics()
    return ascent + descent


def text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    """Rendered width in dots."""
    return int(font.getlength(text))


def text_size(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """(width, full-line-height) — reserves descender space even for text without descenders."""
    return text_width(text, font), font_line_height(font)


@lru_cache(maxsize=128)
def _measure_ink_cached(path: str, size: int, text: str) -> tuple[int, int]:
    """Cached inner — keyed by (font path, font size, probe text)."""
    from label_printer.engine.fonts import is_bitmap_font

    font = ImageFont.truetype(path, size=size)
    mode = "1" if is_bitmap_font(font) else "L"
    w = max(64, text_width(text, font) + 8)
    h = font_line_height(font) + 16
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    draw.fontmode = mode
    draw.text((2, 0), text, fill=0, font=font, anchor="lt")
    inverted = img.point(lambda p: 255 - p, mode="L")
    bbox = inverted.getbbox()
    if bbox is None:
        return 0, 0
    return bbox[1], bbox[3] - 1


def _measure_ink(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    """Render ``text`` at ``anchor='lt'`` y=0 and return (ink_top, ink_bottom).

    Both values are y offsets in pins from the cell top. This sidesteps the
    inconsistency between how Pillow reports metrics for outline vs bitmap
    fonts: ``font.getmetrics()`` includes accent space above the cap, and
    ``font.getbbox()`` returns the cell (not the ink) for bitmap fonts.
    Direct measurement is the only path that's reliable for both kinds.

    Cached on the (path, size, text) triple — for a given font instance we
    only ever do one render pass per probe string.
    """
    return _measure_ink_cached(str(font.path), font.size, text)


def cap_top_offset(font: ImageFont.FreeTypeFont) -> int:
    """Pixels between cell-top and the top of the cap when drawn at ``anchor='lt'``.

    Outline fonts at large sizes typically return 0 (cap top sits at cell top);
    bitmap fonts (Spleen) reserve 4-6 pins above the cap for accent marks.
    Used by ``draw_cap_top_row`` to shift drawing up by exactly that many pins
    so the visible cap aligns to the row top with no padding.
    """
    return _measure_ink(font, "H")[0]


def descender_max(font: ImageFont.FreeTypeFont) -> int:
    """Pixels the deepest descender extends below the baseline.

    Measured against the worst-case glyphs ``Hpqjy`` so it covers anything a
    headline might throw at us. Cell line-height typically reserves more than
    this (Pillow's font metrics include accent space), so subtracting this
    from a row bottom and baseline-anchoring there is safe.
    """
    _, bottom = _measure_ink(font, "Hpqjy")
    _, h_bottom = _measure_ink(font, "H")
    return max(0, bottom - h_bottom)


def fit_text_to_height(
    text: str, height_dots: int, font_path: str | Path | None = None, max_size: int = 200
) -> ImageFont.FreeTypeFont:
    """Largest font whose full line-height fits within ``height_dots``."""
    lo, hi = 6, max_size
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(font_path, mid)
        if font_line_height(font) <= height_dots:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return load_font(font_path, best)


def fit_text_to_box(
    text: str, box_w: int, box_h: int, font_path: str | Path | None = None, max_size: int = 200
) -> ImageFont.FreeTypeFont:
    """Largest font where text width <= ``box_w`` AND line-height <= ``box_h``."""
    lo, hi = 6, max_size
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(font_path, mid)
        if text_width(text, font) <= box_w and font_line_height(font) <= box_h:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return load_font(font_path, best)


def draw_text(
    canvas: LabelCanvas,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    anchor: str = "lt",
) -> None:
    """Draw text with an explicit anchor and font-aware aliasing policy.

    Default ``anchor='lt'`` means (x, y) is the top-left of the glyph bbox —
    so reserving a row that starts at y=Y draws glyphs starting exactly at Y.

    Coordinates are rounded to integers so callers passing float arithmetic
    (e.g. ``(canvas.length_dots - text_w) / 2``) don't smear a glyph across
    two pixel columns at threshold time.

    Fontmode policy: small outline fonts (cap height ≤ ~14px) and Spleen
    bitmap cuts render with fontmode='1' (no AA) — at 180 DPI sub-pixel AA
    thresholds to inconsistent stems. Larger outline fonts keep AA on
    ('L') so big headlines stay smooth instead of stairstepping.
    """
    canvas.draw.fontmode = _fontmode_for(font)
    canvas.draw.text((int(round(x)), int(round(y))), text, fill="black", font=font, anchor=anchor)


def _fontmode_for(font: ImageFont.FreeTypeFont) -> str:
    """Pick the right ImageDraw.fontmode for a given font.

    * Bitmap fonts (Spleen): '1' — they have no AA to disable, but pinning
      it makes intent explicit and matches what callers expect.
    * Small outline glyphs (cap height ≤ ~14px): '1' — at this size AA-then-
      threshold ruins stem consistency, which is the bug the bitmap pack was
      added to dodge in the first place.
    * Larger outline glyphs: 'L' — full AA, smooth at 18px+ caps.
    """
    # Avoid a circular import at module load.
    from label_printer.engine.fonts import is_bitmap_font

    if is_bitmap_font(font):
        return "1"
    # Outline. ``getbbox('A')`` gives a tight cap-height in pixels.
    cap_h = font.getbbox("A")[3] - font.getbbox("A")[1]
    return "1" if cap_h <= 14 else "L"


def draw_row(
    canvas: LabelCanvas,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int,
    align: str = "center",
) -> None:
    """Draw ``text`` horizontally laid-out on the canvas at vertical offset ``y``.

    ``align`` ∈ {"center", "left", "right"}. Uses anchor-based positioning so
    glyphs start at y exactly, with descenders ending at y + line_height.
    """
    if align == "center":
        x = canvas.length_dots // 2
        anchor = "mt"
    elif align == "right":
        x = canvas.length_dots - 2
        anchor = "rt"
    else:
        x = 2
        anchor = "lt"
    draw_text(canvas, text, font, x, y, anchor)


def draw_baseline_row(
    canvas: LabelCanvas,
    text: str,
    font: ImageFont.FreeTypeFont,
    row_top: int,
    row_h: int,
    align: str = "center",
) -> None:
    """Draw ``text`` so its baseline lands as close to the row bottom as
    descenders allow. Visible bottom of caps lands on ``row_top + row_h - descender_max``;
    descenders extend down into the remaining ``descender_max`` pins.

    This eliminates the "wasted descent" gap below cap-only headlines: where
    ``anchor='lt'`` would leave ~7-9 empty pins below the visible baseline
    (because the glyph cell reserves descender space the text doesn't use),
    baseline anchoring pulls the text straight to the bottom of the row.
    Descenders that *do* exist still fit because we leave ``descender_max``
    pins below the baseline.
    """
    desc = descender_max(font)
    baseline_y = row_top + row_h - desc
    if align == "center":
        x, anchor = canvas.length_dots // 2, "ms"
    elif align == "right":
        x, anchor = canvas.length_dots - 2, "rs"
    else:
        x, anchor = 2, "ls"
    draw_text(canvas, text, font, x, baseline_y, anchor)


def draw_cap_top_row(
    canvas: LabelCanvas,
    text: str,
    font: ImageFont.FreeTypeFont,
    row_top: int,
    align: str = "center",
) -> None:
    """Draw ``text`` so its cap top lands exactly on ``row_top``.

    Counterpart to ``draw_baseline_row``: where that helper pulls headlines
    *down* to remove descent slack, this one pulls subtitles *up* to remove
    cap-top slack. Bitmap (Spleen) cuts in particular reserve 4-6 pins above
    the cap for accent marks; with plain ``anchor='lt'`` those pins show as
    extra gap above the subtitle. Subtracting the measured cap-top offset
    from ``y`` cancels that out exactly.
    """
    cap_off = cap_top_offset(font)
    y = row_top - cap_off
    if align == "center":
        x, anchor = canvas.length_dots // 2, "mt"
    elif align == "right":
        x, anchor = canvas.length_dots - 2, "rt"
    else:
        x, anchor = 2, "lt"
    draw_text(canvas, text, font, x, y, anchor)


def draw_dashed_vline(canvas: LabelCanvas, x: int, dash: int = 4, gap: int = 4) -> None:
    y = 0
    while y < canvas.height_dots:
        canvas.draw.line([(x, y), (x, min(y + dash, canvas.height_dots))], fill="black", width=1)
        y += dash + gap


# Backwards-compatible alias — older code used draw_centered_text(canvas, text, font, y=...)
def draw_centered_text(
    canvas: LabelCanvas,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int | None = None,
    x: int | None = None,
) -> None:
    if y is None:
        y = (canvas.height_dots - font_line_height(font)) // 2
    if x is not None:
        draw_text(canvas, text, font, x, y, anchor="lt")
    else:
        draw_row(canvas, text, font, y, align="center")


def split_lines_to_fit(text: str, width_dots: int, font: ImageFont.FreeTypeFont) -> list[str]:
    """Greedy word-wrap. Long words are kept as-is (may overflow)."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if text_width(candidate, font) <= width_dots:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def render_two_line_label(
    tape: TapeWidth,
    primary: str,
    secondary: str,
    *,
    icon: str | None = None,
    primary_font: str | Path | None = None,
    secondary_font: str | Path | None = None,
    max_width_mm: float = 120.0,
    padding_mm: float = 6.0,
    secondary_ratio: float = 0.37,
) -> Image.Image:
    """Render a bold-on-top, subtitle-below label with optional left-side icon.

    Shared across most template packs. Covers the common case: one headline,
    one subtitle, centered horizontally, optional Lucide icon on the left.
    Templates with unique visual needs (cable flags, PSU polarity icons,
    QR codes) stay bespoke.
    """

    layout = TwoLineLayout(tape=tape, secondary_ratio=secondary_ratio)
    p_font_path = primary_font if primary_font is not None else DEFAULT_BOLD
    s_font_path = secondary_font if secondary_font is not None else DEFAULT_FONT

    p_font = fit_text_to_box(primary, mm_to_dots(max_width_mm), layout.primary_h, p_font_path)
    # Subtitle: at 12mm tape this is ~14-18px, the regime where outline
    # fonts go ragged. Prefer a Spleen bitmap cut if the caller didn't
    # pin a specific font path. Pass ``secondary_h`` directly — the layout
    # has already snapped it to a native bitmap height, so subtracting a
    # safety pad here would just shrink the glyph for no reason.
    if secondary_font is None:
        from label_printer.engine.fonts import pick_font

        s_font = pick_font(layout.secondary_h)
    else:
        s_font = load_font(s_font_path, layout.secondary_h)

    from label_printer.tape import geometry_for

    geom = geometry_for(tape)
    icon_img = None
    icon_offset = 0
    if icon:
        from label_printer.engine.icons import IconEngineUnavailable, load_icon

        try:
            icon_size = geom.print_pins - 4
            icon_img = load_icon(icon, icon_size)
            icon_offset = icon_size + mm_to_dots(2)
        except IconEngineUnavailable as e:
            raise ValueError(str(e)) from e

    text_w = max(text_width(primary, p_font), text_width(secondary, s_font))
    length_dots = icon_offset + text_w + mm_to_dots(padding_mm)
    canvas = LabelCanvas.create(tape, length_mm=length_dots * 25.4 / 180)

    if icon_img is not None:
        canvas.image.paste(icon_img, (mm_to_dots(1), 2))

    if icon_offset:
        # Manual horizontal centering inside the icon-offset region.
        for text, font, row_top, row_h, baseline_anchor in (
            (primary, p_font, layout.primary_y, layout.primary_h, True),
            (secondary, s_font, layout.secondary_y, layout.secondary_h, False),
        ):
            w = text_width(text, font)
            x = icon_offset + (canvas.length_dots - icon_offset - w) // 2
            if baseline_anchor:
                desc = descender_max(font)
                draw_text(canvas, text, font, x, row_top + row_h - desc, anchor="ls")
            else:
                draw_text(canvas, text, font, x, row_top - cap_top_offset(font), anchor="lt")
    else:
        draw_baseline_row(canvas, primary, p_font, layout.primary_y, layout.primary_h)
        draw_cap_top_row(canvas, secondary, s_font, layout.secondary_y)
    return canvas.image


@dataclass(frozen=True)
class TwoLineLayout:
    """Vertical layout for a common 'big line on top, small line on bottom' label.

    For a 70-pin (12mm) tape with defaults this snaps the secondary row to a
    Spleen-native height so the small line fills the row instead of leaving
    pixels empty:

        pad_top=1, primary=42, gap=2, secondary=24, pad_bottom=1  → 70
                                       ^^                       Spleen 12x24

    The default ``secondary_ratio`` of 0.37 lands the snap on Spleen 12x24
    at 12mm tape and on Spleen 16x32 at 24mm tape — a 50% cap-height bump
    over the previous 8x16 / 12x24 pairing, in response to v2 print samples
    where the subtitle was the line begging for more pixels.
    """

    tape: TapeWidth
    pad_top: int = 1
    gap: int = 2
    pad_bottom: int = 1
    secondary_ratio: float = 0.37  # fraction of available height for the small line

    # Native cap heights of the bundled Spleen cuts. Any "snap" ends up at
    # one of these so the bitmap glyph fills its row exactly. Declared as a
    # ClassVar so dataclass treats it as class-level state, not a field.
    _SPLEEN_NATIVE: ClassVar[tuple[int, ...]] = (12, 16, 24, 32)

    @property
    def available(self) -> int:
        return geometry_for(self.tape).print_pins - self.pad_top - self.gap - self.pad_bottom

    @property
    def secondary_h(self) -> int:
        """Reserved height for the small line, snapped to a Spleen native size.

        We pick the largest Spleen native size ≤ ``available * ratio`` (and
        ≥ 12, the smallest cut). This way ``pick_font`` can hit the bitmap
        exactly with zero wasted pixels — the fix for the previous "after"
        being visibly smaller than "before".
        """
        target = max(12, int(self.available * self.secondary_ratio))
        chosen = self._SPLEEN_NATIVE[0]
        for native in self._SPLEEN_NATIVE:
            # Cap at 40% of available so we never starve the headline.
            if native <= target and native <= self.available * 0.45:
                chosen = native
        return chosen

    @property
    def primary_h(self) -> int:
        return self.available - self.secondary_h

    @property
    def primary_y(self) -> int:
        return self.pad_top

    @property
    def secondary_y(self) -> int:
        return self.pad_top + self.primary_h + self.gap
