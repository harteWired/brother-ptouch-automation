"""Command-line entry point: `lp`."""

from __future__ import annotations

from pathlib import Path

import click
from PIL import Image

from label_printer import RasterOptions, TapeWidth, encode_batch, encode_job
from label_printer import state as state_mod
from label_printer.engine.compose import compose_extras, strip_template_handled
from label_printer.tape import geometry_for
from label_printer.templates import default_registry
from label_printer.transport.dryrun import DryRunTransport
from label_printer.transport.network import NetworkTransport


def _resolve_host(host: str | None) -> str:
    """Pick a printer host: explicit flag → LABEL_PRINTER_HOST env → saved state."""
    if host:
        return host
    resolved = state_mod.resolve_printer_host()
    if resolved:
        return resolved
    raise click.ClickException(
        "no printer host configured. Pass --host, set LABEL_PRINTER_HOST, "
        "or run `lp printer set <ip>` to persist one."
    )


def _make_transport(transport_name: str, host: str | None):
    """Build a hardware transport. USB/Bluetooth not implemented yet."""
    if transport_name == "network":
        return NetworkTransport(_resolve_host(host))
    raise click.ClickException(
        f"transport '{transport_name}' not available yet — only 'network' "
        "(Wi-Fi / Ethernet) is wired up. USB and Bluetooth land later."
    )


def _verify_tape_or_die(transport, tape: TapeWidth) -> None:
    """Query the printer and bail if the loaded tape doesn't match the job's.

    For transports that can't query status (currently NetworkTransport — Brother
    network firmware uses TCP:9100 as write-only), warn and proceed without
    verification.
    """
    from label_printer.status import (
        StatusQueryError,
        TapeMismatchError,
        check_tape_or_warn,
    )
    try:
        warning = check_tape_or_warn(transport, tape)
    except StatusQueryError as e:
        raise click.ClickException(f"could not query printer status: {e}") from e
    except TapeMismatchError as e:
        raise click.ClickException(str(e)) from e
    if warning:
        click.secho(f"warning: {warning}", fg="yellow")


def _render_with_extras(template, data: dict, tape: TapeWidth,
                        link: str | None, image: str | None) -> Image.Image:
    """Render the template, then compose any post-render extras onto the body."""
    extras = {k: v for k, v in {"link": link, "image": image}.items() if v}
    extras = strip_template_handled(extras, template)
    body = template.render(data, tape)
    return compose_extras(body, extras, tape)


def _tape_from_mm(mm: int) -> TapeWidth:
    try:
        return TapeWidth(4 if mm in (3, 4) else mm)
    except ValueError as e:
        valid = ", ".join(str(int(t)) for t in TapeWidth)
        raise click.BadParameter(f"tape must be one of: {valid}") from e


def _default_tape() -> int:
    try:
        return state_mod.load().tape_mm
    except Exception:
        return 12


def _parse_fields(pairs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(f"expected key=value, got {pair!r}")
        k, v = pair.split("=", 1)
        out[k.strip()] = v
    return out


@click.group()
@click.version_option()
def main() -> None:
    """Brother PT-P750W label printer automation (also supports PT-P710BT and PT-E550W)."""


# --- Registry-driven commands -----------------------------------------------

@main.command("list")
@click.option("--category", type=str, default=None, help="Filter by category.")
def list_templates(category: str | None) -> None:
    """List available label templates."""
    reg = default_registry()
    items = reg.by_category(category) if category else list(reg)
    if not items:
        click.echo("No templates found.")
        return
    width = max(len(t.meta.qualified) for t in items)
    for t in sorted(items, key=lambda x: x.meta.qualified):
        click.echo(f"  {t.meta.qualified:<{width}}  {t.meta.summary}")


@main.command()
@click.argument("qualified")
def show(qualified: str) -> None:
    """Show a template's field schema."""
    reg = default_registry()
    try:
        template = reg.get(qualified)
    except KeyError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"{template.meta.qualified}")
    click.echo(f"  {template.meta.summary}")
    click.echo(f"  default tape: {int(template.meta.default_tape)}mm")
    click.echo("  fields:")
    for f in template.meta.fields:
        req = "required" if f.required and f.default is None else "optional"
        default = f" (default: {f.default!r})" if f.default is not None else ""
        example = f"  e.g. {f.example!r}" if f.example else ""
        click.echo(f"    - {f.name}  [{req}]{default}{example}")
        click.echo(f"      {f.description}")


