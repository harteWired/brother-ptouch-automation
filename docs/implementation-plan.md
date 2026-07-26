---
type: plan
project: label-printer
created: 2026-04-18
updated: 2026-04-18
status: proposed
---

# Label Printer — Implementation Plan

Target hardware: **Brother PT-P750W** (primary — half-cut, Wi-Fi). Raster-compatible siblings PT-P710BT (Cube Plus) and PT-E550W are also supported. Python engine, Click CLI, eventual Claude Code skill. Default tape: 12mm. Printer lives on this machine for now, possibly a server later.

**Reorder note (2026-04-18)**: printer arrives **2026-04-19**. Plan now front-loads every phase that can be built, golden-tested, and dry-run without physical hardware. The moment the printer is on the bench, we should already have: raster bytes for all templates, the full template library, the CLI, and the skill — and the only work left is validating transport and swapping the dry-run stub for a real send.

## Architecture sketch

```
                   ┌─────────────────────────────────────────────┐
 CLI (lp) ────┐    │                 label_printer               │
              │    │                                             │
 Skill ───────┼──▶ │  templates ──▶ engine (Pillow)              │
              │    │                    │                        │
 Telegram ────┘    │                    ▼                        │
                   │              raster encoder                 │
                   │                    │                        │
                   │                    ▼                        │
                   │     transport {usb, bluetooth, dryrun}      │
                   └─────────────────────────────────────────────┘
                                        │
                                        ▼
                                  PT-P750W
```

**Key separation**: templates produce a Pillow `Image` given structured input; the engine converts images to Brother raster command bytes; transport writes bytes to USB / BT / a `DryRunTransport` that dumps to a file. Clients never see transport. This lets us build phases 1–4 with `DryRunTransport` and swap in the real transport in phase 5 without touching any template or engine code.

---

## Phase 1 — Package skeleton + raster encoder (pre-hardware)

**Goal**: `lp render` produces a byte-exact command stream for an arbitrary PNG. No printer needed.

