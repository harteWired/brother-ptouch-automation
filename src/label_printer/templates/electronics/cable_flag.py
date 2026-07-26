"""Cable flag — two identical faces with a wrap gap sized to the cable.

Layout per face (left to right inside one face section)::

    ┌──────┬─────────────────────────────┬──────┐
    │      │   TITLE (large, bold)       │      │
    │  IMG │   ─────────────────────     │  QR  │
    │      │   date   detail line(s)     │      │
    └──────┴─────────────────────────────┴──────┘

The full label is ``[face][wrap][face]``. When wrapped around a cable, the
wrap section circles the cable and the two faces stick together back-to-back,
so the flag reads the same whichever side is facing you.

Everything but the title is optional:

* ``title`` directly, or ``source`` + ``dest`` (auto-formats as ``"src → dest"``).
* ``date`` and multi-line ``details`` add a small-print block under the title.
* ``link`` renders a QR flush-right on **each** face (not on the trailing edge).
* ``image`` renders a bitmap flush-left on **each** face — good for a big
  mains/low-voltage / hazard / category symbol.
* ``wire`` sizes the wrap gap (default ``ethernet`` ≈ 5.5 mm OD).

The wrap width is computed from the cable's outer diameter (π·OD plus a
3 mm overlap for adhesive). The template carries ``link`` and ``image``
itself, so ``compose_extras`` is told to leave both alone via
``handles_extras`` — otherwise a trailing-edge copy would also appear.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from label_printer.engine.compose import load_and_fit_image
from label_printer.engine.fonts import pick_font
from label_printer.engine.layout import (
    DEFAULT_BOLD,
    LabelCanvas,
    TwoLineLayout,
    cap_top_offset,
    descender_max,
    draw_dashed_vline,
    draw_text,
    fit_text_to_box,
    mm_to_dots,
    split_lines_to_fit,
    text_width,
)
from label_printer.engine.qr import render_qr
from label_printer.engine.wire import diameter_mm, wrap_length_mm
from label_printer.tape import TapeWidth, geometry_for
from label_printer.templates.base import Template, TemplateField, TemplateMeta

# Fraction of the available face height reserved for the small-print block
# when there are any small lines. Bumped above TwoLineLayout's default 0.28
# because we may have several lines (date + multi-line details), not one
# subtitle.
_SMALL_RATIO = 0.32


def _resolve_title(data: dict) -> str:
    """Title comes either directly from `title`, or from `source`+`dest`."""
    title = data.get("title")
    if title:
        return str(title)
    src = data.get("source")
    dst = data.get("dest")
    if src and dst:
        return f"{src} → {dst}"
    raise ValueError("cable_flag needs either 'title' or both 'source' and 'dest'")


def _detail_lines(data: dict) -> list[str]:
    """Gather the small-print lines: date first (if present), then details."""
    lines: list[str] = []
    date = data.get("date")
    if date:
        lines.append(str(date))
    details = data.get("details")
    if details:
        # Accept both real newlines and literal "\n" escapes (common from CLI / JSON callers).
        normalized = str(details).replace("\\n", "\n")
        for line in normalized.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


class CableFlagTemplate(Template):
    handles_extras = frozenset({"link", "image"})
    meta = TemplateMeta(
        category="electronics",
        name="cable_flag",
        summary=(
            "Cable flag with two identical faces and a cable-sized wrap. "
            "Optional small-print, per-face QR, and per-face image."
        ),
        fields=[
            TemplateField(
                "title",
                "Large text on each face. Omit to use 'source' + 'dest' instead.",
                required=False,
                example="NAS → SW p3",
            ),
            TemplateField(
                "source",
                "Source end. Paired with 'dest' to auto-format the title as 'src → dst'.",
                required=False,
                example="NAS",
            ),
            TemplateField(
                "dest",
                "Destination end. Paired with 'source'.",
                required=False,
                example="SWITCH p3",
            ),
            TemplateField(
                "date",
                "Optional small-print date (ISO 8601 preferred).",
                required=False,
                example="2026-04-25",
            ),
            TemplateField(
                "details",
                "Optional small-print line(s). Use newlines to separate.",
                required=False,
                example="VLAN 20\\npatch A-14",
            ),
            TemplateField(
                "link",
                "Optional QR payload — short-form (vault:, gh:), URL, or any string. "
                "Renders a QR on each face, not on the trailing edge.",
                required=False,
                example="vault:networking/nas-eth0",
            ),
            TemplateField(
                "image",
                "Optional bitmap path. Renders flush-left on each face — good "
                "for a big mains / low-voltage / hazard symbol.",
                required=False,
                example="src/label_printer/icons/lucide/zap.svg",
            ),
            TemplateField(
                "wire",
                "Cable type or gauge — e.g. 'ethernet', 'hdmi', 'usb-c', '18 AWG', '5mm'. "
                "Default: ethernet (5.5mm OD).",
                required=False,
                default="ethernet",
                example="ethernet",
            ),
            TemplateField(
                "overlap_mm",
                "Extra length beyond a full wrap for adhesive-on-adhesive closure.",
                required=False,
                default=3.0,
                example="3.0",
            ),
        ],
        default_tape=TapeWidth.MM_12,
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        resolved = super().validate(data)
        has_title = bool(resolved.get("title"))
        has_pair = bool(resolved.get("source")) and bool(resolved.get("dest"))
        if not (has_title or has_pair):
            raise ValueError(
                f"Template {self.meta.qualified} needs either 'title' or both 'source' and 'dest'"
            )
        return resolved

    def render(self, data: dict, tape: TapeWidth) -> Image.Image:
        title = _resolve_title(data)
        link = data.get("link")
        image_path = data.get("image")
        lines = _detail_lines(data)
        wire_spec = data.get("wire") or "ethernet"
        overlap = float(data.get("overlap_mm") or 3.0)

        geom = geometry_for(tape)
        face_h = geom.print_pins

        # Per-face extras: QR flush-right, bitmap flush-left. Both scaled to
        # full face height; the bitmap preserves aspect ratio (so a wide
        # symbol stays wide).
        qr_img = render_qr(str(link), face_h) if link else None
        face_image = load_and_fit_image(image_path, face_h) if image_path else None
        qr_w = qr_img.width if qr_img else 0
        img_w = face_image.width if face_image else 0
        gap = mm_to_dots(1.5)
        qr_gap = gap if qr_img else 0
        img_gap = gap if face_image else 0

        # Vertical layout: title on top, optional small-print block below.
        # TwoLineLayout gives the padding/gap constants; we size the small
        # block as a *total* (not per-line) because we may have multiple
        # detail lines, not just one subtitle.
        layout = TwoLineLayout(tape=tape, secondary_ratio=_SMALL_RATIO)
        avail = layout.available
        title_y = layout.primary_y
        min_per_line = 8
        min_title_h = 12

        if lines:
            target_block = max(min_per_line * len(lines), layout.secondary_h)
            block_ceiling = max(min_per_line * len(lines), avail - min_title_h - layout.gap)
            small_block_h = min(target_block, block_ceiling)
            small_line_h = max(min_per_line, small_block_h // len(lines))
            if small_line_h * len(lines) > avail - min_title_h - layout.gap:
                small_line_h = max(6, (avail - min_title_h - layout.gap) // len(lines))
            title_h = max(min_title_h, avail - small_line_h * len(lines) - layout.gap)
            small_block_y = title_y + title_h + layout.gap
        else:
            small_line_h = 0
            title_h = avail
            small_block_y = title_y + title_h

        # Initial title sizing — width gets finalised after we know how wide
        # the wrapped small lines are.
        text_area_target = mm_to_dots(55)
        title_font = fit_text_to_box(title, text_area_target, title_h, DEFAULT_BOLD)
        title_w = text_width(title, title_font)

        small_font = pick_font(max(7, small_line_h)) if lines else None

        wrapped_small: list[str] = []
        if small_font:
            width_budget = max(title_w, mm_to_dots(20))
            for line in lines:
                wrapped_small.extend(split_lines_to_fit(line, width_budget, small_font))
            # If wrapping introduced extra lines, the small block grows and
            # the title has to shrink — recompute everything affected.
            if len(wrapped_small) > len(lines):
                n = len(wrapped_small)
                block_ceiling = max(min_per_line * n, avail - min_title_h - layout.gap)
                small_block_h = min(max(min_per_line * n, layout.secondary_h), block_ceiling)
                small_line_h = max(min_per_line, small_block_h // n)
                if small_line_h * n > avail - min_title_h - layout.gap:
                    small_line_h = max(6, (avail - min_title_h - layout.gap) // n)
                small_font = pick_font(max(6, small_line_h))
                title_h = max(min_title_h, avail - small_line_h * n - layout.gap)
                title_font = fit_text_to_box(title, text_area_target, title_h, DEFAULT_BOLD)
                title_w = text_width(title, title_font)
                small_block_y = title_y + title_h + layout.gap

        small_w = (
            max((text_width(line, small_font) for line in wrapped_small), default=0)
            if small_font
            else 0
        )
        text_w = max(title_w, small_w)

        # Face length: side padding + image + text + qr.
        face_text_pad = mm_to_dots(2)
        face_dots = face_text_pad + img_w + img_gap + text_w + qr_gap + qr_w + mm_to_dots(2)
        face_dots = max(face_dots, mm_to_dots(20))

        od = diameter_mm(wire_spec)
        wrap_mm = wrap_length_mm(od, overlap_mm=overlap)
        wrap_dots = mm_to_dots(wrap_mm)

        total = face_dots * 2 + wrap_dots
        canvas = LabelCanvas.create(tape, length_mm=total * 25.4 / 180)

        for face_x in (0, face_dots + wrap_dots):
            if face_image is not None:
                canvas.image.paste(face_image, (face_x + face_text_pad, 0))
            if qr_img is not None:
                canvas.image.paste(qr_img, (face_x + face_dots - qr_w, 0))

            text_x = face_x + face_text_pad + img_w + img_gap

            # Title baseline-anchored to row bottom (minus descender room) so
            # caps fill the row without reserved descent space below them.
            title_baseline = title_y + title_h - descender_max(title_font)
            draw_text(canvas, title, title_font, text_x, title_baseline, anchor="ls")

            if small_font and wrapped_small:
                # First small line cap-top sits flush with small_block_y; each
                # subsequent line advances by small_line_h with the same
                # cap-top offset cancelled out.
                cap_off = cap_top_offset(small_font)
                cursor_y = small_block_y - cap_off
                for line in wrapped_small:
                    draw_text(canvas, line, small_font, text_x, cursor_y, anchor="lt")
                    cursor_y += small_line_h

        # Dashed fold lines at both edges of the wrap section.
        draw_dashed_vline(canvas, face_dots)
        draw_dashed_vline(canvas, face_dots + wrap_dots)
        return canvas.image