@main.command(name="render")
@click.argument("qualified")
@click.option("--tape", "tape_mm", type=int, default=None, help="Tape width in mm.")
@click.option("-f", "--field", "fields", multiple=True, help="key=value template field.")
@click.option("--link", type=str, default=None,
              help="QR payload appended to the right edge (short-form, URL, or opaque string).")
@click.option("--image", "image_path", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Path to a bitmap appended to the right edge (fit to tape height).")
@click.option("--png-out", type=click.Path(path_type=Path), default=None,
              help="Where to save the rendered PNG preview.")
@click.option("--bin-out", type=click.Path(path_type=Path), default=None,
              help="Where to save the raw command stream.")
def render_template(qualified: str, tape_mm: int | None, fields: tuple[str, ...],
                    link: str | None, image_path: str | None,
                    png_out: Path | None, bin_out: Path | None) -> None:
    """Render a template to a PNG and/or raster command stream (no printing)."""
    reg = default_registry()
    try:
        template = reg.get(qualified)
    except KeyError as e:
        raise click.ClickException(str(e)) from e

    tape = _tape_from_mm(tape_mm) if tape_mm else template.meta.default_tape
    data = template.validate(_parse_fields(fields))
    image = _render_with_extras(template, data, tape, link, image_path)

    if png_out is None and bin_out is None:
        png_out = Path(f"out_{qualified.replace('/', '_')}_{int(tape)}mm.png")

    if png_out:
        png_out.parent.mkdir(parents=True, exist_ok=True)
        image.save(png_out)
        click.echo(f"png: {png_out}  ({image.width}×{image.height})")

    if bin_out:
        cmd_bytes = encode_job(image, tape)
        transport = DryRunTransport(bin_out)
        transport.send(cmd_bytes)
        click.echo(f"bin: {bin_out}  ({len(cmd_bytes)} bytes)")


@main.command(name="print")
@click.argument("qualified")
@click.option("--tape", "tape_mm", type=int, default=None)
@click.option("-f", "--field", "fields", multiple=True, help="key=value template field.")
@click.option("--link", type=str, default=None,
              help="QR payload appended to the right edge (short-form, URL, or opaque string).")
@click.option("--image", "image_path", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Path to a bitmap appended to the right edge (fit to tape height).")
@click.option(
    "--send/--dry-run",
    default=False,
    show_default=True,
    help="Actually send the job to the printer. Default is dry-run — the "
         "command stream is written to a file and nothing is sent.",
)
@click.option(
    "--transport", "transport_name",
    type=click.Choice(["network", "usb", "bluetooth"]),
    default="network", show_default=True,
    help="Hardware transport to use when --send is set.",
)
@click.option("--host", "printer_host", type=str, default=None,
              help="Printer host/IP (for --transport network). Falls back to "
                   "LABEL_PRINTER_HOST env var, then saved state.")
@click.option("--bin-out", type=click.Path(path_type=Path), default=Path("out.bin"),
              help="Dry-run output path (ignored when --send is set).")
def print_template(qualified: str, tape_mm: int | None, fields: tuple[str, ...],
                   link: str | None, image_path: str | None,
                   send: bool, transport_name: str, printer_host: str | None,
                   bin_out: Path) -> None:
    """Encode + (dry-run|send) a template-based label.

    By default this is a dry-run: the label is rendered and encoded, the
    raster command bytes are written to ``--bin-out``, and a hex preview is
    printed. Pass ``--send`` to actually drive the hardware transport.
    """
    reg = default_registry()
    try:
        template = reg.get(qualified)
    except KeyError as e:
        raise click.ClickException(str(e)) from e

    tape = _tape_from_mm(tape_mm) if tape_mm else template.meta.default_tape
    data = template.validate(_parse_fields(fields))
    image = _render_with_extras(template, data, tape, link, image_path)
    cmd_bytes = encode_job(image, tape)

    if not send:
        transport = DryRunTransport(bin_out)
        transport.send(cmd_bytes)
        click.echo(transport.hex_preview(cmd_bytes))
        click.secho(
            "dry-run: nothing was printed. Pass --send to drive the printer.",
            fg="yellow",
        )
        return

    transport = _make_transport(transport_name, printer_host)
    _verify_tape_or_die(transport, tape)
    transport.send(cmd_bytes)
    click.secho(
        f"sent {len(cmd_bytes)} bytes to {transport.name} ({getattr(transport, 'host', '?')}).",
        fg="green",
    )


# --- Image-to-raster passthrough (Phase 1 surface, still useful) ------------

@main.command("render-image")
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--tape", "tape_mm", type=int, default=None, show_default=True,
              help=f"Tape width in mm (default from state, currently {_default_tape()}).")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=Path("out.bin"),
              show_default=True, help="Where to write the raster command stream.")