1. `pyproject.toml` (uv): pillow, click, python-barcode, qrcode, pytest, ruff, mypy.
2. `src/label_printer/engine/raster.py`:
   - Pillow `Image` → 1-bit monochrome (Floyd-Steinberg dithering optional, off by default for text labels)
   - Align to the 128-pin head, pad per tape-width offset (table from Brother's spec)
   - TIFF-PackBits compression
   - Emit init + control codes + raster + print command per Brother Raster Command Reference
3. `src/label_printer/transport/base.py` — `Transport` protocol with `send(bytes) -> None`.
4. `src/label_printer/transport/dryrun.py` — writes the byte stream to a file, prints a hex summary. This is what every pre-hardware phase uses.
5. Golden byte tests under `tests/golden/raster/`:
   - `hello_12mm.png` + `hello_12mm.bin` — fixed input PNG, expected byte stream
   - Same for 24mm
   - Regression-guard the encoder: any accidental change to padding/compression shows up instantly
6. Cross-check against `treideme/brother_pt` and `robby-cornelissen/pt-p710bt-label-maker` — feed the same image, compare bytes. If they diverge, understand why before moving on. Document the findings in `research/encoder-validation.md`.

**Exit criteria**: raster encoder produces bytes we trust are correct (per spec + cross-check). `lp render --out hello.bin image.png` works. All goldens green.

---

## Phase 2 — Template engine + all three template packs (pre-hardware)

**Goal**: every label we plan to ship exists as a template, renders to PNG, has a golden.

1. Template base class: `Template(ABC)` with `render(data: dict, tape_mm: int) -> Image`. Registry auto-discovers templates from `templates/<category>/*.py` at startup.
2. Layout helpers in `engine/layout.py`: text fit-to-width, multi-line wrapping, icon/QR placement, dashed fold lines, Code128 barcodes via `python-barcode`.
3. Font bundle in `assets/fonts/` — DejaVu Sans + a condensed face. Pin versions, commit TTFs.
4. **Kitchen pack**:
   - `pantry_jar` — item + purchase date + expiry (optional)
   - `spice` — name + origin (optional) + best-by
   - `leftover` — contents + cooked date + "eat by" (auto +N days)
   - `freezer` — contents + frozen date + portion
5. **Electronics pack**:
   - `cable_flag` — source → destination, dashed fold line
   - `component_bin` — value + footprint + tolerance
   - `psu_polarity` — voltage, current, polarity, connector icon
6. **3D printing pack**:
   - `filament_spool` — material, color name + swatch, brand, date opened, print temp range
   - `print_bin` — part name + project + quantity
   - `tool_tag` — tool name + owning project
7. Golden PNG per template at both 12mm and 24mm.

**Exit criteria**: 10 templates render cleanly, 20 PNG goldens, registry discovers them via `lp list`.

---

## Phase 3 — CLI + skill + service skeleton (pre-hardware)

**Goal**: every client surface works end-to-end in dry-run mode.

1. CLI (`src/label_printer/cli.py`):
   - `lp list [--category X]`
   - `lp render <template> --tape 12 --out file.png ...fields`
   - `lp print <template> ...` — defaults to `DryRunTransport`, dumps `.bin` + renders PNG preview
   - `lp tape <width>` — persists current tape in `~/.config/label-printer/state.toml`
   - `lp scan` — stub (returns "hardware not connected yet")
2. Skill at `~/.claude/skills/label-printer/` (symlink from `skill/` in repo, matching prompt-master pattern):
   - SKILL.md with template catalog + schemas
   - Always dry-render first, show the user, require confirmation before real print
   - Skill triggers on: "labels", "label maker", "p-touch", "print a label", "tape"
3. Service skeleton `lp serve` — FastAPI daemon:
   - `POST /render` → PNG
   - `POST /print` → stub that calls `DryRunTransport` until Phase 5 flips it
   - bearer-token auth from `secrets-manager` (new `label-printer` namespace, key `PRINT_TOKEN`)
4. Tests: Click `CliRunner` covers all commands; skill doc linted; FastAPI `TestClient` covers both endpoints.

**Exit criteria**: from a fresh shell, a user can `lp print kitchen/pantry_jar --name Flour --purchased 2026-04-19` and get a PNG + `.bin` they can eyeball. Skill is invokable from any Claude Code session on this machine and produces the same artifacts. Service runs and responds.

---

## Phase 4 — Telegram wiring in dry-run (pre-hardware, optional)

**Goal**: prove the skill is callable from the Telegram channel before the printer arrives, so when it does arrive, only transport remains.

1. Confirm with telegram-channel that the integration path is: Telegram message → Claude session on this PC → `/label-printer` skill → `DryRunTransport`.
2. Add a "describe and print" convention to the skill: free-form text → skill picks the best template, confirms fields, dry-runs, then (post-hardware) prints.
3. Demo: send "label this: sriracha, opened 2026-04-19" from Telegram, receive the rendered PNG back in-chat, no physical print.

**Skip criterion**: skip this phase entirely if Phase 3 lands late on 2026-04-18 — it's nice-to-have pre-hardware. Phase 5 doesn't depend on it.

**Exit criteria**: a Telegram message produces a PNG back in Telegram, no printer involved.

---

## Phase 5 — Hardware day: transport + first physical print (2026-04-19+)

**Goal**: everything already works on paper; this phase just validates it prints.

1. Unbox and pair. Document the exact steps in `docs/setup.md`:
   - USB: udev rules, any vendor/product ID quirks
   - BT: device name, SPP channel, pairing command sequence
   - Confirm the devcontainer can see both (may need `--privileged` or device passthrough for BT — capture the workaround).
2. `transport/usb.py`: vendor the relevant pieces of `treideme/brother_pt`. Keep the public surface `Transport.send(bytes)` identical to `DryRunTransport`.
3. `transport/bluetooth.py`: port the SPP handshake + chunking from `robby-cornelissen/pt-p710bt-label-maker`.
4. **First physical print**: `lp print kitchen/pantry_jar --name "HELLO" --tape 12 --transport usb`. If this comes out right the first time, our Phase 1 goldens validated against the real printer and we can trust the encoder wholesale. If not, that's the bug to fix first.
5. Smoke-test every template in both tape widths we own (12mm + 24mm). Any template that looks wrong on paper vs. tape gets a fix in Phase 2 code and a regenerated golden.
6. Validate status/query commands — can we read tape width from the printer? If yes, wire it into `lp scan` and default `--tape` to the loaded cassette.
7. ~~Flip the service's `POST /print` stub from `DryRunTransport` to the real one.~~ **Done** — `POST /print` with `"send": true` now drives `NetworkTransport`, with the same host-resolution (`LABEL_PRINTER_HOST` → saved state) and SNMP tape-width pre-check the CLI uses.
8. Experiments to close out:
   - BT pairing stability over a reboot
   - Chaining / auto-cut / half-cut behavior (note findings in `research/brother-raster-protocol.md`)
   - Max raster line count before the printer chokes

**Exit criteria**: every shipped template prints correctly on 12mm and 24mm over both USB and BT. Setup doc is complete enough that a fresh machine can pair the printer in under 10 minutes.

---

## Phase 6 — Telegram end-to-end + service migration readiness (post-hardware)

**Goal**: close the loop and make the server migration a non-event when it happens.

1. Swap Phase 4's dry-run Telegram flow to actually print. Keep dry-run behind a `--preview` flag so we never accidentally print from Telegram without confirmation.
2. Add `lp print --remote <host>` so clients can call the service instead of the local transport. Same CLI, different transport class.
3. Actual server migration (whenever the user's ready): clone repo on target machine, `uv sync`, run the pairing doc from Phase 5, update clients to `--remote`. No code changes expected.

**Exit criteria**: Telegram message → physical label, end to end. A second machine can print via the service with a token from secrets-manager.

---

## Open questions / decisions deferred

- **Label preview in terminal**: sixel/kitty image output or just PNG + path? Start with PNG path; add terminal preview if it annoys us.
- **Multi-label batch jobs**: Brother spec supports chaining. Revisit in Phase 5 once we see real throughput.
- **Units**: SI (mm) at the boundary. No pt/inch/px in public APIs.
- **Persisted state**: `~/.config/label-printer/state.toml` for current tape + last transport. Never in-repo.
- **Pre-hardware raster trust**: we cross-check against reference libraries in Phase 1. If goldens disagree with real hardware output in Phase 5, the encoder is wrong, not the goldens — regenerate after the fix.

## Non-goals

- CUPS / system print queue
- Windows / macOS
- Importing `.lbx` files
- Cloud print service

## Risks

| Risk | Mitigation |
|---|---|
| Pre-hardware raster goldens diverge from what the printer actually accepts | Cross-check against 2+ reference libs in Phase 1; first physical print in Phase 5 is the validation gate. |
| BT SPP pairing flaky on Linux / in devcontainer | Do USB first on hardware day; BT second. Capture devcontainer quirks in setup doc. |
| Skill triggers too aggressively and prints without intent | Skill ALWAYS dry-runs + confirms first. No exception. |
| Server migration later breaks clients | `--remote` mode exists from Phase 3; migration is just flipping the host. |
