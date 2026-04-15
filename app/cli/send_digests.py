"""Send maintenance-task digest emails.

Designed to be invoked by a systemd timer:

    python -m app.cli.send_digests --frequency daily
    python -m app.cli.send_digests --frequency weekly --dry-run

Emits one JSON line per user processed on stdout, a summary on stderr,
and exits non-zero if any send failed.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from datetime import date, datetime

from app.config import get_settings
from app.database import get_session_factory
from app.logging_config import setup_logging
from app.services.email_reminders import DigestSendResult, send_digests, send_due_digests

logger = logging.getLogger(__name__)


def _digest_time(value: str) -> str:
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("time must use HH:MM format") from exc
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frequency",
        required=True,
        choices=("daily", "weekly"),
        help="Which user digest frequency bucket to send.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads and print recipients without calling Resend.",
    )
    parser.add_argument(
        "--due-now",
        action="store_true",
        help="Send only users whose configured digest time matches the current minute.",
    )
    parser.add_argument(
        "--at-time",
        type=_digest_time,
        help="HH:MM time to use with --due-now instead of the current local time.",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=7,
        help="Look-ahead window for upcoming tasks (default: 7).",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.at_time and not args.due_now:
        raise SystemExit("--at-time can only be used with --due-now")
    settings = get_settings()
    setup_logging(settings)
    digest_time = args.at_time or datetime.now().strftime("%H:%M")
    logger.info(
        "Starting maintenance digest send",
        extra={
            "frequency": args.frequency,
            "dry_run": args.dry_run,
            "due_now": args.due_now,
            "digest_time": digest_time if args.due_now else None,
        },
    )
    if args.due_now and not _should_send_today(args.frequency, _today()):
        results = []
    else:
        session = get_session_factory()()
        try:
            if args.due_now:
                results = send_due_digests(
                    session,
                    frequency=args.frequency,
                    digest_time=digest_time,
                    settings=settings,
                    dry_run=args.dry_run,
                    days_ahead=args.days_ahead,
                )
            else:
                results = send_digests(
                    session,
                    frequency=args.frequency,
                    settings=settings,
                    dry_run=args.dry_run,
                    days_ahead=args.days_ahead,
                )
        finally:
            session.close()

    for index, result in enumerate(results, start=1):
        print(json.dumps(_safe_result_payload(result, index)))

    summary = _summarize(results)
    logger.info(
        "Completed maintenance digest send",
        extra={
            "frequency": args.frequency,
            "dry_run": args.dry_run,
            "due_now": args.due_now,
            "digest_time": digest_time if args.due_now else None,
            "processed": summary["total"],
            "sent": summary["sent"],
            "skipped": summary["skipped"],
            "failed": summary["failed"],
        },
    )
    print(
        f"digest frequency={args.frequency} "
        f"processed={summary['total']} sent={summary['sent']} "
        f"skipped={summary['skipped']} failed={summary['failed']} "
        f"dry_run={summary['dry_run']}",
        file=sys.stderr,
    )
    return 1 if summary["failed"] else 0


def _should_send_today(frequency: str, today: date) -> bool:
    return frequency == "daily" or today.weekday() == 0


def _today() -> date:
    return date.today()


def _summarize(results: list[DigestSendResult]) -> dict[str, int]:
    counts = {"total": len(results), "sent": 0, "skipped": 0, "failed": 0, "dry_run": 0}
    for result in results:
        if result.status in counts:
            counts[result.status] += 1
    return counts


def _safe_result_payload(result: DigestSendResult, recipient_index: int) -> dict:
    payload = dataclasses.asdict(result)
    payload.pop("email", None)
    payload["recipient_index"] = recipient_index
    return payload


if __name__ == "__main__":
    sys.exit(run())
