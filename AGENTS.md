# Label Printer

## Overview
Automation flow for generating labels on a Brother PT-P750W (primary target; PT-P710BT "Cube Plus" and PT-E550W also supported via the same raster command set). Produces a diversity of label styles — kitchen, electronics, 3D printing, general household — from a single Python engine, callable by humans (CLI) and by other projects (Claude Code skill, Telegram channel, life-planner, etc.). The printer stays connected to one machine (currently this PC, possibly a server later); clients talk to a local print service.

## Tech Stack
- Language: Python 3.11+
- Imaging: Pillow (PIL) for label composition → monochrome raster
- Printer protocol: Brother Raster Command Reference (official spec for PT-E550W / PT-P750W / PT-P710BT)
- Transport: USB (primary) + Bluetooth SPP (secondary, for wireless fallback)
- Library choice: start from `treideme/brother_pt` (Python, explicit PT-P710BT support) as the reference implementation; vendor/fork if we need changes
- Package manager: uv (or pip + venv — match cli-anything-* sibling projects)
- CLI framework: Click (matches cli-anything-openscad / cli-anything-obsidian)
- Skill: installed at `~/.claude/skills/label-printer/` via symlink, same pattern as prompt-master

## Hardware Facts (pin these)
- Primary printer: **Brother PT-P750W** (chosen over the PT-P710BT for half-cut support and Wi-Fi)
- Compatible: PT-P710BT, PT-E550W (same raster command reference, same 128-pin head — code is identical)
- Print resolution: 180 DPI
- Print head width: 128 pins → usable print area ~18mm tall at max
- Supported TZe tape widths: 3.5, 6, 9, 12, 18, 24 mm (laminated TZe tapes only)
- User stocks **12mm and 24mm** — default templates to 12mm
- Max label length: ~500 mm per print
- Print speed: ~20 mm/s
- Half-cut: **supported on P750W** (separates labels without severing liner); silently ignored on P710BT
- Connectivity: USB + Wi-Fi on P750W (no built-in Bluetooth). Not connected on this machine yet — first-time driver + pairing step is part of Phase 5.

## Commands
```bash
# Planned — not yet implemented:
# uv sync                    - Install deps into local venv
# lp render <template> ...   - Render a label to PNG without printing
# lp print <template> ...    - Render + send to printer
# lp scan                    - Discover USB / BT printers
# lp tape <width>            - Declare current tape width (persisted)
# pytest                     - Run test suite
```

## Conventions
- Snake_case for Python (per root CLAUDE.md).
- **Keep the renderer pure**: templates produce a Pillow `Image` given structured input; the transport layer takes images and sends bytes. No rendering in the transport code.
- **No printer mocks in integration tests**: use the real raster bytes stream into a byte buffer and diff against a golden. Only mock the USB/BT write at the very last step. (Mirrors the "don't mock the database" feedback rule.)
- **Template = data + layout**, not prose. Templates are declared as Python dataclasses or YAML schemas, rendered by a shared layout engine. Adding a new label type should not require touching transport code.
- Label types live under `templates/<category>/` with a manifest the CLI discovers at startup. Treat the category directories (kitchen, electronics, three_d_printing) as plugin dirs.
- All label designs must target **180 DPI** exactly — no scaling surprises at print time.
- Never commit generated label PNGs outside `tests/golden/`.

## Project Structure
```
label-printer/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── src/label_printer/
│   ├── engine/                 # Pillow-based layout + raster conversion
│   ├── transport/              # Network (TCP:9100) raster command senders
│   ├── templates/              # Template registry + packs (presets.toml per category)
│   ├── fonts/                  # Bundled fonts (package-data — ships in the wheel)
│   ├── icons/                  # Bundled Lucide icon set (package-data)
│   └── cli.py                  # Click CLI entrypoint ("lp")
├── containers/                 # One folder per Docker image (brother-ptouch-automation)
├── research/
│   ├── brother-raster-protocol.md
│   └── sdk-comparison.md
├── docs/sessions/              # Session logs (per workspace convention)
└── tests/
    └── golden/                 # Byte-exact raster-encoder snapshots
```

Runtime resources (templates, fonts, icons) live **inside** the package so
they resolve identically from a source checkout, an editable install, and an
installed wheel — `pip install .` and the Docker image both get them via
`package-data` in pyproject.toml. Do not move them back to a repo-root
`assets/` dir: paths resolved relative to the repo root break in installed
packages.

## When Working Here
1. Read this file + the implementation plan at `obsidian-vault/vault/projects/label-printer/implementation-plan.md`.
2. Confirm current phase before starting a task (the plan is the source of truth, not memory).
3. For any code that touches the printer: render to a PNG first and eyeball it before sending bytes. 180 DPI matters.
4. When adding a template, cover it in `tests/test_templates.py` so it renders + encodes at 12mm and 24mm. Per-template visual goldens are not required — templates may shift visually as the renderer evolves. `tests/golden/` pins the raster encoder, not per-template layout.
5. When this project becomes a skill, verify Telegram-channel can call it end-to-end before closing the phase.

## Future integrations
- Chat / messaging client — once the skill is published, any Claude Code session can call it, including from a Telegram→Claude bridge.
- Inventory systems — any external system with a list of things to label can call the HTTP service at `/print` with a template + fields.
- Secret-manager integration — only relevant once we ever push to a remote / cloud queue; local service keeps `LABEL_PRINTER_TOKEN` in env for now.
