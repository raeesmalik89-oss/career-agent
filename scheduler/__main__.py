"""The scheduler process: `python -m scheduler` (loop) or `python -m scheduler --once` (single pass, for cron or
Windows Task Scheduler). Needs PYTHONPATH=backend;. like the API."""

import argparse
import logging
import signal
import threading

from app.db.session import get_sessionmaker
from scheduler.runner import tick

log = logging.getLogger("scheduler")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="scheduler")
    p.add_argument("--once", action="store_true", help="run whatever is due now, then exit")
    p.add_argument("--interval", type=int, default=30, help="seconds between checks (default 30)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    factory = get_sessionmaker()
    log.info("scheduler started (checking every %ss; Ctrl+C to stop)", args.interval)
    while True:
        try:
            for r in tick(factory):
                log.info("%s finished: %s (%s)", r["pipeline"], r["status"], r["trigger"])
        except Exception:  # noqa: BLE001 - keep the loop alive; the next tick retries
            log.exception("scheduler tick failed")
        if args.once or stop.wait(max(args.interval, 5)):
            break
    log.info("scheduler stopped")


if __name__ == "__main__":
    main()
