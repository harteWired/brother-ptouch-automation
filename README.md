# brother-ptouch-automation

[![CI](https://img.shields.io/github/actions/workflow/status/harteWired/brother-ptouch-automation/ci.yml?branch=main&label=ci&style=flat)](https://github.com/harteWired/brother-ptouch-automation/actions/workflows/ci.yml) [![license](https://img.shields.io/github/license/harteWired/brother-ptouch-automation?style=flat)](LICENSE) [![live demo](https://img.shields.io/badge/live%20demo-36%20templates-2ea44f?style=flat&logo=github)](https://harteWired.github.io/brother-ptouch-automation/) [![by harteWired](https://img.shields.io/badge/by-harteWired-e6a562?style=flat&labelColor=15151e)](https://github.com/harteWired)

**A small, flexible label engine** for the Brother **PT-P750W** (primary target; PT-P710BT and PT-E550W also work). One byte-exact raster core, one layout engine, a tiny TOML preset format for declaring new label types, and a QR / image decorator that snaps onto *any* label — all driveable from a CLI, an HTTP service, or a Claude Code skill.

Adding a new label category is usually ~10 lines of TOML, not a Python class. Adding a QR code or an inline image to an existing label is a flag, not a new template. The fiddly stuff (cable-flag wrap geometry, polarity icons, GHS hazard symbols) stays in Python where it belongs; everything else is data.

<p align="center">
  <img src="docs/previews/kitchen_pantry_jar_with_icon_12mm.png" alt="Kitchen pantry-jar label with wheat icon — 12 mm tape">
  <img src="docs/previews/utility_qr_12mm.png" alt="Utility QR-code label with caption — 12 mm tape">
  <img src="docs/previews/three_d_printing_filament_spool_12mm.png" alt="3D-printing filament-spool label — 12 mm tape">
  <img src="docs/previews/electronics_cable_flag_12mm.png" alt="Electronics cable-flag label — 12 mm tape">
</p>

> [!TIP]
> The full catalog — all 36 templates across 12 packs, with search, field schemas, and copy-paste CLI examples — is at the **[live demo site](https://harteWired.github.io/brother-ptouch-automation/)**.

## How it composes

The system is deliberately small. Four things, layered:

1. **The raster engine.** Byte-exact against Brother's official command reference, cross-checked against [`treideme/brother_pt`](https://github.com/treideme/brother_pt) in CI. Handles every TZe width (3.5 / 6 / 9 / 12 / 18 / 24 mm), half-cut, multi-label batches with `0x0C` separators, and 32-byte status parsing so real sends can be gated on "the loaded tape matches the job."
2. **The layout helpers.** `render_two_line_label`, `TwoLineLayout`, `fit_text_to_box`, icon placement, QR composition — a handful of pure functions that compose a `Pillow.Image` at 180 DPI for a given tape width.
3. **TOML presets.** ~30 of the shipped labels are declarative data: a `qualified` name, a schema, a primary / secondary line template, some optional conditionals. Adding a new one is an entry in a pack's `presets.toml` — no Python required. See [`docs/creating-a-preset.md`](docs/creating-a-preset.md).
4. **Bespoke Python templates** for the few that need custom geometry — `electronics/cable_flag` (wire-OD-sized wrap section), `electronics/psu_polarity` (polarity icon), `workshop/hazard` (GHS pictograms), `utility/qr` / `utility/image`. These stay as classes so they can break out of the preset shape when they genuinely need to.

Cross-cutting things — QR codes, arbitrary bitmaps — are **decorators** that snap onto any template via `--link` and `--image`, so they never have to be copy-pasted into each label. The whole library is 36 labels, but the engine treats new labels as cheap.

## Why

The Brother P-touch Editor app is fine for a one-off, but it's terrible at the workflows you actually want:

- Labelling ten jars in a row without clicking through a GUI every time
- Printing from a script, a scheduled job, or a chatbot
- Sharing a template library across projects
- Getting the *same* label twice in a row, reliably
- Reusing 90% of the design when you add a new label category

Templates have validated field schemas, dry-run is the default, and the three surfaces (CLI, HTTP service, Claude Code skill) all call the same engine — a label triggered from Claude comes off the tape identical to one triggered from the shell.

### Highlights

- **Dry-run by default.** `lp print` and `lp batch` encode + write bytes to a file but never drive the transport unless you add `--send`. The printer never moves unexpectedly.
- **Wire-aware cable flags.** Pass `wire=ethernet` or `wire=18AWG` and the wrap section is sized to the cable's outer diameter (π·OD + adhesive overlap); 40+ keywords plus AWG 0–30 built in.
- **Icons, opt-in.** ~50 curated Lucide icons bundled; full Lucide (~1500) or Material Design Icons (~7000) sets install with `lp icons install-lucide` / `lp icons install-mdi`.
- **Pack plug-in system.** Ship your own templates as a separate pip package via standard entry points; broken packs are isolated and a safe-mode env var disables them wholesale. See [`docs/creating-a-pack.md`](docs/creating-a-pack.md).
- **180+ tests**, ruff clean, CI green on every push.

## Architecture

![Architecture — three client surfaces (lp CLI, /label-printer Claude Code skill, HTTP service) all feed the template registry inside the engine. Registry routes to template.render (→ Pillow Image), then the raster encoder (128-pin aligned, TIFF-PackBits, half-cut, chaining), which sends bytes through one of three transports (DryRunTransport default, USB and Bluetooth SPP coming in phase 5). USB and Bluetooth query the status parser as a tape-match gate before encoding. The PT-P750W on the right is the primary printer (180 DPI, 128 pins, half-cut).](./docs/images/lp-architecture.png)

**Key separation**: templates produce a Pillow `Image` sized for the loaded tape; the engine converts it to a Brother raster command stream; transports only care about `send(bytes)`. Clients never touch transport code. Swapping from a local printer to a network service or migrating to a different host is zero-template-change work.

## Template gallery

**36 templates across 12 packs** — kitchen, electronics, 3D printing, utility, garden, networking, workshop, home-inventory, media, pet, travel, calibration. The README shows a small sample; the [live demo site](https://harteWired.github.io/brother-ptouch-automation/) has every template with rendered previews, field schemas, and copy-paste CLI examples.

| Pack | Template | Preview |
|---|---|---|
| `kitchen/` | `pantry_jar` (with icon) | ![](docs/previews/kitchen_pantry_jar_with_icon_12mm.png) |
| `electronics/` | `cable_flag` (wrap sized to the cable) | ![](docs/previews/electronics_cable_flag_12mm.png) |
| `three_d_printing/` | `filament_spool` | ![](docs/previews/three_d_printing_filament_spool_12mm.png) |
| `utility/` | `qr` | ![](docs/previews/utility_qr_12mm.png) |

### Wire-aware cable flags

Pass the cable type as plain language and the wrap section (the part that goes around the cable) is sized from its outer diameter:

| `wire=` | OD | Preview |
|---|---|---|
| `24AWG` (hookup wire) | 1.4 mm | ![](docs/previews/electronics_cable_flag_thin-24awg_12mm.png) |
| `ethernet` (Cat6 patch) | 5.5 mm | ![](docs/previews/electronics_cable_flag_12mm.png) |
| `extension-cord` | 10.0 mm | ![](docs/previews/electronics_cable_flag_thick-extension_12mm.png) |

Supported out of the box: `ethernet`, `cat5/5e/6/6a/7/8`, `coax`, `hdmi`, `displayport`, `usb/usb-c/micro-usb`, `lightning`, `thunderbolt`, `ac`, `iec-c13`, `extension-cord`, `lamp-cord`, `xlr`, `trs`, `rca`, `sata`, `molex`, `jst`, `dupont`, `romex-12/14/10`, AWG 0–30, or a literal `"5mm"`. Run `lp wires` for the full list.

## Quickstart

```bash
git clone https://github.com/harteWired/brother-ptouch-automation.git
cd brother-ptouch-automation
python3.11 -m venv .venv
.venv/bin/pip install -e '.[barcode,service,icons]'

# Discover what's shipped
.venv/bin/lp packs            # installed template packs (built-in + entry-point)
.venv/bin/lp list             # all templates
.venv/bin/lp show kitchen/pantry_jar

# Dry-render a PNG + raster command stream (no printing)
.venv/bin/lp render kitchen/pantry_jar \
  -f name="AP Flour" -f purchased=2026-04-19 \
  --png-out flour.png --bin-out flour.bin

# Pantry jar with an icon (opt-in; icons extra pulls cairosvg)
# wheat for flour, egg for eggs, leaf for herbs, carrot for root veg — pick what fits
.venv/bin/lp render kitchen/pantry_jar \
  -f name="AP Flour" -f purchased=2026-04-19 -f icon=wheat \
  --png-out flour-with-icon.png

# QR code with caption
.venv/bin/lp render utility/qr \
  -f data=https://github.com/harteWired/brother-ptouch-automation \
  -f caption=repo \
  --png-out qr.png

# Cable flag, auto-sized for the cable
.venv/bin/lp render electronics/cable_flag \
  -f source=NAS -f dest="SWITCH p3" -f wire=ethernet \
  --png-out cable.png

# Batch-print a whole spice rack as one chained job (half-cut between each)
cat > rack.json <<EOF
[
  {"template": "kitchen/spice", "tape_mm": 12, "fields": {"name": "Paprika"}},
  {"template": "kitchen/spice", "tape_mm": 12, "fields": {"name": "Cumin"}},
  {"template": "kitchen/spice", "tape_mm": 12, "fields": {"name": "Oregano"}}
]
EOF
.venv/bin/lp batch rack.json

# When hardware lands: verify the right tape is loaded, then actually print
.venv/bin/lp status           # parses the printer's status packet
.venv/bin/lp batch rack.json --send
```

## Three surfaces

### CLI

```bash
# discover
lp packs                               # installed template packs
lp list [--category kitchen]           # templates in a pack
lp show <category>/<name>              # field schema for a template
lp tape-info                           # print-head geometry per tape
lp wires                               # cable-keyword → outer-diameter table
lp icons list [--source]               # bundled Lucide icons

# render (safe — no transport touched)
lp render <template> -f k=v ...        # PNG + raster preview
lp render-image <file.png>             # raster-encode an arbitrary image

# print — dry-run default, --send opt-in
lp print <template> -f k=v ...         # single label
lp print <template> -f k=v ... --send  # really print
lp batch <spec.json>                   # chained multi-label job (half-cut)
lp batch <spec.json> --send            # ditto, send for real

# hardware (Wi-Fi)
lp printer set <ip>                    # persist printer host/IP
lp status                              # loaded tape + error flags (via SNMP)
lp scan                                # probe whether the printer accepts connections

# config
lp tape <mm>                           # persist current tape width
lp icons install-lucide                # clone ~1500 Lucide icons to ~/.config
lp icons install-mdi                   # clone ~7000 Material Design Icons

# service
lp serve --host 127.0.0.1 --port 8765  # FastAPI HTTP service
```

`lp print` and `lp batch` are **dry-run by default** — they encode the job and write the raster command stream to `--bin-out`, but never touch the printer. Add `--send` to actually drive the transport. The HTTP service mirrors the same contract: `POST /print` is dry-run by default, set `"send": true` in the body to drive the transport.

### HTTP service

```bash
export LABEL_PRINTER_TOKEN=s3cret     # optional bearer-token auth
export LABEL_PRINTER_HOST=192.168.1.50  # printer IP for send:true (or `lp printer set`)
lp serve --host 127.0.0.1 --port 8765
```

```bash
curl -s http://127.0.0.1:8765/templates | jq .

# Render returns a PNG
curl -X POST http://127.0.0.1:8765/render \
  -H 'Authorization: Bearer s3cret' \
  -H 'Content-Type: application/json' \
  -d '{"template":"utility/qr","tape_mm":12,"fields":{"data":"https://example.com","caption":"site"}}' \
  --output qr.png

# Print — dry-run returns the raster bytes; set send:true to drive the transport
curl -X POST http://127.0.0.1:8765/print \
  -H 'Content-Type: application/json' \
  -d '{"template":"kitchen/spice","tape_mm":12,"fields":{"name":"Paprika"},"send":true}'
```

Endpoints: `GET /health`, `GET /templates`, `POST /render`, `POST /print`.

`POST /print` with `"send": true` resolves the printer host the same way the CLI does — `LABEL_PRINTER_HOST` env var first, then the value persisted by `lp printer set <ip>`. Before sending, the service queries the printer over SNMP and returns `409` if the loaded tape width doesn't match `tape_mm` (if SNMP is disabled on the printer, the check is skipped and the response carries a `warning` field). Transport failures return `502`; a missing printer host returns `503`.

#### Docker

Container images are defined in `containers/<name>/` — one folder per image. Each build publishes `ghcr.io/<owner>/<name>` (`:latest` plus an auto-incremented `:X.Y.Z`). Versions are tracked per container by `<name>-vX.Y.Z` git tags rather than VERSION files — each folder has its own independent version line, and a new folder starts at `0.0.1`.

**What triggers a build:**

| Trigger | What gets built |
|---|---|
| Push to `main` touching `containers/<name>/**` | Just that container |
| Push to `main` touching `src/**` or `pyproject.toml` | **All** containers — the images bake in the Python package, so a source change affects every image |
| Manual: Actions → `docker-build` → Run workflow | One named container, or all (default) |
| Weekly schedule (Sun 03:17 UTC) | All containers — picks up base-image (`python:slim`) security patches and apt updates even when the repo is quiet |

The label-printer image runs `lp serve --host 0.0.0.0 --port 8765` as a non-root user:

```bash
docker run -p 8765:8765 \
  -e LABEL_PRINTER_HOST=192.168.1.50 \
  -e LABEL_PRINTER_TOKEN=s3cret \
  ghcr.io/<owner>/brother-ptouch-automation:latest
```

To persist CLI state (e.g. `lp printer set`) across restarts, mount a volume at `/home/labelprinter/.config/label-printer`.

### Claude Code skill

The `skill/` directory is a Claude Code skill. Symlink it into `~/.claude/skills/label-printer/` and Claude sessions can print labels:

```bash
ln -s "$(pwd)/skill" ~/.claude/skills/label-printer
```

From any Claude session:

> "label this jar — sriracha, opened 2026-04-10"

Claude picks the right template, proposes fields, dry-renders a PNG for you to review, and only prints once you approve.

## Job lifecycle

![Print-a-label sequence — 16 numbered messages across User, /label-printer skill, Registry, Engine, Transport, and PT-P750W. Skill resolves template via Registry, gets PNG preview from Engine, asks user to confirm, queries printer status (ESC i S → 32-byte packet), encodes the job, sends raster bytes (ESC @, init, raster, 1A), and the printer hands the label to the user. Amber arrows are forward requests; teal dashed arrows are responses.](./docs/images/lp-print-sequence.png)

## Multi-label batch workflow

![Batch print flow — spec.json holding [label1, label2, …] enters the lp batch command, validates that every label uses the same tape width, renders each to a Pillow Image, then encode_batch emits a session prologue once followed by per-page commands (print_information + mode + advanced + margin + compression + raster + 0x0C next-page) repeated for each label. The last page appends 0x1A (print & feed). The PT-P750W produces one continuous strip with half-cuts between labels.](./docs/images/lp-batch-flow.png)

> [!NOTE]
> The cut command sequence is more subtle than the Brother Raster Command Reference's example would suggest — auto-cut on the Mode byte forces full cuts between every page in a chain, and the canonical "half-cut between, full cut at end" pattern requires a specific byte layout we discovered empirically. See [Cutting and batches — what actually works](./docs/cutting-and-batches.md) if you're touching the encoder, adding a new transport, or wondering why the obvious-from-the-spec answer doesn't work.

## How a single label is encoded

![Render pipeline — Template.render produces a tape-sized Pillow Image, converted to monochrome (threshold 128), fit-checked against tape dimensions, then packed into 128-pin MSB-first raster bytes. Each 16-byte line branches: all-zero lines collapse to a single 0x5A Z-shortcut; non-zero lines get 0x47 + length + PackBits (TIFF-style compression). Both paths merge into the command stream, which is wrapped in the prologue (init · mode · info · margin) and terminated with 0x1A (print & feed). Amber accents on entry, branch, and final output; teal highlights the Z-shortcut shortcut path.](./docs/images/lp-render-pipeline.png)

## QR codes and bitmaps on any template

Two global options — `--link` and `--image` — compose onto the right edge of *any* template's output, so you do not need a QR-specific template per category. `--link` takes a short-form (`vault:...`, `gh:...`), a URL, or any opaque string, and renders it as a QR sized to tape height. `--image` takes a path to a bitmap and fits it to tape height (monochrome, aspect preserved).

```bash
# Pantry label plus a QR that Claude can later resolve to the vault note
lp render kitchen/spice -f name="Smoked Paprika" -f best_by=2027-03 \
  --link vault:kitchen/spices/paprika --png-out preview.png

# Tool tag with a personal logo on the right
lp render three_d_printing/tool_tag -f tool="Calipers" \
  --image ~/assets/logo.png --png-out preview.png
```

Templates that render their own QR / image (`utility/qr`, `utility/image`, `electronics/cable_flag` — which puts both on **each** face inside the wrap geometry) declare `handles_extras = {…}` and silently absorb the matching flag instead of letting `compose_extras` tack a copy onto the trailing edge.

## Extending it

### Add a new label — the usual path (TOML preset)

Two-line labels — which covers most of what people actually print — are declarative data, not Python. Add an entry to a pack's `presets.toml`:

```toml
[[presets]]
qualified = "garden/seed_packet"
summary   = "Seed packet: variety + sow-by date + optional year."
layout    = "two_line"
icon_field = "icon"
primary   = "{variety}"
secondary = [
  { if = "year", text = "{year} · " },
  "sow by {sow_by}",
]

[[presets.fields]]
name = "variety"
required = true
example = "Brandywine tomato"

[[presets.fields]]
name = "sow_by"
required = true
example = "2026-05-15"

[[presets.fields]]
name = "year"
required = false
example = "2025"

[[presets.fields]]
name = "icon"
required = false
example = "sprout"
```

That's it — the preset loader picks it up at registry init, `lp list` shows it, `lp show garden/seed_packet` prints the schema, and `lp render garden/seed_packet ...` produces a label. Want a QR next to it? `--link vault:garden/tomatoes/brandywine`. An arbitrary bitmap? `--image path/to/photo.png`. Neither of those requires touching the preset.

The preset format supports a primary line, a secondary line (optionally joined with a separator), conditional fragments (`if` / `if_all` / `if_any`), a derived date-offset field (leftovers compute their eat-by date this way), and an optional icon field. See [`docs/creating-a-preset.md`](docs/creating-a-preset.md) for the full schema.

### Add a bespoke Python template

When a label genuinely needs custom geometry — cable flags that wrap around a cable, polarity icons, GHS hazard pictograms — write it as a Python class that inherits `Template` and lives alongside the preset entries in the same pack. The pack's `__init__.py` includes it in `PACK.templates` next to the loaded presets. Five such templates ship today out of 36 total.

### Ship a whole pack as a separate pip package

Your users can `pip install label-printer-ham-radio` and get your templates alongside the built-ins. The pack registers via standard Python entry points:

```toml
# In your package's pyproject.toml
[project.entry-points."label_printer.packs"]
ham_radio = "label_printer_ham:PACK"
```

Full walkthrough in [`docs/creating-a-pack.md`](docs/creating-a-pack.md). The doc also covers the trust model, collision rules, and the `LABEL_PRINTER_DISABLE_ENTRY_POINT_PACKS=1` safe-mode escape hatch.

## Hardware & compatibility

![Printer compatibility — this project (PT-P750W command set) fans out to two containers. WORKS: PT-P750W (primary, half-cut · Wi-Fi), PT-P710BT (Cube Plus), PT-E550W — teal-accented, same command family. OUT OF SCOPE (for now, amber-dashed): PT-P300BT (Cube) and PT-P910BT (Cube Pro) are different command sets; QL / Dymo / Zebra are a different protocol entirely.](./docs/images/lp-compatibility.png)

- **Primary target: Brother PT-P750W** — 180 DPI, 128-pin head, TZe tapes 3.5–24 mm, USB + Wi-Fi, half-cut supported
- **Also works** with **PT-P710BT** ("Cube Plus") and **PT-E550W** — same raster command reference, same 128-pin head. The P710BT lacks half-cut hardware but silently ignores the bit.
- **Out of scope (for now)**: the smaller **PT-P300BT** (Cube, original) and the **PT-P910BT** (Cube Pro) — different command sets and different head geometry
- **Out of scope (for now)**: Brother QL shipping-label printers and Dymo / Zebra / Epson — completely different protocols

The encoder targets Brother's [Raster Command Reference for PT-E550W / PT-P750W / PT-P710BT](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf).

## Roadmap

- [x] **Phase 1** — raster encoder + `DryRunTransport` + byte goldens + cross-check against `brother_pt`
- [x] **Phase 2** — template engine + registry + template packs (kitchen / electronics / 3D-printing / utility)
- [x] **Phase 3** — CLI + HTTP service + Claude Code skill, all on `DryRunTransport`
- [x] **Pack primitive** — `TemplatePack` dataclass, `label_printer.packs` entry-point group, external packs as standalone pip packages
- [x] **Half-cut + multi-label batch** — chained print jobs with partial cuts between labels (PT-P750W)
- [x] **Icon engine** — curated Lucide bundle + optional full-set installers, opt-in per template
- [x] **Status parsing** — 32-byte packet decoded, `ensure_tape_matches()` gate for real sends
- [x] **Phase 4** — chat-bridge integration (Telegram) in dry-run
- [x] **Phase 5 (Wi-Fi)** — `NetworkTransport` over TCP:9100 + SNMP-based `lp status`; first physical prints landed
- [ ] **Phase 5 (USB / Bluetooth)** — direct-attach transports for offline use
- [ ] **Phase 6** — `lp print --remote <host>` for running the service on a dedicated machine

### Open proposals

- [Proposal 0001 — QR-code context linking](docs/proposals/0001-qr-context-linking.md) (open): let any label carry a small QR pointing at its canonical source of truth in an Obsidian vault or a GitHub repo. Resolved by Claude from a photo — no URL scheme drama, no hosted redirect, no "Obsidian not installed" dead-ends.

See [`docs/implementation-plan.md`](docs/implementation-plan.md) for the full phased plan.

## Development

```bash
.venv/bin/pytest                  # 124 tests — unit + integration
.venv/bin/pytest -m hardware      # transport tests, require the physical printer
.venv/bin/ruff check src tests
```

Regenerate byte goldens after an intentional encoder change:

```bash
REGEN_GOLDENS=1 .venv/bin/pytest tests/test_raster_encoder.py
```

Safe mode (skip all entry-point-registered external packs):

```bash
LABEL_PRINTER_DISABLE_ENTRY_POINT_PACKS=1 lp list
```

## Credits

Built from Brother's [official raster command manual](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf), informed by two excellent open-source implementations:

- [treideme/brother_pt](https://github.com/treideme/brother_pt) — Python USB driver, Apache 2.0
- [robby-cornelissen/pt-p710bt-label-maker](https://github.com/robby-cornelissen/pt-p710bt-label-maker) — Python Bluetooth driver

Bundled icons are [Lucide](https://lucide.dev/) (ISC) — see [`src/label_printer/icons/LICENSE-Lucide.txt`](src/label_printer/icons/LICENSE-Lucide.txt). Bundled fonts are DejaVu (Bitstream Vera derivative) — see [`src/label_printer/fonts/LICENSE-DejaVu.txt`](src/label_printer/fonts/LICENSE-DejaVu.txt). Full dependency list and license attributions in [`CREDITS.md`](CREDITS.md).

## License

MIT — see [`LICENSE`](LICENSE).
