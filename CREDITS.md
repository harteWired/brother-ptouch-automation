# Credits

This project's raster encoder was built by studying the Brother "Software
Developer's Manual — Raster Command Reference" (PT-E550W / PT-P750W /
PT-P710BT) alongside two excellent open-source implementations. No code is
copied from either project, but both significantly informed the design.

## Reference implementations

- **[treideme/brother_pt](https://github.com/treideme/brother_pt)** (Apache
  License 2.0) — Python USB driver and raster encoder for the PT-P710BT,
  PT-E550W, and PT-P750W. Used as the primary reference for the command
  sequence and as the cross-check target in `tests/test_raster_encoder.py`.

- **[robby-cornelissen/pt-p710bt-label-maker](https://github.com/robby-cornelissen/pt-p710bt-label-maker)**
  — Python Bluetooth driver specifically for the PT-P710BT. Will serve as
  the reference for the Bluetooth SPP transport in Phase 5.

## Protocol source of truth

- [Brother Software Developer's Manual — Raster Command Reference, PT-E550W / PT-P750W / PT-P710BT](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf)

## Bundled fonts

`src/label_printer/fonts/` contains the DejaVu Sans family (regular + bold +
mono). See `src/label_printer/fonts/LICENSE-DejaVu.txt` for the license.
Source: <https://dejavu-fonts.github.io/>.

## Runtime dependencies

- [Pillow](https://github.com/python-pillow/Pillow) — HPND
- [packbits](https://github.com/psd-tools/packbits) — MIT
- [Click](https://github.com/pallets/click) — BSD-3
- [python-barcode](https://github.com/WhyNotHugo/python-barcode) — BSD-3
- [qrcode](https://github.com/lincolnloop/python-qrcode) — BSD-3
- [FastAPI](https://github.com/tiangolo/fastapi) — MIT (optional, service extra)
