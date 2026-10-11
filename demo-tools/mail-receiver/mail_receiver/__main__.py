"""Entry point: ``python -m mail_receiver`` (or the ``mail-receiver`` script)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from . import __version__
from .config import load_settings
from .http_api import start_http
from .pipeline import Receiver
from .smtp_handler import start_smtp_servers

log = logging.getLogger("mail_receiver")


async def serve() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("mail.log").setLevel(logging.WARNING)  # aiosmtpd's per-command chatter
    log.info(
        "Vouch mail receiver %s starting: domain=%s accepting=%s forward=%s",
        __version__,
        settings.mail_domain,
        sorted(settings.accepted_addresses) if not settings.accept_any_recipient else "*",
        settings.backend_intake_url or "(store only)",
    )
    receiver = Receiver(settings)
    await receiver.start()
    smtp_servers = await start_smtp_servers(receiver)
    http_runner = await start_http(receiver)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - Windows
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    log.info("shutting down")
    for server in smtp_servers:
        server.close()
        await server.wait_closed()
    await http_runner.cleanup()
    await receiver.stop()


def main() -> int:
    with contextlib.suppress(KeyboardInterrupt):  # pragma: no cover
        asyncio.run(serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