@click.option("--no-auto-cut", is_flag=True)
@click.option("--no-half-cut", is_flag=True, help="Disable half-cut (PT-P750W only).")
@click.option("--mirror", is_flag=True)
@click.option("--feed-dots", type=int, default=14, show_default=True)
def render_image(image_path: Path, tape_mm: int | None, out_path: Path, no_auto_cut: bool,
                 no_half_cut: bool, mirror: bool, feed_dots: int) -> None:
    """Render an arbitrary image (skipping templates) to a command stream."""
    tape = _tape_from_mm(tape_mm) if tape_mm else _tape_from_mm(_default_tape())
    img = Image.open(image_path)
    options = RasterOptions(
        auto_cut=not no_auto_cut, mirror=mirror,
        half_cut=not no_half_cut, feed_dots=feed_dots,
    )
    data = encode_job(img, tape, options)
    transport = DryRunTransport(out_path)
    transport.send(data)
    click.echo(transport.hex_preview(data))


# --- State + geometry --------------------------------------------------------

@main.command()
@click.argument("width", type=int)
def tape(width: int) -> None:
    """Persist the currently-loaded tape width (mm)."""
    _tape_from_mm(width)  # validates
    state = state_mod.load()
    state.tape_mm = width
    path = state_mod.save(state)
    click.echo(f"tape = {width}mm  (saved to {path})")


@main.command("tape-info")
def tape_info() -> None:
    """Show geometry for each supported tape width."""
    click.echo(f"{'width':>7}  {'margin':>6}  {'print':>5}")
    for t in TapeWidth:
        geom = geometry_for(t)
        click.echo(f"{geom.display_mm:>5.1f}mm  {geom.margin_pins:>6}  {geom.print_pins:>5} pins")


@main.command()
@click.option("--host", "printer_host", type=str, default=None,
              help="Override the saved printer host for this probe.")
def scan(printer_host: str | None) -> None:
    """Probe the configured printer host and report whether it's reachable on TCP:9100."""
    try:
        host = _resolve_host(printer_host)
    except click.ClickException as e:
        click.echo(str(e.message))
        return
    transport = NetworkTransport(host)
    try:
        transport.probe()
    except OSError as e:
        click.secho(f"unreachable: {host}:{transport.port} — {e}", fg="red")
        raise click.exceptions.Exit(1) from None
    click.secho(f"reachable: {host}:{transport.port}", fg="green")


@main.command()
@click.option(
    "--transport", "transport_name",
    type=click.Choice(["network", "usb", "bluetooth"]),
    default="network", show_default=True,
)
@click.option("--host", "printer_host", type=str, default=None,
              help="Printer host/IP (for --transport network).")
def status(transport_name: str, printer_host: str | None) -> None:
    """Query the printer and report loaded tape + any error flags.

    Returns non-zero on any error condition (wrong media, cover open,
    overheating, etc.) so scripts can gate on it.
    """
    transport = _make_transport(transport_name, printer_host)
    try:
        snap = transport.query_status()
    except Exception as e:
        raise click.ClickException(f"could not query status: {e}") from e
    loaded = snap.tape_width()
    width_str = f"{int(loaded)}mm" if loaded else f"{snap.media_width_mm}mm (unknown)"
    click.echo(f"tape:  {width_str}")
    click.echo(f"media: {'loaded' if snap.has_media else 'absent'}")
    errors = snap.describe_errors()
    if errors:
        click.secho(f"errors: {', '.join(errors)}", fg="red")
        raise click.exceptions.Exit(1)
    click.secho("ok", fg="green")


@main.group()
def printer() -> None:
    """Configure printer connection (host/IP)."""


