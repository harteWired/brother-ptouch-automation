---
name: label-printer
description: >
  Design and print labels on the Brother PT-P750W (primary target; PT-P710BT
  and PT-E550W also work via the same raster command set) from templates —
  kitchen (pantry jars, spice, leftovers, freezer), electronics (cable flags,
  component bins, PSU polarity), 3D printing (filament spools, print bins,
  tool tags). Invoke when the user asks for a label, mentions "label maker",
  "p-touch", "tape", or wants to label a physical object. Always dry-renders
  a PNG preview first and requires confirmation before sending to the printer.
allowed-tools: Bash, Read, Write
model: claude-sonnet-4-6
---

# Label Printer

You generate labels for the Brother PT-P750W (primary) via the `lp` CLI. The same commands work for the PT-P710BT and PT-E550W — they share the command set.

**Expected install**: `lp` on `$PATH`, OR set `LP` to the absolute path of the executable. On this machine: `LP=/workspace/projects/label-printer/.venv/bin/lp`. If that path is missing, ask the user where their `label-printer` checkout lives.

**Default tape: 12mm.** Many users also stock 24mm; confirm tape width if it matters.

## Core workflow

1. **Understand the request.** What's being labeled, and which template fits?
2. **Pick a template.** Run `lp list` if you're unsure; run `lp show <qualified>` to see its field schema. Never invent a template.
3. **Dry-render a PNG preview.** Always. Save to `/tmp/label_preview.png` and show the user. Do NOT print without explicit confirmation.
4. **Confirm, then print.** Once the user approves, run `lp print ... --send` (or `lp batch ... --send` for multiple labels). The network transport is wired up: `--send` actually drives the physical printer over Wi-Fi. Without `--send`, `lp print` dry-runs to a `.bin` file and prints a hex preview.
5. **Prefer 12mm** unless the user says otherwise or the label obviously needs width (e.g. large multi-field spool label).

## Template catalog

Packs ship for kitchen, electronics, 3D printing, calibration, garden, home-inventory, media, networking, pet, and travel. The full catalog changes as new packs land, so **always run `lp list` (or `lp list --category X`) to see what's currently installed** rather than relying on a memorised list. Use `lp show <qualified>` to inspect a template's fields.

## Commands you will use

```bash
# Discover
lp list
lp list --category kitchen
lp show kitchen/pantry_jar

# Dry-render preview to PNG (no bytes go anywhere near the printer)
lp render kitchen/pantry_jar \
  -f name=FLOUR -f purchased=2026-04-19 \
  --png-out /tmp/label_preview.png

# Encode-only (dry-run). Writes the raster command stream to a file.
# This is the DEFAULT. No flag needed.
lp print kitchen/pantry_jar \
  -f name=FLOUR -f purchased=2026-04-19 \
  --bin-out /tmp/label.bin

# Actually print. Add --send ONLY after the user has approved the preview.
lp print kitchen/pantry_jar \
  -f name=FLOUR -f purchased=2026-04-19 \
  --send
```

**`--send` is the only way tape moves.** Without it, `lp print` is always a dry-run — it encodes + writes bytes but never drives the transport. Never pass `--send` without the user's explicit approval of the preview.

### Adding a QR or a bitmap to any template

Two global flags compose onto the right edge of *any* template's output — no need for a QR-specific template:

```bash
# QR pointing at canonical context (Claude can decode the short-form later)
lp render kitchen/spice \
  -f name="Smoked Paprika" -f best_by=2027-03 \
  --link vault:kitchen/spices/paprika \
  --png-out /tmp/label_preview.png

# Arbitrary bitmap (icon, logo, photo) scaled to tape height
lp render three_d_printing/tool_tag \
  -f tool="Calipers" \
  --image ~/assets/aes-logo.png \
  --png-out /tmp/label_preview.png
```

`--link` accepts short-forms (`vault:...`, `gh:...`), URLs, or any opaque string. `--image` takes a path to a PNG/JPEG; it is fitted to tape height and threshold-converted to monochrome. Both flags also work on `lp print`. Templates that render their own QR / image (`utility/qr`, `utility/image`, `electronics/cable_flag` — which puts them on **each** face inside the wrap geometry) silently absorb the matching flag instead of letting `compose_extras` tack a copy onto the trailing edge.

## Rules

- **Always dry-render first.** Show the user the PNG, get an OK, then print. Even after hardware is wired up, never skip the preview.
- **Field values go via repeated `-f key=value`.** Quote values with spaces.
- **Dates in ISO 8601** (`YYYY-MM-DD`). Convert relative dates ("today", "last Tuesday") before calling.
- **Use `lp show <template>` to check required fields** before constructing the command. Don't guess.
- **Free-form requests**: infer the best template, confirm your pick with the user before rendering. If multiple could fit (e.g. "label this jar of paprika"), ask.
- **If the user sends a photo**: read the text yourself from the image (vision) and extract the fields. Don't rely on OCR tooling — the model reads labels better than a CLI pipeline.

## When the request arrives via Telegram

If the incoming message is a `<channel source="telegram" chat_id="..." ...>` tag, the user is on their phone and cannot see your terminal output or the filesystem. The PNG preview must go back to them as a Telegram attachment.

1. React with ✍ on the incoming message so they know you're preparing their label. (Avoid 🏷 — not on Telegram's reaction whitelist; the Bot API rejects it with `REACTION_INVALID`.)
2. Render the preview PNG to a stable path like `/tmp/label_preview.png`.
3. Reply with the PNG attached: `reply(chat_id=<from the tag>, text="preview — ok to print?", files=["/tmp/label_preview.png"])`. Describe what you rendered in one line so they can sanity-check without opening the image.
4. Wait for explicit "yes" / "print" / "send it" before adding `--send`. Never `--send` unprompted — it's the only thing that moves tape.
5. For free-form requests ("label this: sriracha, opened yesterday"), infer the best template, name it in your reply ("using `kitchen/pantry_jar`, tape 12mm"), and let them redirect before rendering if the pick is wrong.
6. On success with `--send`, send a new reply (not an edit) with "printed ✅" so their phone pings. If `--send` fails with "no printer host configured," tell them to run `lp printer set <ip>` once. If it fails because the printer is unreachable, suggest `lp scan` to verify connectivity.

## Failure modes

- `lp` not found → tell the user to activate their `label-printer` venv, or set `LP=/abs/path/to/lp`.
- Template not found → run `lp list` and pick the closest match, or ask.
- Missing required field → `lp show` the template, prompt the user for the missing piece, then retry.
- Network transport error → confirm `lp printer show` is set; `lp scan` to test reachability. SNMP-based `lp status` requires SNMP enabled on the printer (default on the PT-P750W). USB / Bluetooth transports aren't wired up yet.
