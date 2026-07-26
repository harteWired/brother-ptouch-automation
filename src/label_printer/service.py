"""HTTP service for remote printing.

`/render` returns a PNG, `/print` returns the raster command bytes by default
(dry-run) or drives the configured network transport when ``send=true``.
The printer host is resolved the same way the CLI resolves it: the
``LABEL_PRINTER_HOST`` environment variable, then the value persisted by
``lp printer set <ip>``.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any

try:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.responses import Response
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Install service extras: pip install -e '.[service]'"
    ) from e

from label_printer import encode_job
from label_printer import state as state_mod
from label_printer.engine.compose import compose_extras, strip_template_handled
from label_printer.status import (
    StatusQueryError,
    TapeMismatchError,
    check_tape_or_warn,
)
from label_printer.tape import TapeWidth
from label_printer.templates import default_registry
from label_printer.transport.network import NetworkTransport

app = FastAPI(title="label-printer", version="0.1.0")
_REGISTRY = default_registry()
_TOKEN_ENV = "LABEL_PRINTER_TOKEN"


def _require_token(authorization: str | None) -> None:
    expected = os.environ.get(_TOKEN_ENV)
    if not expected:
        return  # auth disabled if no token set (local dev)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    if authorization.split(" ", 1)[1] != expected:
        raise HTTPException(403, "bad token")


class RenderRequest(BaseModel):
    template: str
    tape_mm: int = 12
    fields: dict[str, Any] = {}
    # Optional post-render extras composed onto the right edge of any label.
    link: str | None = None
    image: str | None = None


def _render_body_with_extras(template, fields: dict, tape: TapeWidth,
                             link: str | None, image: str | None):
    extras = {k: v for k, v in {"link": link, "image": image}.items() if v}
    extras = strip_template_handled(extras, template)
    body = template.render(template.validate(fields), tape)
    return compose_extras(body, extras, tape)


class PrintRequest(RenderRequest):
    # Dry-run by default — opt in explicitly to drive the hardware transport.
    send: bool = False


def _resolve_printer_host() -> str:
    """Pick a printer host: LABEL_PRINTER_HOST env → saved state.

    Raises HTTPException(503) if neither is set — the service can't reach any
    printer without one.
    """
    resolved = state_mod.resolve_printer_host()
    if resolved:
        return resolved
    raise HTTPException(
        503,
        "no printer host configured. Set LABEL_PRINTER_HOST or run "
        "`lp printer set <ip>` on the service host.",
    )


def _verify_tape(transport: NetworkTransport, tape: TapeWidth) -> str | None:
    """Check the loaded tape matches the job. Returns a warning string if the
    check was skipped (SNMP unavailable), None on success. Raises
    HTTPException(409) on a real mismatch or printer error, 502 if the status
    query itself fails.
    """
    try:
        return check_tape_or_warn(transport, tape)
    except StatusQueryError as e:
        raise HTTPException(502, f"could not query printer status: {e}") from e
    except TapeMismatchError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "printer_configured": bool(state_mod.resolve_printer_host())}


@app.get("/templates")
def templates(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _require_token(authorization)
    return [
        {
            "qualified": t.meta.qualified,
            "summary": t.meta.summary,
            "default_tape_mm": int(t.meta.default_tape),
            "fields": [
                {
                    "name": f.name,
                    "description": f.description,
                    "required": f.required and f.default is None,
                    "default": f.default,
                    "example": f.example,
                }
                for f in t.meta.fields
            ],
        }
        for t in _REGISTRY
    ]


@app.post("/render")
def render(req: RenderRequest, authorization: str | None = Header(default=None)) -> Response:
    _require_token(authorization)
    try:
        template = _REGISTRY.get(req.template)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    tape = TapeWidth(4 if req.tape_mm in (3, 4) else req.tape_mm)
    image = _render_body_with_extras(template, req.fields, tape, req.link, req.image)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.post("/print")
def print_(req: PrintRequest, authorization: str | None = Header(default=None)) -> Response:
    """Encode a label. Dry-run by default; set ``send=true`` to drive the printer."""
    _require_token(authorization)
    try:
        template = _REGISTRY.get(req.template)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    tape = TapeWidth(4 if req.tape_mm in (3, 4) else req.tape_mm)
    image = _render_body_with_extras(template, req.fields, tape, req.link, req.image)
    data = encode_job(image, tape)

    if not req.send:
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"X-Dry-Run": "true", "X-Bytes": str(len(data))},
        )

    host = _resolve_printer_host()
    transport = NetworkTransport(host)
    warning = _verify_tape(transport, tape)
    try:
        transport.send(data)
    except OSError as e:
        raise HTTPException(502, f"could not reach printer at {host}: {e}") from e

    body: dict[str, Any] = {
        "sent": True,
        "host": host,
        "bytes": len(data),
    }
    if warning:
        body["warning"] = warning
    return Response(
        json.dumps(body),
        media_type="application/json",
        headers={"X-Dry-Run": "false", "X-Bytes": str(len(data))},
    )