@printer.command("set")
@click.argument("host")
def printer_set(host: str) -> None:
    """Persist the printer host/IP for future commands."""
    state = state_mod.load()
    state.printer_host = host
    path = state_mod.save(state)
    click.echo(f"printer_host = {host}  (saved to {path})")


@printer.command("show")
def printer_show() -> None:
    """Show the configured printer host."""
    state = state_mod.load()
    if state.printer_host:
        click.echo(state.printer_host)
    else:
        click.echo("(unset — pass --host or run `lp printer set <ip>`)")


@main.command()
def packs() -> None:
    """List installed template packs (built-in + entry-point-registered)."""
    reg = default_registry()
    width = max(len(p.name) for p in reg.packs.values())
    for pack in sorted(reg.packs.values(), key=lambda p: p.name):
        click.echo(f"  {pack.name:<{width}}  v{pack.version}  ({len(pack.templates)} templates)")
        click.echo(f"  {' ':<{width}}  {pack.summary}")
        if pack.homepage:
            click.echo(f"  {' ':<{width}}  {pack.homepage}")
    if reg.failed_packs:
        click.echo("")
        click.secho("failed packs (entry-point load error):", fg="red")
        for name, reason in sorted(reg.failed_packs.items()):
            click.echo(f"  {name}: {reason}")


@main.command()
def wires() -> None:
    """List known cable/wire specs and their approximate outer diameters."""
    from label_printer.engine.wire import _AWG_OD_MM, _CABLE_OD_MM
    click.echo("Cable keywords:")
    width = max(len(k) for k in _CABLE_OD_MM)
    for key in sorted(_CABLE_OD_MM):
        click.echo(f"  {key:<{width}}  {_CABLE_OD_MM[key]:>5.1f} mm")
    click.echo("\nAWG (insulated hookup wire):")
    for gauge in sorted(_AWG_OD_MM, reverse=True):
        click.echo(f"  {gauge:>3d} AWG   {_AWG_OD_MM[gauge]:>5.1f} mm")


# --- Batch printing ---------------------------------------------------------

@main.command(name="batch")
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--send/--dry-run",
    default=False, show_default=True,
    help="Actually send the chained job to the printer. Default: dry-run.",
)
@click.option(
    "--no-half-cut", is_flag=True,
    help="Disable half-cut between labels (full cut between each). P750W only.",
)
@click.option(
    "--transport", "transport_name",
    type=click.Choice(["network", "usb", "bluetooth"]),
    default="network", show_default=True,
)
@click.option("--host", "printer_host", type=str, default=None,
              help="Printer host/IP (for --transport network).")
@click.option("--bin-out", type=click.Path(path_type=Path), default=Path("batch.bin"),
              show_default=True, help="Dry-run output path.")
def batch_cmd(spec_file: Path, send: bool, no_half_cut: bool,
              transport_name: str, printer_host: str | None, bin_out: Path) -> None:
    """Print multiple labels as a single chained job.

    SPEC_FILE is a JSON array — each element specifies one label:

    \b
        [
          {"template": "kitchen/pantry_jar", "tape_mm": 12,
           "fields": {"name": "AP Flour", "purchased": "2026-04-19"}},
          {"template": "kitchen/spice",
           "fields": {"name": "Smoked Paprika", "origin": "Spain"}}
        ]

    All labels must use the same tape width (chained jobs can't switch tape
    mid-job). With half-cut enabled (default), labels come off the printer
    as a single strip separated by partial cuts — much easier to handle
    than N separate strips.
    """
    import json
    raw = json.loads(spec_file.read_text())
    if not isinstance(raw, list) or not raw:
        raise click.ClickException("spec file must be a non-empty JSON array")

    reg = default_registry()
    tapes: set[int] = set()
    images = []
    for i, entry in enumerate(raw):
        try:
            template = reg.get(entry["template"])
        except KeyError as e:
            raise click.ClickException(f"entry {i}: {e}") from e
        tape_mm = int(entry.get("tape_mm", int(template.meta.default_tape)))
        tapes.add(tape_mm)
        data = template.validate(entry.get("fields", {}))
        images.append(template.render(data, _tape_from_mm(tape_mm)))

    if len(tapes) != 1:
        raise click.ClickException(
            f"all batch entries must share one tape width; got {sorted(tapes)}"
        )
    tape = _tape_from_mm(tapes.pop())
    options = RasterOptions(half_cut=not no_half_cut)
    cmd_bytes = encode_batch(images, tape, options)

    click.echo(f"batched {len(images)} label(s) → {len(cmd_bytes)} bytes")
    if not send:
        DryRunTransport(bin_out).send(cmd_bytes)
        click.echo(f"bin: {bin_out}")
        click.secho(
            "dry-run: nothing was printed. Pass --send to drive the printer.",
            fg="yellow",
        )
        return

    transport = _make_transport(transport_name, printer_host)
    _verify_tape_or_die(transport, tape)
    transport.send(cmd_bytes)
    click.secho(
        f"sent {len(cmd_bytes)} bytes to {transport.name} ({getattr(transport, 'host', '?')}).",
        fg="green",
    )


