"""CLI: ``python -m invoice_creator serve | presets | send | send-all | build``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import load_settings
from .deliver import deliver
from .mail import auth_summary, build_message, eml_to_intake_json, message_bytes
from .models import SendRequest
from .presets import build_presets, demo_sequence, get_preset


def _request_from_preset(key: str, fmt: str | None, delivery: str, sender_kind: str | None) -> SendRequest:
    p = get_preset(key)
    sender = p.sender.model_copy(deep=True)
    if sender_kind:
        opt = next((o for o in p.sender_options if o.kind == sender_kind), None)
        if opt is None:
            raise SystemExit(f"preset {key!r} has no {sender_kind!r} sender option")
        sender.from_name, sender.from_addr, sender.reply_to = opt.from_name, opt.from_addr, opt.reply_to
    return SendRequest(
        invoice=p.invoice,
        sender=sender,
        format=fmt or p.format,  # type: ignore[arg-type]
        delivery=delivery,  # type: ignore[arg-type]
        scenario=p.key,
        label=p.title,
    )


def cmd_presets(_args: argparse.Namespace) -> int:
    for p in build_presets():
        flag = "  (follow-up)" if p.hidden else ""
        print(f"{p.key:16s} [{p.group}] {p.title}{flag}")
        print(f"{'':16s}     {p.vendor} · default format {p.format} · from {p.sender.from_addr}")
        print(f"{'':16s}     expected: {p.expected}")
    return 0


def _send_one(req: SendRequest, settings, out_dir: Path | None, as_json: bool) -> dict:
    msg, attachment = build_message(req, settings)
    raw = message_bytes(msg)
    envelope_from = req.sender.envelope_from or req.sender.from_addr
    result = deliver(req.delivery, msg, raw, settings, envelope_from=envelope_from)
    saved = None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = out_dir / f"{req.scenario or 'invoice'}-{req.invoice.invoice_number}.eml"
        saved.write_bytes(raw)
        if as_json:
            saved.with_suffix(".json").write_text(json.dumps(eml_to_intake_json(raw), indent=2))
    info = {
        "scenario": req.scenario,
        "invoice": req.invoice.invoice_number,
        "vendor": req.invoice.vendor_name,
        "amount": req.invoice.amount,
        "format": req.format,
        "from": req.sender.from_addr,
        "reply_to": req.sender.reply_to,
        "auth": auth_summary(req.sender),
        "delivery": req.delivery,
        "ok": result.ok,
        "detail": result.detail,
        "message_id": str(msg["Message-ID"]),
        "attachment": attachment.filename if attachment else None,
        "eml": str(saved) if saved else None,
    }
    return info


def cmd_send(args: argparse.Namespace) -> int:
    settings = load_settings()
    req = _request_from_preset(args.preset, args.format, args.delivery, args.sender)
    info = _send_one(req, settings, Path(args.out) if args.out else None, args.json)
    print(json.dumps(info, indent=2))
    return 0 if info["ok"] else 1


def cmd_send_all(args: argparse.Namespace) -> int:
    settings = load_settings()
    failures = 0
    for key in demo_sequence():
        req = _request_from_preset(key, args.format, args.delivery, None)
        info = _send_one(req, settings, Path(args.out) if args.out else None, args.json)
        mark = "ok " if info["ok"] else "FAIL"
        print(f"[{mark}] {key:16s} {info['invoice']:14s} {info['format']:4s} {info['detail']}")
        failures += 0 if info["ok"] else 1
        if args.pause:
            time.sleep(args.pause)
    return 1 if failures else 0


def cmd_build(args: argparse.Namespace) -> int:
    settings = load_settings()
    req = _request_from_preset(args.preset, args.format, "none", args.sender)
    msg, _ = build_message(req, settings)
    raw = message_bytes(msg)
    if args.out:
        Path(args.out).write_bytes(raw)
        print(f"wrote {args.out} ({len(raw)} bytes)")
    else:
        sys.stdout.buffer.write(raw)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .app import run

    settings = load_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    print(
        f"Vouch demo invoice creator → http://{settings.host}:{settings.port}  "
        f"(SMTP target {settings.smtp_host}:{settings.smtp_port}, to {settings.mail_to})"
    )
    run(settings)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invoice-creator", description="Vouch demo invoice creator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the web UI (default)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("presets", help="list demo presets")
    s.set_defaults(fn=cmd_presets)

    fmts = ["pdf", "png", "xlsx", "csv", "body"]
    deliveries = ["smtp", "receiver_http", "backend", "none"]

    s = sub.add_parser("send", help="build one preset and deliver it")
    s.add_argument("--preset", required=True)
    s.add_argument("--format", choices=fmts)
    s.add_argument("--delivery", choices=deliveries, default="smtp")
    s.add_argument("--sender", choices=["legit", "lookalike"], help="override the preset's sender identity")
    s.add_argument("--out", help="directory to also write the .eml into")
    s.add_argument("--json", action="store_true", help="also write the IntakeRequest JSON next to the .eml")
    s.set_defaults(fn=cmd_send)

    s = sub.add_parser("send-all", help="send every preset in demo order (follow-ups included)")
    s.add_argument("--format", choices=fmts, help="force one format for every preset")
    s.add_argument("--delivery", choices=deliveries, default="smtp")
    s.add_argument("--out")
    s.add_argument("--json", action="store_true")
    s.add_argument("--pause", type=float, default=0.0, help="seconds to wait between sends")
    s.set_defaults(fn=cmd_send_all)

    s = sub.add_parser("build", help="write the .eml for a preset without sending")
    s.add_argument("--preset", required=True)
    s.add_argument("--format", choices=fmts)
    s.add_argument("--sender", choices=["legit", "lookalike"])
    s.add_argument("--out")
    s.set_defaults(fn=cmd_build)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