# --- Icons -------------------------------------------------------------------

@main.group()
def icons() -> None:
    """Manage icon packs (optional, used by templates that opt in)."""


@icons.command("list")
@click.option("--source", default=None, help="Filter by source (e.g. 'lucide', 'mdi').")
def icons_list(source: str | None) -> None:
    """List available icons."""
    from label_printer.engine.icons import has_engine, registry
    if not has_engine():
        click.secho(
            "cairosvg not installed — icons can't render. Run: "
            "pip install 'label-printer[icons]'",
            fg="yellow",
        )
    items = registry().available(source)
    if not items:
        click.echo("no icons found. Run `lp icons install-lucide` or "
                   "`lp icons install-mdi` to install a full set.")
        return
    for name in items:
        click.echo(f"  {name}")


@icons.command("preview")
@click.argument("name")
@click.option("--size", default=64, show_default=True, help="Square size in dots.")
@click.option("--out", "out_path", type=click.Path(path_type=Path),
              default=Path("icon-preview.png"), show_default=True)
def icons_preview(name: str, size: int, out_path: Path) -> None:
    """Render an icon to a preview PNG."""
    from label_printer.engine.icons import IconNotFoundError, load_icon
    try:
        img = load_icon(name, size)
    except IconNotFoundError as e:
        raise click.ClickException(str(e)) from e
    img.save(out_path)
    click.echo(f"{name} → {out_path} ({img.width}×{img.height})")


@icons.command("install-lucide")
def icons_install_lucide() -> None:
    """Clone the full Lucide icon set to the user config directory."""
    from label_printer.engine.icons import USER_ROOT
    _install_icon_repo(
        repo="https://github.com/lucide-icons/lucide.git",
        subdir="icons",
        target=USER_ROOT / "lucide",
        display="Lucide (~1500 icons, ISC)",
    )


@icons.command("install-mdi")
def icons_install_mdi() -> None:
    """Clone the Material Design Icons set to the user config directory."""
    from label_printer.engine.icons import USER_ROOT
    _install_icon_repo(
        repo="https://github.com/Templarian/MaterialDesign-SVG.git",
        subdir="svg",
        target=USER_ROOT / "mdi",
        display="Material Design Icons (~7000 icons, Apache 2.0)",
    )


def _install_icon_repo(*, repo: str, subdir: str, target: Path, display: str) -> None:
    import shutil
    import subprocess
    import tempfile
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        click.confirm(
            f"{target} already exists. Replace it?",
            abort=True, default=False,
        )
        shutil.rmtree(target)
    click.echo(f"Cloning {display} from {repo} (shallow)...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        subprocess.run(
            ["git", "clone", "--depth", "1", repo, str(tmp_path / "repo")],
            check=True,
        )
        shutil.copytree(tmp_path / "repo" / subdir, target)
    count = sum(1 for _ in target.rglob("*.svg"))
    click.secho(f"Installed {count} icons to {target}", fg="green")


# --- Service mode ------------------------------------------------------------

@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
def serve(host: str, port: int) -> None:
    """Run the label-printer HTTP service.

    `/print` is a dry-run unless the request body sets ``send=true``, in which
    case the service drives the network transport. Set ``LABEL_PRINTER_HOST``
    (or run `lp printer set <ip>` once) so the service knows where to send.
    """
    try:
        import uvicorn
    except ImportError as e:
        raise click.ClickException(
            "Install the service extras: pip install -e '.[service]'"
        ) from e
    from label_printer.service import app

    click.echo(f"label-printer service on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
